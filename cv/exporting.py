"""把标注/一致性结果导出成 CSV、JSONL、JSON。"""
from __future__ import annotations

import csv
import io
import json

from .analysis import _model_pref, _pair_truth, _point_truth

VERDICT_COLUMNS = [
    "task_id",
    "mode",
    "annotator",
    "axis",
    "lang",
    "model",
    "item_id",
    "item_label",
    "model_score_a",
    "model_score_b",
    "model_pref",
    "human_agree",
    "human_correction",
    "human_truth",
    "overall",
    "note",
    "duration_ms",
    "finished_at",
    "status",
    "started_at",
    "model_a",
    "model_b",
    "human_verdict",
    # 追加列（放在最后，老脚本按列名取不会受影响）
    "prompt",
    "shown_as",
    "region",
]

CONSISTENCY_COLUMNS = [
    "section",
    "key",
    "label",
    "n",
    "agree",
    "disagree",
    "agreement_rate",
    "corrected",
    "truth_n",
    "evaluator_accuracy",
    "raw_pass_rate",
    "verified_pass_rate",
    "flipped",
    "kappa",
    "kappa_n",
    "n_pairs",
    "n_items",
    "avg_duration_ms",
]


def _labels(tasks: list[dict], config: dict | None) -> dict[str, str]:
    labels = {}
    for entry in (config or {}).get("dimensions", []) + (config or {}).get("criteria", []):
        if entry.get("id"):
            labels[str(entry["id"])] = entry.get("label") or str(entry["id"])
    for task in tasks:
        for item in task.get("items", []) + task.get("criteria", []):
            key = item.get("dim") or item.get("id")
            if key and item.get("label"):
                labels.setdefault(str(key), item["label"])
    return labels


def _blank(value):
    """保留 0 / False 这类"有值但假"的取值：`value or ""` 会把修正值 0 吃掉。"""
    return "" if value is None or value == "" else value


def verdict_rows(tasks: list[dict], annotations: list[dict], config: dict | None = None) -> list[dict]:
    labels = _labels(tasks, config)
    task_by_id = {t["id"]: t for t in tasks}
    rows: list[dict] = []
    for ann in annotations:
        if not isinstance(ann, dict):
            continue
        task = task_by_id.get(ann.get("task_id"))
        if not task:
            continue
        verdicts = ann.get("verdicts")
        if not isinstance(verdicts, dict):
            verdicts = {}
        meta = task.get("meta") or {}
        status = ann.get("status") or ""
        finished = ann.get("finished_at") or (
            ann.get("updated_at") if status in ("done", "flagged") else ""
        )
        base = {
            "task_id": task["id"],
            "mode": task.get("mode"),
            "annotator": ann.get("annotator"),
            "axis": task.get("axis", ""),
            "lang": task.get("lang", ""),
            "overall": _blank(ann.get("overall")),
            "note": _blank(ann.get("note")),
            "duration_ms": _blank(ann.get("duration_ms")),
            "finished_at": finished or "",
            "status": status,
            "started_at": _blank(ann.get("started_at")),
            "prompt": task.get("prompt", ""),
            "shown_as": _blank(ann.get("shown_as")),
            "region": task.get("region", ""),
        }
        if task.get("mode") == "pointwise":
            for item in task.get("items", []):
                verdict = verdicts.get(item["dim"])
                if not isinstance(verdict, dict):
                    continue
                truth = _point_truth(item, verdict)
                rows.append(
                    {
                        **base,
                        "model": meta.get("model", ""),
                        "model_a": meta.get("model", ""),
                        "model_b": "",
                        "item_id": item["dim"],
                        "item_label": labels.get(item["dim"], item["dim"]),
                        "model_score_a": item["score"],
                        "model_score_b": "",
                        "model_pref": "",
                        "human_agree": 1 if verdict.get("agree") else 0,
                        "human_correction": _blank(verdict.get("correction")),
                        "human_truth": "" if truth is None else truth,
                        "human_verdict": "同意" if verdict.get("agree") else "不同意",
                    }
                )
        else:
            model_a = meta.get("model_A", "")
            model_b = meta.get("model_B", "")
            for crit in task.get("criteria", []):
                verdict = verdicts.get(crit["id"])
                if not isinstance(verdict, dict):
                    continue
                pref = _model_pref(task, crit["id"])
                truth = _pair_truth(pref, verdict)
                rows.append(
                    {
                        **base,
                        "model": f"{model_a} vs {model_b}" if model_a and model_b else "",
                        "model_a": model_a,
                        "model_b": model_b,
                        "item_id": crit["id"],
                        "item_label": labels.get(crit["id"], crit["id"]),
                        "model_score_a": task["scores"]["A"][crit["id"]],
                        "model_score_b": task["scores"]["B"][crit["id"]],
                        "model_pref": pref,
                        "human_agree": 1 if verdict.get("agree") else 0,
                        "human_correction": _blank(verdict.get("correction")),
                        "human_truth": truth or "",
                        "human_verdict": "同意" if verdict.get("agree") else "不同意",
                    }
                )
    return rows


