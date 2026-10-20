"""数据集与标注的本地存储。

目录结构::

    data/
      cv.sqlite3                 # 标注
      datasets/
        <name>/
          dataset.json           # 元信息 + 维度配置
          tasks.jsonl            # 题目
          images/...             # 图片
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
MEDIA_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def valid_name(name: str) -> bool:
    return bool(name and NAME_RE.match(name))


class Storage:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.datasets_dir = self.root / "datasets"
        self.tmp_dir = self.root / "tmp"
        self.datasets_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "cv.sqlite3"
        self._task_cache: dict[str, tuple[float, list[dict]]] = {}
        self._init_db()

    # ---------------------------------------------------------------- sqlite
    @contextmanager
    def _db(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._db() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS annotations (
                    dataset   TEXT NOT NULL,
                    task_id   TEXT NOT NULL,
                    annotator TEXT NOT NULL,
                    payload   TEXT NOT NULL,
                    status    TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (dataset, task_id, annotator)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_annotations_dataset ON annotations(dataset)"
            )

    # --------------------------------------------------------------- dataset
    def dataset_dir(self, name: str) -> Path:
        if not valid_name(name):
            raise ValueError(f"非法数据集名称：{name!r}（只允许字母、数字、-、_）")
        return self.datasets_dir / name

    def exists(self, name: str) -> bool:
        return (self.dataset_dir(name) / "dataset.json").is_file()

    def meta(self, name: str) -> dict:
        path = self.dataset_dir(name) / "dataset.json"
        if not path.is_file():
            raise KeyError(f"数据集不存在：{name}")
        return json.loads(path.read_text(encoding="utf-8"))

    def tasks(self, name: str) -> list[dict]:
        path = self.dataset_dir(name) / "tasks.jsonl"
        if not path.is_file():
            raise KeyError(f"数据集缺少 tasks.jsonl：{name}")
        mtime = path.stat().st_mtime
        cached = self._task_cache.get(name)
        if cached and cached[0] == mtime:
            return cached[1]
        tasks = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tasks.append(json.loads(line))
        self._task_cache[name] = (mtime, tasks)
        return tasks

    def task_ids(self, name: str) -> set[str]:
        return {t["id"] for t in self.tasks(name)}

    def list_datasets(self) -> list[dict]:
        out: list[dict] = []
        for child in sorted(self.datasets_dir.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            meta_file = child / "dataset.json"
            if not meta_file.is_file():
                continue
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            meta["annotators"] = self.annotators(child.name)
            meta["annotation_count"] = self.annotation_count(child.name)
            out.append(meta)
        return out

    def annotation_count(self, name: str) -> int:
        with self._db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM annotations WHERE dataset = ?", (name,)
            ).fetchone()
            return int(row["n"])

    def annotators(self, name: str) -> list[str]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT DISTINCT annotator FROM annotations WHERE dataset = ? ORDER BY annotator",
                (name,),
            ).fetchall()
            return [r["annotator"] for r in rows]

    # ----------------------------------------------------------- annotations
    def save_annotation(self, name: str, payload: dict) -> dict:
        if not self.exists(name):
            raise KeyError(f"数据集不存在：{name}")
        annotator = str(payload.get("annotator") or "").strip()
        task_id = str(payload.get("task_id") or "").strip()
        if not annotator:
            raise ValueError("annotation.annotator 不能为空")
        if not task_id:
            raise ValueError("annotation.task_id 不能为空")
        if task_id not in self.task_ids(name):
            raise ValueError(f"题目不存在：{task_id}")
        payload = {**payload, "annotator": annotator, "task_id": task_id}
        updated = payload.get("updated_at") or utc_now()
        payload["updated_at"] = updated
        with self._db() as conn:
            conn.execute(
                """
                INSERT INTO annotations (dataset, task_id, annotator, payload, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset, task_id, annotator) DO UPDATE SET
                    payload = excluded.payload,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    name,
                    task_id,
                    annotator,
                    json.dumps(payload, ensure_ascii=False),
                    payload.get("status"),
                    updated,
                ),
            )
        return payload

    def annotations(self, name: str, annotator: str | None = None) -> list[dict]:
        if not self.exists(name):
            raise KeyError(f"数据集不存在：{name}")
        sql = "SELECT payload FROM annotations WHERE dataset = ?"
        args: list[Any] = [name]
        if annotator:
            sql += " AND annotator = ?"
            args.append(annotator)
        sql += " ORDER BY updated_at"
        with self._db() as conn:
            rows = conn.execute(sql, args).fetchall()
        out = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except json.JSONDecodeError:
                continue
            payload.setdefault("dataset", name)
            out.append(payload)
        return out

    # ----------------------------------------------------------------- files
    def staging_dir(self) -> Path:
        return Path(tempfile.mkdtemp(prefix="import-", dir=self.tmp_dir))

    def commit_dataset(self, name: str, staging: Path, overwrite: bool = False) -> None:
        final = self.dataset_dir(name)
        if final.exists():
            if not overwrite:
                raise ValueError(f"数据集已存在：{name}（加 --overwrite 覆盖）")
            self.delete_dataset(name)
        os.replace(staging, final)
        self._task_cache.pop(name, None)

    def delete_dataset(self, name: str) -> None:
        final = self.dataset_dir(name)
        if final.exists():
            shutil.rmtree(final)
        with self._db() as conn:
            conn.execute("DELETE FROM annotations WHERE dataset = ?", (name,))
        self._task_cache.pop(name, None)

    def media_path(self, name: str, rel: str) -> Path:
        base = self.dataset_dir(name).resolve()
        target = (base / rel).resolve()
        if target != base and base not in target.parents:
            raise ValueError("非法图片路径")
        return target

    def update_config(self, name: str, labels: dict, questions: dict) -> dict:
        meta = self.meta(name)
        config = meta.get("config") or {}
        for entry in (config.get("dimensions") or []) + (config.get("criteria") or []):
            key = entry.get("id")
            if key in labels and str(labels[key]).strip():
                entry["label"] = str(labels[key]).strip()
            if key in questions:
                entry["question"] = str(questions[key]).strip()
        meta["config"] = config
        (self.dataset_dir(name) / "dataset.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return config

    def iter_images(self, name: str) -> Iterable[Path]:
        image_dir = self.dataset_dir(name) / "images"
        if not image_dir.is_dir():
            return []
        return (p for p in image_dir.rglob("*") if p.is_file())
