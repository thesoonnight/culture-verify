"""一致性统计测试。"""
from __future__ import annotations

import unittest

from cv.analysis import analyze
from cv.exporting import CONSISTENCY_COLUMNS, VERDICT_COLUMNS, consistency_rows, to_csv, verdict_rows


def sample():
    tasks = [
        {
            "mode": "pointwise",
            "id": "T1",
            "prompt": "p",
            "axis": "服饰",
            "items": [
                {"dim": "d1", "score": 1, "label": "准确性"},
                {"dim": "d2", "score": 0, "label": "错配"},
            ],
            "meta": {"model": "M1"},
        },
        {
            "mode": "pairwise",
            "id": "P1",
            "prompt": "p2",
            "axis": "建筑",
            "criteria": [{"id": "q1", "label": "质感"}],
            "scores": {"A": {"q1": 7}, "B": {"q1": 3}},
            "meta": {"model_A": "M1", "model_B": "M2"},
        },
    ]
    annotations = [
        {
            "task_id": "T1",
            "annotator": "a",
            "verdicts": {"d1": {"agree": True}, "d2": {"agree": False, "correction": "1"}},
            "duration_ms": 1000,
        },
        {
            "task_id": "P1",
            "annotator": "a",
            "verdicts": {"q1": {"agree": True}},
            "overall": "A",
            "duration_ms": 2000,
        },
        {
            "task_id": "T1",
            "annotator": "b",
            "verdicts": {"d1": {"agree": True}, "d2": {"agree": True}},
            "duration_ms": 3000,
        },
    ]
    config = {"dimensions": [{"id": "d1", "label": "准确性"}], "criteria": [{"id": "q1", "label": "质感"}]}
    return tasks, annotations, config


class AnalysisTests(unittest.TestCase):
    def test_agreement_and_verified_rates(self) -> None:
        tasks, annotations, config = sample()
        summary = analyze(tasks, annotations, config)
        dims = {item["id"]: item for item in summary["dimensions"]}
        self.assertEqual(dims["d1"]["n"], 2)
        self.assertEqual(dims["d1"]["agree"], 2)
        self.assertEqual(dims["d2"]["agree"], 1)
        self.assertEqual(dims["d2"]["corrected"], 1)
        self.assertAlmostEqual(dims["d2"]["raw_pass_rate"], 0.0)
        self.assertAlmostEqual(dims["d2"]["verified_pass_rate"], 0.5)
        self.assertAlmostEqual(dims["d2"]["evaluator_accuracy"], 0.5)
        self.assertEqual(summary["overall"]["n"], 5)
        self.assertEqual(summary["overall"]["agree"], 4)
        self.assertAlmostEqual(summary["overall"]["agreement_rate"], 0.8)

    def test_pairwise(self) -> None:
        tasks, annotations, config = sample()
        summary = analyze(tasks, annotations, config)
        crit = {item["id"]: item for item in summary["criteria"]}
        self.assertEqual(crit["q1"]["n"], 1)
        self.assertEqual(crit["q1"]["agree"], 1)
        self.assertEqual(crit["q1"]["flipped"], 0)

    def test_inter_annotator_kappa(self) -> None:
        tasks, annotations, config = sample()
        summary = analyze(tasks, annotations, config)
        inter = summary["inter_annotator"]
        self.assertEqual(inter["annotators"], ["a", "b"])
        self.assertEqual(inter["n_items"], 3)
        self.assertEqual(inter["n_comparisons"], 2)
        self.assertAlmostEqual(inter["percent_agreement"], 0.5)
        self.assertAlmostEqual(inter["kappa"], 0.0)

    def test_single_annotator_has_no_kappa(self) -> None:
        tasks, annotations, config = sample()
        summary = analyze(tasks, annotations[:2], config)
        self.assertIsNone(summary["inter_annotator"]["kappa"])

    def test_by_model(self) -> None:
        tasks, annotations, config = sample()
        summary = analyze(tasks, annotations, config)
        model = {row["model"]: row for row in summary["by_model"]}["M1"]
        self.assertEqual(model["n"], 4)
        self.assertAlmostEqual(model["raw_pass_rate"], 0.5)
        self.assertAlmostEqual(model["verified_pass_rate"], 0.75)

    def test_verdict_export(self) -> None:
        tasks, annotations, config = sample()
        rows = verdict_rows(tasks, annotations, config)
        self.assertEqual(len(rows), 5)
        d2 = [row for row in rows if row["item_id"] == "d2" and row["annotator"] == "a"][0]
        self.assertEqual(d2["human_correction"], "1")
        self.assertEqual(d2["human_truth"], 1)
        data = to_csv(rows, VERDICT_COLUMNS)
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"human_truth", data)

    def test_consistency_export(self) -> None:
        tasks, annotations, config = sample()
        summary = analyze(tasks, annotations, config)
        rows = consistency_rows(summary)
        data = to_csv(rows, CONSISTENCY_COLUMNS)
        self.assertIn(b"inter_annotator", data)
        self.assertIn(b"kappa", data)


if __name__ == "__main__":
    unittest.main()