def annotations_jsonl(annotations: list[dict]) -> bytes:
    lines = [json.dumps(ann, ensure_ascii=False) for ann in annotations]
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def consistency_rows(summary: dict) -> list[dict]:
    rows: list[dict] = []
    base_keys = [
        "n",
        "agree",
        "disagree",
        "agreement_rate",
        "corrected",
        "truth_n",
        "evaluator_accuracy",
        "raw_pass_rate",
        "verified_pass_rate",
        "flipped",
    ]

    def add(section: str, key: str, label: str, item: dict, extra: dict | None = None) -> None:
        row = {"section": section, "key": key, "label": label}
        for k in base_keys:
            row[k] = item.get(k)
        if extra:
            row.update(extra)
        rows.append(row)

    overall = summary.get("overall") or {}
    inter = summary.get("inter_annotator") or {}
    add(
        "overall",
        "all",
        "全部判定",
        overall,
        {"kappa": inter.get("kappa"), "kappa_n": inter.get("n_kappa_comparisons")},
    )
    for item in summary.get("dimensions", []):
        add("evaluator_vs_human", item.get("id", ""), item.get("label", ""), item)
    for item in summary.get("criteria", []):
        add("evaluator_vs_human", item.get("id", ""), item.get("label", ""), item)
    rows.append(
        {
            "section": "inter_annotator",
            "key": "all",
            "label": "多标注员一致性",
            "n": inter.get("n_comparisons"),
            "agreement_rate": inter.get("percent_agreement"),
            "kappa": inter.get("kappa"),
            "kappa_n": inter.get("n_kappa_comparisons"),
            "n_pairs": inter.get("n_pairs"),
            "n_items": inter.get("n_items"),
        }
    )
    for item in summary.get("by_model", []):
        add("by_model", item.get("model", ""), item.get("model", ""), item)
    for item in summary.get("by_axis", []):
        add("by_axis", item.get("axis", ""), item.get("axis", ""), item)
    for item in summary.get("by_annotator", []):
        rows.append(
            {
                "section": "by_annotator",
                "key": item.get("annotator", ""),
                "label": item.get("annotator", ""),
                "n": item.get("n"),
                "agree": item.get("agree"),
                "agreement_rate": item.get("agreement_rate"),
                "corrected": item.get("corrected"),
                "avg_duration_ms": item.get("avg_duration_ms"),
            }
        )
    return rows


def to_csv(rows: list[dict], columns: list[str] | None = None) -> bytes:
    if columns is None:
        columns = list(rows[0].keys()) if rows else []
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")  # BOM：Excel 直接打开不乱码


def summary_json(summary: dict) -> bytes:
    return json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8")
