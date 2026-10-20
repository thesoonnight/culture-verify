"""把「评分集 + 图片集」导入成可标注的数据集。

支持：
  * tasks.jsonl / tasks.json / tasks.csv
  * 图片按相对路径、绝对路径或 --images 目录解析
  * zip 包（根目录或单层子目录里放 tasks.* + images/ + 可选 config.json）
  * 导入前完整校验，失败时列清所有问题，不落半成品
"""
from __future__ import annotations

import csv
import io
import json
import shutil
import tempfile
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Any

from .storage import Storage, utc_now, valid_name

DEFAULT_DIMENSIONS = [
    {"id": "d1", "label": "文化元素准确性", "question": "图中服饰、器物、纹样等文化元素的形制与符号是否符合该文化？"},
    {"id": "d2", "label": "无西方化错配", "question": "是否存在西方中心化的错配、替换或刻板化简化？"},
    {"id": "d3", "label": "图内文字可读性", "question": "图内文字是否字形正确、笔画完整、可读？"},
]
DEFAULT_CRITERIA = [
    {"id": "q1", "label": "画面质感", "question": "材质、光影、颗粒与整体画面完成度"},
    {"id": "q2", "label": "细节真实度", "question": "局部结构、边缘与纹理的精细程度"},
]

MAX_ZIP_BYTES = 1024 * 1024 * 1024  # 1 GB

TASK_NAMES = ("tasks.jsonl", "tasks.json", "tasks.csv")
CONFIG_NAMES = ("config.json", "dataset.json")


class ImportProblem(Exception):
    def __init__(self, messages: list[str] | str):
        if isinstance(messages, str):
            messages = [messages]
        self.messages = messages
        super().__init__("；".join(messages[:6]))


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------
def read_task_rows(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8-sig")
    if suffix == ".jsonl":
        rows = []
        for n, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ImportProblem(f"{path.name} 第 {n} 行不是合法 JSON：{exc}") from exc
        return rows
    if suffix == ".json":
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("tasks"), list):
            return data["tasks"]
        if isinstance(data, list):
            return data
        raise ImportProblem(f"{path.name} 需要是数组，或含 tasks 数组的对象")
    if suffix == ".csv":
        return rows_to_tasks(read_csv_rows(text))
    raise ImportProblem(f"不支持的评分集格式：{path.suffix}（用 .jsonl / .json / .csv）")


def _norm_header(name: str) -> str:
    return (name or "").strip().lower().replace(" ", "").replace("_", "")


HEADER_ALIASES = {
    "类型": "type",
    "mode": "type",
    "题目id": "id",
    "题号": "id",
    "id": "id",
    "提示词": "prompt",
    "prompt": "prompt",
    "图片": "image",
    "图片路径": "image",
    "图片a": "images_a",
    "图片b": "images_b",
    "图a": "images_a",
    "图b": "images_b",
    "imagesa": "images_a",
    "imagesb": "images_b",
    "文化轴": "axis",
    "轴": "axis",
    "语言": "lang",
    "地区": "region",
    "判定项id": "item_id",
    "判定项": "item_label",
    "判定项名称": "item_label",
    "判定项说明": "item_question",
    "判断说明": "item_question",
    "itemid": "item_id",
    "itemlabel": "item_label",
    "itemquestion": "item_question",
    "分数": "score",
    "评审分数": "score",
    "打分": "score",
    "理由": "rationale",
    "评审理由": "rationale",
    "评分维度id": "criterion_id",
    "评分维度": "criterion_label",
    "维度名称": "criterion_label",
    "维度说明": "criterion_question",
    "criterionid": "criterion_id",
    "criterionlabel": "criterion_label",
    "criterionquestion": "criterion_question",
    "分数a": "score_a",
    "分数b": "score_b",
    "a分": "score_a",
    "b分": "score_b",
    "scorea": "score_a",
    "scoreb": "score_b",
    "备注": "note",
}


