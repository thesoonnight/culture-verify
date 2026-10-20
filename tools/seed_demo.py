#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""给本地演示数据集灌入两条示例标注，方便看结果页。

    python tools/seed_demo.py --base http://127.0.0.1:8766 --dataset demo
"""
from __future__ import annotations

import argparse
import json
import urllib.request


def verdict(agree: bool, correction: str | None = None) -> dict:
    out = {"agree": agree}
    if correction:
        out["correction"] = correction
    return out


ANNOTATIONS = [
    {
        "task_id": "A01",
        "mode": "pointwise",
        "annotator": "lin",
        "status": "done",
        "verdicts": {"d1": verdict(True), "d2": verdict(True), "d3": verdict(True)},
        "duration_ms": 5200,
        "note": "",
    },
    {
        "task_id": "A02",
        "mode": "pointwise",
        "annotator": "lin",
        "status": "done",
        "verdicts": {"d1": verdict(False, "1"), "d2": verdict(True), "d3": verdict(True)},
        "duration_ms": 6100,
        "note": "塔顶结构其实说得过去，评审偏严。",
    },
    {
        "task_id": "A03",
        "mode": "pointwise",
        "annotator": "lin",
        "status": "done",
        "verdicts": {"d1": verdict(True), "d2": verdict(False, "1"), "d3": verdict(False, "1")},
        "duration_ms": 7000,
        "note": "",
    },
    {
        "task_id": "B01",
        "mode": "pairwise",
        "annotator": "lin",
        "status": "done",
        "verdicts": {"q1": verdict(True), "q2": verdict(False, "gap")},
        "overall": "A",
        "duration_ms": 9000,
        "shown_as": "BA",
        "note": "",
    },
    {
        "task_id": "A01",
        "mode": "pointwise",
        "annotator": "wang",
        "status": "done",
        "verdicts": {"d1": verdict(True), "d2": verdict(False, "1"), "d3": verdict(True)},
        "duration_ms": 4800,
        "note": "",
    },
    {
        "task_id": "A02",
        "mode": "pointwise",
        "annotator": "wang",
        "status": "done",
        "verdicts": {"d1": verdict(False, "1"), "d2": verdict(True), "d3": verdict(True)},
        "duration_ms": 5600,
        "note": "",
    },
    {
        "task_id": "B01",
        "mode": "pairwise",
        "annotator": "wang",
        "status": "done",
        "verdicts": {"q1": verdict(True), "q2": verdict(True)},
        "overall": "A",
        "duration_ms": 8000,
        "shown_as": "AB",
        "note": "",
    },
    {
        "task_id": "B02",
        "mode": "pairwise",
        "annotator": "wang",
        "status": "done",
        "verdicts": {"q1": verdict(True), "q2": verdict(True)},
        "overall": "B",
        "duration_ms": 7400,
        "shown_as": "BA",
        "note": "",
    },
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8766")
    parser.add_argument("--dataset", default="demo")
    args = parser.parse_args()
    for annotation in ANNOTATIONS:
        body = json.dumps({"annotation": annotation}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{args.base}/api/datasets/{args.dataset}/annotations",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
        print(f"seeded {annotation['annotator']} / {annotation['task_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
