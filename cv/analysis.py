"""一致性 / 评分统计。

输入是已经规范化的任务列表和标注列表，输出一份可以直接 JSON 化的报告：

  * evaluator vs human：每个维度/评分维度的同意率、修正率、修正后通过率
  * inter-annotator：多标注员的成对一致率与 Cohen's κ
  * by_model / by_axis / by_annotator：分组切片
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
from itertools import combinations
from typing import Any, Iterable

from .validation import COUNTED_CORRECTIONS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty_stats() -> dict[str, Any]:
    return {
        "n": 0,
        "agree": 0,
        "disagree": 0,
        "corrected": 0,
        "truth_n": 0,
        "raw_sum": 0.0,
        "truth_sum": 0.0,
        "correct_sum": 0,
        "flipped": 0,
        "duration_sum": 0,
        "duration_n": 0,
    }


def _finalize(stats: dict[str, Any], label: str = "", scope: str = "") -> dict[str, Any]:
    n = stats["n"]
    truth_n = stats["truth_n"]
    out = {
        "label": label,
        "scope": scope,
        "n": n,
        "agree": stats["agree"],
        "disagree": stats["disagree"],
        "agreement_rate": (stats["agree"] / n) if n else None,
        "corrected": stats["corrected"],
        "truth_n": truth_n,
        "evaluator_accuracy": (stats["correct_sum"] / truth_n) if truth_n else None,
    }
    if scope == "pointwise":
        out["raw_pass_rate"] = (stats["raw_sum"] / n) if n else None
        out["verified_pass_rate"] = (stats["truth_sum"] / truth_n) if truth_n else None
    if scope == "pairwise":
        out["flipped"] = stats["flipped"]
    if stats["duration_n"]:
        out["avg_duration_ms"] = round(stats["duration_sum"] / stats["duration_n"])
    return out


def _item_ids(task: dict) -> list[str]:
    if task.get("mode") == "pointwise":
        return [item["dim"] for item in task.get("items", [])]
    return [crit["id"] for crit in task.get("criteria", [])]


def _model_pref(task: dict, cid: str) -> str:
    a = task["scores"]["A"][cid]
    b = task["scores"]["B"][cid]
    if a == b:
        return "tie"
    return "A" if a > b else "B"


def _point_truth(item: dict, verdict: dict) -> int | None:
    if not isinstance(verdict, dict):
        return None
    correction = verdict.get("correction")
    if correction in ("0", "1", 0, 1):
        return int(correction)
    if verdict.get("agree") is True:
        return int(item["score"])
    return None


def _pair_truth(pref: str, verdict: dict) -> str | None:
    if not isinstance(verdict, dict):
        return None
    correction = verdict.get("correction")
    if verdict.get("agree") is True:
        return pref
    if correction in ("A", "B", "tie"):
        return correction
    if correction == "gap":
        return pref  # 方向认可，只是分差不同意
    return None


def _kappa(pairs: list[tuple[int, int]]) -> tuple[float | None, float | None]:
    """返回 (percent agreement, Cohen's kappa)。"""
    if not pairs:
        return None, None
    n = len(pairs)
    matches = sum(1 for a, b in pairs if a == b)
    po = matches / n
    p1 = sum(a for a, _ in pairs) / n
    q1 = sum(b for _, b in pairs) / n
    pe = p1 * q1 + (1 - p1) * (1 - q1)
    if pe >= 1:
        return po, None
    return po, (po - pe) / (1 - pe)


def analyze(tasks: list[dict], annotations: list[dict], config: dict | None = None) -> dict:
    config = config or {}
    labels: dict[str, str] = {}
    for entry in config.get("dimensions", []) + config.get("criteria", []):
        if entry.get("id"):
            labels[str(entry["id"])] = entry.get("label") or str(entry["id"])
    for task in tasks:
        for item in task.get("items", []) + task.get("criteria", []):
            key = item.get("dim") or item.get("id")
            if key and item.get("label"):
                labels.setdefault(str(key), item["label"])

    task_by_id = {t["id"]: t for t in tasks}
    dim_stats: "OrderedDict[str, dict]" = OrderedDict()
    crit_stats: "OrderedDict[str, dict]" = OrderedDict()
    by_annotator: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    by_axis: dict[str, dict] = {}
    overall = _empty_stats()
    inter_labels: dict[tuple[str, str], dict[str, int]] = {}

    for ann in annotations:
        if not isinstance(ann, dict):
            continue  # 手工改过库 / 外部工具写坏的行，不能让整份报告 500
        task = task_by_id.get(ann.get("task_id"))
        if not task:
            continue
        annotator = ann.get("annotator") or "unknown"
        verdicts = ann.get("verdicts")
        if not isinstance(verdicts, dict):
            verdicts = {}
        duration = ann.get("duration_ms")
        annot_stats = by_annotator.setdefault(annotator, _empty_stats())
        if isinstance(duration, (int, float)) and duration >= 0:
            annot_stats["duration_sum"] += duration
            annot_stats["duration_n"] += 1
            overall["duration_sum"] += duration
            overall["duration_n"] += 1
        axis = task.get("axis") or "未标注"
        axis_stats = by_axis.setdefault(axis, _empty_stats())

        if task.get("mode") == "pointwise":
            model = str((task.get("meta") or {}).get("model") or "unknown")
            model_stats = by_model.setdefault(model, _empty_stats())
            for item in task.get("items", []):
                did = item["dim"]
                verdict = verdicts.get(did)
                if not isinstance(verdict, dict) or not isinstance(verdict.get("agree"), bool):
                    continue
                stats = dim_stats.setdefault(did, _empty_stats())
                for bucket in (stats, overall, annot_stats, axis_stats, model_stats):
                    bucket["n"] += 1
                if verdict["agree"]:
                    for bucket in (stats, overall, annot_stats, axis_stats, model_stats):
                        bucket["agree"] += 1
                else:
                    stats["disagree"] += 1
                    axis_stats["disagree"] += 1
                    model_stats["disagree"] += 1
                    overall["disagree"] += 1
                    if verdict.get("correction") in COUNTED_CORRECTIONS:
                        for bucket in (stats, annot_stats, overall, axis_stats, model_stats):
                            bucket["corrected"] += 1
                stats["raw_sum"] += item["score"]
                model_stats["raw_sum"] += item["score"]
                axis_stats["raw_sum"] += item["score"]
                truth = _point_truth(item, verdict)
                if truth is not None:
                    for bucket in (stats, overall, annot_stats, axis_stats, model_stats):
                        bucket["truth_n"] += 1
                        bucket["truth_sum"] += truth
                        if int(item["score"]) == truth:
                            bucket["correct_sum"] += 1
                inter_labels.setdefault((task["id"], did), {})[annotator] = 1 if verdict["agree"] else 0
        else:
            for crit in task.get("criteria", []):
                cid = crit["id"]
                verdict = verdicts.get(cid)
                if not isinstance(verdict, dict) or not isinstance(verdict.get("agree"), bool):
                    continue
                pref = _model_pref(task, cid)
                stats = crit_stats.setdefault(cid, _empty_stats())
                for bucket in (stats, overall, annot_stats, axis_stats):
                    bucket["n"] += 1
                if verdict["agree"]:
                    for bucket in (stats, overall, annot_stats, axis_stats):
                        bucket["agree"] += 1
                else:
                    stats["disagree"] += 1
                    axis_stats["disagree"] += 1
                    overall["disagree"] += 1
                    correction = verdict.get("correction")
                    if correction in COUNTED_CORRECTIONS:
                        for bucket in (stats, overall, annot_stats, axis_stats):
                            bucket["corrected"] += 1
                    if correction in ("A", "B") and correction != pref:
                        stats["flipped"] += 1
                truth = _pair_truth(pref, verdict)
                if truth is not None:
                    for bucket in (stats, overall, annot_stats, axis_stats):
                        bucket["truth_n"] += 1
                        if truth == pref:
                            bucket["correct_sum"] += 1
                inter_labels.setdefault((task["id"], cid), {})[annotator] = 1 if verdict["agree"] else 0

    dimensions = [
        {"id": did, **_finalize(stats, labels.get(did, did), "pointwise")}
        for did, stats in dim_stats.items()
    ]
    criteria = [
        {"id": cid, **_finalize(stats, labels.get(cid, cid), "pairwise")}
        for cid, stats in crit_stats.items()
    ]

    # 多标注员一致性：对每个 (task, item) 取两位标注员的 ✓/✗，成对算 percent agreement 与 κ
    pair_kappas: list[tuple[int, float]] = []
    pair_agreements: list[tuple[int, float]] = []
    annotators = sorted({a for values in inter_labels.values() for a in values})
    for left, right in combinations(annotators, 2):
        common = [
            (values[left], values[right])
            for values in inter_labels.values()
            if left in values and right in values
        ]
        if len(common) < 2:
            continue
        po, kappa = _kappa(common)
        pair_agreements.append((len(common), po or 0.0))
        if kappa is not None:
            pair_kappas.append((len(common), kappa))
    total_common = sum(n for n, _ in pair_agreements)
    kappa_items = sum(n for n, _ in pair_kappas)
    inter = {
        "annotators": annotators,
        "n_items": len(inter_labels),
        "n_comparisons": total_common,
        "percent_agreement": (
            sum(n * po for n, po in pair_agreements) / total_common if total_common else None
        ),
        # 某一对标注员全都判「同意」时 pe=1，κ 无定义；这类配对只进一致率不进 κ，
        # 所以单独报出 κ 实际用到的比较数，免得两个数看起来对不上
        "n_kappa_comparisons": kappa_items,
        "kappa": (
            sum(n * k for n, k in pair_kappas) / kappa_items if pair_kappas else None
        ),
        "n_pairs": len(pair_agreements),
    }

    overall_out = _finalize(overall, "全部维度", "overall")
    by_annotator_out = [
        {
            "annotator": annotator,
            "n": stats["n"],
            "agree": stats["agree"],
            "agreement_rate": (stats["agree"] / stats["n"]) if stats["n"] else None,
            "corrected": stats["corrected"],
            "avg_duration_ms": (
                round(stats["duration_sum"] / stats["duration_n"]) if stats["duration_n"] else None
            ),
        }
        for annotator, stats in sorted(by_annotator.items())
    ]
    by_model_out = [
        {
            "model": model,
            **_finalize(stats, model, "pointwise"),
        }
        for model, stats in sorted(by_model.items())
    ]
    by_axis_out = [
        {"axis": axis, **_finalize(stats, axis, "overall")}
        for axis, stats in sorted(by_axis.items())
    ]

    return {
        "generated_at": _now(),
        "task_counts": {
            "total": len(tasks),
            "pointwise": sum(1 for t in tasks if t.get("mode") == "pointwise"),
            "pairwise": sum(1 for t in tasks if t.get("mode") == "pairwise"),
        },
        "annotation_count": len(annotations),
        "annotated_tasks": len(
            {ann.get("task_id") for ann in annotations if ann.get("task_id") in task_by_id}
        ),
        "annotators": annotators,
        "overall": overall_out,
        "dimensions": dimensions,
        "criteria": criteria,
        "inter_annotator": inter,
        "by_annotator": by_annotator_out,
        "by_model": by_model_out,
        "by_axis": by_axis_out,
    }