def read_csv_rows(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ImportProblem("CSV 没有表头")
    mapping = {}
    for name in reader.fieldnames:
        key = _norm_header(name)
        mapping[name] = HEADER_ALIASES.get(key, key)
    rows = []
    for row in reader:
        item = {mapping[k]: (v or "").strip() for k, v in row.items() if k in mapping}
        if any(item.values()):
            rows.append(item)
    return rows


def rows_to_tasks(rows: list[dict]) -> list[dict]:
    """把 CSV 的长表（一行一个判定项/维度）折叠成任务对象。"""
    grouped: "OrderedDict[tuple[str, str], dict]" = OrderedDict()
    for row in rows:
        mode = (row.get("type") or "pointwise").strip().lower()
        if mode in {"single", "image", "t2i", "单图"}:
            mode = "pointwise"
        if mode in {"pair", "compare", "双图"}:
            mode = "pairwise"
        tid = str(row.get("id") or "").strip()
        if not tid:
            raise ImportProblem("CSV 每一行都需要 id")
        key = (mode, tid)
        if key not in grouped:
            task: dict[str, Any] = {
                "mode": mode,
                "id": tid,
                "prompt": row.get("prompt") or "",
                "axis": row.get("axis") or "",
                "lang": row.get("lang") or "",
                "region": row.get("region") or "",
            }
            if mode == "pointwise":
                task["image"] = row.get("image") or ""
                task["items"] = []
                grouped[key] = task
                if not task["image"]:
                    continue
            else:
                task["images"] = {"A": row.get("images_a") or "", "B": row.get("images_b") or ""}
                task["criteria"] = []
                task["scores"] = {"A": {}, "B": {}}
                grouped[key] = task
            if row.get("note"):
                task["note"] = row["note"]
        task = grouped[key]
        if mode == "pointwise":
            if not row.get("score"):
                continue
            task["items"].append(
                {
                    "id": row.get("item_id") or "",
                    "label": row.get("item_label") or "",
                    "question": row.get("item_question") or "",
                    "score": row.get("score"),
                    "rationale": row.get("rationale") or "",
                }
            )
        else:
            cid = row.get("criterion_id") or ""
            if not cid:
                continue
            task["criteria"].append(
                {
                    "id": cid,
                    "label": row.get("criterion_label") or "",
                    "question": row.get("criterion_question") or "",
                }
            )
            task["scores"]["A"][cid] = row.get("score_a")
            task["scores"]["B"][cid] = row.get("score_b")
    return list(grouped.values())


# --------------------------------------------------------------------------
# normalizing / validating
# --------------------------------------------------------------------------
def _as_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field} 不能为空")
    try:
        return int(float(text))
    except ValueError as exc:
        raise ValueError(f"{field} 不是数字：{value!r}") from exc


def normalize_task(raw: dict, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("任务必须是对象")
    mode = str(raw.get("mode") or raw.get("type") or "").strip().lower()
    if mode in {"pointwise", "single", "image", "t2i", "单图"}:
        mode = "pointwise"
    elif mode in {"pairwise", "pair", "compare", "双图"}:
        mode = "pairwise"
    else:
        raise ValueError(f"type 必须是 pointwise / pairwise，收到 {mode!r}")

    tid = str(raw.get("id") or "").strip()
    if not tid:
        raise ValueError("缺少 id")
    prompt = str(raw.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("缺少 prompt")

    task: dict[str, Any] = {
        "mode": mode,
        "id": tid,
        "prompt": prompt,
        "axis": str(raw.get("axis") or "").strip(),
        "lang": str(raw.get("lang") or "").strip(),
        "region": str(raw.get("region") or "").strip(),
        "meta": raw.get("meta") if isinstance(raw.get("meta"), dict) else {},
    }
    attrs = raw.get("attrs")
    if isinstance(attrs, list):
        task["attrs"] = [str(a) for a in attrs if str(a).strip()]

    if mode == "pointwise":
        image = str(raw.get("image") or "").strip()
        if not image:
            raise ValueError("单图任务缺少 image")
        task["image"] = image
        items_raw = raw.get("items") or []
        if not isinstance(items_raw, list) or not items_raw:
            raise ValueError("单图任务至少需要 1 个 items")
        items = []
        seen = set()
        for i, it in enumerate(items_raw, 1):
            if not isinstance(it, dict):
                raise ValueError(f"items[{i}] 必须是对象")
            did = str(it.get("dim") or it.get("id") or f"d{i}").strip()
            if did in seen:
                raise ValueError(f"items 的 id 重复：{did}")
            seen.add(did)
            score = _as_int(it.get("score"), f"items[{i}].score")
            if score not in (0, 1):
                raise ValueError(f"items[{i}].score 必须是 0/1")
            items.append(
                {
                    "dim": did,
                    "label": str(it.get("label") or "").strip(),
                    "question": str(it.get("question") or "").strip(),
                    "score": score,
                    "rationale": str(it.get("rationale") or "").strip(),
                }
            )
        task["items"] = items
        return task

    images = raw.get("images") or {}
    if not isinstance(images, dict):
        raise ValueError("pairwise 任务的 images 必须是 {A, B}")
    img_a = str(images.get("A") or images.get("a") or raw.get("image_a") or "").strip()
    img_b = str(images.get("B") or images.get("b") or raw.get("image_b") or "").strip()
    if not img_a or not img_b:
        raise ValueError("pairwise 任务需要 images.A 和 images.B")
    task["images"] = {"A": img_a, "B": img_b}

    scores_raw = raw.get("scores") or {}
    if not isinstance(scores_raw, dict):
        raise ValueError("pairwise 任务的 scores 必须是 {A: {...}, B: {...}}")
    scores_a = scores_raw.get("A") or scores_raw.get("a") or {}
    scores_b = scores_raw.get("B") or scores_raw.get("b") or {}
    if not isinstance(scores_a, dict) or not isinstance(scores_b, dict):
        raise ValueError("scores.A / scores.B 必须是对象")

    criteria_raw = raw.get("criteria") or []
    if criteria_raw:
        if not isinstance(criteria_raw, list):
            raise ValueError("criteria 必须是数组")
        criteria = []
        seen = set()
        for i, c in enumerate(criteria_raw, 1):
            if not isinstance(c, dict):
                raise ValueError(f"criteria[{i}] 必须是对象")
            cid = str(c.get("id") or c.get("dim") or f"q{i}").strip()
            if cid in seen:
                raise ValueError(f"criteria 的 id 重复：{cid}")
            seen.add(cid)
            criteria.append(
                {
                    "id": cid,
                    "label": str(c.get("label") or "").strip(),
                    "question": str(c.get("question") or "").strip(),
                }
            )
    else:
        criteria = [{"id": str(k), "label": "", "question": ""} for k in scores_a.keys()]
        if not criteria:
            raise ValueError("pairwise 任务没有 criteria，也没有 scores.A 的键")

    scores = {"A": {}, "B": {}}
    for c in criteria:
        cid = c["id"]
        for side, source in (("A", scores_a), ("B", scores_b)):
            if cid not in source:
                raise ValueError(f"scores.{side} 缺少维度 {cid}")
            value = _as_int(source[cid], f"scores.{side}.{cid}")
            if not 0 <= value <= 10:
                raise ValueError(f"scores.{side}.{cid} 需要在 0–10")
            scores[side][cid] = value
    task["criteria"] = criteria
    task["scores"] = scores
    note = raw.get("note") or raw.get("rationale")
    if note:
        task["note"] = str(note).strip()
    return task


def normalize_tasks(rows: list[dict]) -> tuple[list[dict], list[str]]:
    if not rows:
        return [], ["评分集是空的"]
    tasks: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    for i, raw in enumerate(rows, 1):
        try:
            task = normalize_task(raw, i)
        except ValueError as exc:
            errors.append(f"第 {i} 条：{exc}")
            continue
        if task["id"] in seen:
            errors.append(f"第 {i} 条：id 重复 {task['id']}")
            continue
        seen.add(task["id"])
        tasks.append(task)
    return tasks, errors


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------
def load_config(path: Path | None) -> dict:
    if not path:
        return {}
    if not path.is_file():
        raise ImportProblem(f"找不到配置文件：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ImportProblem(f"config.json 不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise ImportProblem("config.json 必须是对象")
    if isinstance(data.get("config"), dict):
        data = {**data["config"], "title": data.get("title") or data["config"].get("title")}
    return data


def derive_config(tasks: list[dict], explicit: dict | None = None, title: str = "") -> dict:
    explicit = explicit or {}
    dimensions: "OrderedDict[str, dict]" = OrderedDict()
    criteria: "OrderedDict[str, dict]" = OrderedDict()

    for item in explicit.get("dimensions") or []:
        if isinstance(item, dict) and item.get("id"):
            dimensions[str(item["id"])] = {
                "id": str(item["id"]),
                "label": str(item.get("label") or ""),
                "question": str(item.get("question") or ""),
            }
    for item in explicit.get("criteria") or []:
        if isinstance(item, dict) and item.get("id"):
            criteria[str(item["id"])] = {
                "id": str(item["id"]),
                "label": str(item.get("label") or ""),
                "question": str(item.get("question") or ""),
            }

    for task in tasks:
        if task["mode"] == "pointwise":
            for item in task["items"]:
                entry = dimensions.setdefault(
                    item["dim"], {"id": item["dim"], "label": "", "question": ""}
                )
                entry["label"] = entry["label"] or item.get("label", "")
                entry["question"] = entry["question"] or item.get("question", "")
        else:
            for item in task["criteria"]:
                entry = criteria.setdefault(
                    item["id"], {"id": item["id"], "label": "", "question": ""}
                )
                entry["label"] = entry["label"] or item.get("label", "")
                entry["question"] = entry["question"] or item.get("question", "")

    defaults = {d["id"]: d for d in DEFAULT_DIMENSIONS}
    defaults.update({c["id"]: c for c in DEFAULT_CRITERIA})
    for entry in list(dimensions.values()) + list(criteria.values()):
        fallback = defaults.get(entry["id"])
        if fallback:
            entry["label"] = entry["label"] or fallback["label"]
            entry["question"] = entry["question"] or fallback["question"]
        entry["label"] = entry["label"] or entry["id"]

    return {
        "title": str(explicit.get("title") or title or ""),
        "dimensions": list(dimensions.values()),
        "criteria": list(criteria.values()),
    }


# --------------------------------------------------------------------------
# image staging
# --------------------------------------------------------------------------
def _resolve_image(ref: str, base_dir: Path, images_dir: Path | None) -> Path | None:
    path = Path(ref)
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.append(base_dir / path)
        if images_dir:
            candidates.append(Path(images_dir) / path)
            candidates.append(Path(images_dir) / path.name)
        candidates.append(base_dir / path.name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _stage(storage: Storage, name: str, tasks: list[dict], base_dir: Path,
           images_dir: Path | None, config: dict, title: str, source: str,
           overwrite: bool) -> dict:
    staging = storage.staging_dir()
    image_out = staging / "images"
    image_out.mkdir(parents=True, exist_ok=True)
    copied: dict[Path, str] = {}
    used_names: set[str] = set()
    errors: list[str] = []

    def stage_image(ref: str, where: str) -> str:
        src = _resolve_image(ref, base_dir, images_dir)
        if not src:
            errors.append(f"{where}：找不到图片 {ref}")
            return ref
        key = src.resolve()
        if key in copied:
            return copied[key]
        dest_name = src.name
        if dest_name in used_names:
            stem, suffix = src.stem, src.suffix
            n = 2
            while f"{stem}-{n}{suffix}" in used_names:
                n += 1
            dest_name = f"{stem}-{n}{suffix}"
        used_names.add(dest_name)
        shutil.copy2(src, image_out / dest_name)
        rel = f"images/{dest_name}"
        copied[key] = rel
        return rel

    for task in tasks:
        if task["mode"] == "pointwise":
            task["image"] = stage_image(task["image"], f"{task['id']}.image")
        else:
            task["images"]["A"] = stage_image(task["images"]["A"], f"{task['id']}.images.A")
            task["images"]["B"] = stage_image(task["images"]["B"], f"{task['id']}.images.B")

    if errors:
        shutil.rmtree(staging, ignore_errors=True)
        raise ImportProblem(errors)

    with (staging / "tasks.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for task in tasks:
            handle.write(json.dumps(task, ensure_ascii=False) + "\n")

    meta = {
        "name": name,
        "title": title or config.get("title") or name,
        "created_at": utc_now(),
        "source": source,
        "task_count": len(tasks),
        "pointwise": sum(1 for t in tasks if t["mode"] == "pointwise"),
        "pairwise": sum(1 for t in tasks if t["mode"] == "pairwise"),
        "config": config,
    }
    (staging / "dataset.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    storage.commit_dataset(name, staging, overwrite=overwrite)
    return meta


# --------------------------------------------------------------------------
# public entry points
# --------------------------------------------------------------------------
def import_dataset(storage: Storage, name: str, tasks_path: str | Path,
                   images_dir: str | Path | None = None,
                   config_path: str | Path | None = None,
                   title: str = "", overwrite: bool = False) -> dict:
    if not valid_name(name):
        raise ImportProblem(f"非法数据集名称：{name!r}（只允许字母、数字、-、_）")
    if storage.exists(name) and not overwrite:
        raise ImportProblem(f"数据集已存在：{name}（加 --overwrite 覆盖）")
    tasks_path = Path(tasks_path)
    if tasks_path.is_dir():
        found = find_tasks_file(tasks_path)
        if not found:
            raise ImportProblem(f"目录里找不到 tasks.jsonl / tasks.json / tasks.csv：{tasks_path}")
        tasks_path = found
    if not tasks_path.is_file():
        raise ImportProblem(f"找不到评分集：{tasks_path}")
    rows = read_task_rows(tasks_path)
    tasks, errors = normalize_tasks(rows)
    if errors:
        raise ImportProblem(errors)
    explicit = load_config(Path(config_path) if config_path else None)
    config = derive_config(tasks, explicit, title)
    base_dir = tasks_path.parent
    img_dir = Path(images_dir) if images_dir else None
    return _stage(storage, name, tasks, base_dir, img_dir, config, title,
                  source=str(tasks_path.name), overwrite=overwrite)


def find_tasks_file(root: Path) -> Path | None:
    candidates = [p for p in root.rglob("*") if p.is_file() and p.name.lower() in TASK_NAMES]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (len(p.parts), str(p)))
    return candidates[0]


def import_zip_bytes(storage: Storage, name: str, data: bytes, title: str = "",
                     overwrite: bool = False) -> dict:
    if not valid_name(name):
        raise ImportProblem(f"非法数据集名称：{name!r}（只允许字母、数字、-、_）")
    if len(data) > MAX_ZIP_BYTES:
        raise ImportProblem("zip 超过 1 GB")
    if storage.exists(name) and not overwrite:
        raise ImportProblem(f"数据集已存在：{name}（加 --overwrite 覆盖）")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ImportProblem("不是有效的 zip 文件") from exc

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp).resolve()
        for info in archive.infolist():
            if info.is_dir() or info.filename.startswith("__MACOSX/"):
                continue
            target = (tmp_root / info.filename).resolve()
            if tmp_root not in target.parents:
                raise ImportProblem(f"zip 内含非法路径：{info.filename}")
            archive.extract(info, tmp_root)
        tasks_file = find_tasks_file(tmp_root)
        if not tasks_file:
            raise ImportProblem("zip 里找不到 tasks.jsonl / tasks.json / tasks.csv")
        config_file = tasks_file.parent / "config.json"
        return import_dataset(
            storage,
            name,
            tasks_file,
            images_dir=tasks_file.parent,
            config_path=config_file if config_file.is_file() else None,
            title=title,
            overwrite=overwrite,
        )


def import_zip_file(storage: Storage, name: str, path: str | Path, title: str = "",
                    overwrite: bool = False) -> dict:
    path = Path(path)
    if not path.is_file():
        raise ImportProblem(f"找不到 zip：{path}")
    return import_zip_bytes(storage, name, path.read_bytes(), title=title, overwrite=overwrite)
