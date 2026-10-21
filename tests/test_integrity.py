"""数据完整性 / 恢复能力测试。

对应这几条评审发现：
  * 一条结构不对的标注会让 /stats 与全部导出 500，而且没有删除接口；
  * 数字 0 的修正值在导出时被 `or ""` 吃掉；
  * 图片缓存一小时，覆盖导入后同名图不变；
  * 上传整个 zip 进内存、1 GB 上限。
"""
from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from cv.analysis import analyze
from cv.exporting import VERDICT_COLUMNS, to_csv, verdict_rows
from cv.importer import ImportProblem, import_zip_path
from cv.server import make_server
from cv.storage import Storage
from cv.validation import AnnotationInvalid, validate_annotation

WEB_DIR = Path(__file__).resolve().parents[1] / "prototype"


def make_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)


class IntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        make_image(root / "a.png")
        make_image(root / "b.png")
        (root / "tasks.jsonl").write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "pointwise",
                            "id": "T1",
                            "prompt": "p1",
                            "image": "a.png",
                            "items": [
                                {"dim": "d1", "score": 1},
                                {"dim": "d2", "score": 0},
                            ],
                        }
                    ),
                    json.dumps(
                        {
                            "type": "pairwise",
                            "id": "P1",
                            "prompt": "p2",
                            "images": {"A": "a.png", "B": "b.png"},
                            "criteria": [{"id": "q1"}],
                            "scores": {"A": {"q1": 7}, "B": {"q1": 3}},
                        }
                    ),
                ]
            ),
            encoding="utf-8",
        )
        cls.storage = Storage(root / "data")
        cls.storage.save_annotation  # noqa: B018
        from cv.importer import import_dataset

        import_dataset(cls.storage, "ds", root / "tasks.jsonl")
        cls.httpd = make_server("127.0.0.1", 0, cls.storage, WEB_DIR)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    # ------------------------------------------------------------------ http
    def request(self, path, method="GET", data=None, headers=None):
        req = urllib.request.Request(self.base + path, data=data, method=method)
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return res.status, res.headers, res.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def post_annotation(self, annotation, content_type="application/json"):
        body = json.dumps({"annotation": annotation}).encode("utf-8")
        status, headers, raw = self.request(
            "/api/datasets/ds/annotations", "POST", body, {"Content-Type": content_type}
        )
        return status, json.loads(raw) if raw else {}

    # -------------------------------------------------------- 标注结构校验
    def test_verdict_must_be_object(self) -> None:
        status, data = self.post_annotation(
            {"task_id": "T1", "annotator": "qa", "verdicts": {"d1": "yes"}}
        )
        self.assertEqual(status, 400)
        self.assertIn("verdicts.d1", " ".join(data["messages"]))

    def test_agree_must_be_bool(self) -> None:
        status, data = self.post_annotation(
            {"task_id": "T1", "annotator": "qa", "verdicts": {"d1": {"agree": "true"}}}
        )
        self.assertEqual(status, 400)
        self.assertTrue(any("agree" in message for message in data["messages"]))

    def test_unknown_dim_rejected(self) -> None:
        status, data = self.post_annotation(
            {"task_id": "T1", "annotator": "qa", "verdicts": {"d9": {"agree": True}}}
        )
        self.assertEqual(status, 400)
        self.assertTrue(any("d9" in message for message in data["messages"]))

    def test_correction_must_match_task_mode(self) -> None:
        status, _ = self.post_annotation(
            {"task_id": "T1", "annotator": "qa", "verdicts": {"d1": {"agree": False, "correction": "A"}}}
        )
        self.assertEqual(status, 400, "单图任务的修正值不该接受 A/B/gap")
        status, _ = self.post_annotation(
            {"task_id": "P1", "annotator": "qa", "verdicts": {"q1": {"agree": False, "correction": "0"}}}
        )
        self.assertEqual(status, 400, "双图任务的修正值不该接受 0/1")

    def test_numeric_correction_normalized_to_string(self) -> None:
        annotation = validate_annotation(
            {"task_id": "T1", "annotator": "qa", "verdicts": {"d1": {"agree": False, "correction": 0}}},
            {"id": "T1", "mode": "pointwise", "items": [{"dim": "d1"}]},
        )
        self.assertEqual(annotation["verdicts"]["d1"]["correction"], "0")

    def test_non_json_content_type_rejected(self) -> None:
        status, data = self.post_annotation(
            {"task_id": "T1", "annotator": "qa", "verdicts": {}}, content_type="text/plain"
        )
        self.assertEqual(status, 400)
        self.assertIn("application/json", data["error"])

    def test_annotation_invalid_exposes_all_messages(self) -> None:
        with self.assertRaises(AnnotationInvalid) as ctx:
            validate_annotation(
                {
                    "task_id": "T1",
                    "annotator": "",
                    "verdicts": {"d1": {"agree": "nope"}, "d9": {"agree": True}},
                    "overall": "Z",
                },
                {"id": "T1", "mode": "pointwise", "items": [{"dim": "d1"}]},
            )
        self.assertGreaterEqual(len(ctx.exception.messages), 3)

    # ------------------------------------------------- 历史脏数据不能让报告 500
    def test_stats_survive_legacy_bad_row(self) -> None:
        conn = sqlite3.connect(self.storage.db_path)
        conn.execute(
            "INSERT INTO annotations (dataset, task_id, annotator, payload, status, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                "ds",
                "T1",
                "legacy",
                json.dumps({"task_id": "T1", "annotator": "legacy", "verdicts": {"d1": "yes"}}),
                "done",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.commit()
        conn.close()
        status, _, raw = self.request("/api/datasets/ds/stats")
        self.assertEqual(status, 200, raw[:200])
        summary = json.loads(raw)
        self.assertGreaterEqual(summary["overall"]["n"], 0)
        status, _, raw = self.request("/api/datasets/ds/export?kind=verdicts")
        self.assertEqual(status, 200, raw[:200])
        # 顺手清理，别影响后面的用例
        self.storage.delete_annotations("ds", "legacy")

    # ----------------------------------------------------------- 删除能力
    def test_delete_annotation_and_dataset(self) -> None:
        self.post_annotation(
            {"task_id": "T1", "annotator": "deleter", "verdicts": {"d1": {"agree": True}}}
        )
        status, _, raw = self.request(
            "/api/datasets/ds/annotations?annotator=deleter&task_id=T1", "DELETE"
        )
        self.assertEqual(status, 200, raw[:200])
        self.assertEqual(json.loads(raw)["deleted"], 1)
        status, _, raw = self.request("/api/datasets/ds/annotations?annotator=deleter")
        self.assertEqual(json.loads(raw)["annotations"], [])

        # 单独建一个数据集，删掉后应该 404
        make_image(Path(self.tmp.name) / "c.png")
        (Path(self.tmp.name) / "tmp_tasks.jsonl").write_text(
            json.dumps(
                {
                    "type": "pointwise",
                    "id": "X1",
                    "prompt": "p",
                    "image": "c.png",
                    "items": [{"dim": "d1", "score": 1}],
                }
            ),
            encoding="utf-8",
        )
        from cv.importer import import_dataset

        import_dataset(self.storage, "tempds", Path(self.tmp.name) / "tmp_tasks.jsonl")
        status, _, _ = self.request("/api/datasets/tempds", "DELETE")
        self.assertEqual(status, 200)
        status, _, _ = self.request("/api/datasets/tempds/tasks")
        self.assertEqual(status, 404)

    # ------------------------------------------------------- 导出口径
    def test_export_keeps_zero_correction(self) -> None:
        tasks = [
            {
                "mode": "pointwise",
                "id": "T1",
                "prompt": "p",
                "items": [{"dim": "d1", "score": 1}],
            }
        ]
        annotations = [
            {
                "task_id": "T1",
                "annotator": "qa",
                "verdicts": {"d1": {"agree": False, "correction": "0"}},
                "duration_ms": 0,
            }
        ]
        rows = verdict_rows(tasks, annotations, {})
        self.assertEqual(rows[0]["human_correction"], "0", "修正值 0 不能被当成空")
        self.assertEqual(rows[0]["human_truth"], 0)
        self.assertEqual(rows[0]["duration_ms"], 0, "0 毫秒也是有效值")
        self.assertIn("prompt", VERDICT_COLUMNS)
        text = to_csv(rows, VERDICT_COLUMNS).decode("utf-8-sig")
        self.assertIn("T1,pointwise,qa", text)

    def test_question_mark_is_not_a_correction(self) -> None:
        tasks = [
            {"mode": "pointwise", "id": "T1", "prompt": "p", "items": [{"dim": "d1", "score": 1}]}
        ]
        annotations = [
            {
                "task_id": "T1",
                "annotator": "qa",
                "verdicts": {"d1": {"agree": False, "correction": "?"}},
            }
        ]
        summary = analyze(tasks, annotations, {})
        self.assertEqual(summary["dimensions"][0]["corrected"], 0)
        self.assertEqual(summary["dimensions"][0]["truth_n"], 0)

    def test_kappa_reports_its_own_denominator(self) -> None:
        tasks = [
            {"mode": "pointwise", "id": "T1", "prompt": "p", "items": [{"dim": "d1", "score": 1}]},
            {"mode": "pointwise", "id": "T2", "prompt": "p", "items": [{"dim": "d1", "score": 1}]},
        ]
        annotations = [
            {"task_id": "T1", "annotator": "a", "verdicts": {"d1": {"agree": True}}},
            {"task_id": "T1", "annotator": "b", "verdicts": {"d1": {"agree": True}}},
            {"task_id": "T2", "annotator": "a", "verdicts": {"d1": {"agree": True}}},
            {"task_id": "T2", "annotator": "b", "verdicts": {"d1": {"agree": False}}},
        ]
        inter = analyze(tasks, annotations, {})["inter_annotator"]
        self.assertEqual(inter["n_comparisons"], 2)
        self.assertIsNotNone(inter["kappa"])
        self.assertEqual(inter["n_kappa_comparisons"], 2)

    # --------------------------------------------------------- 图片缓存
    def test_media_honours_etag(self) -> None:
        status, headers, _ = self.request("/media/ds/images/a.png")
        self.assertEqual(status, 200)
        etag = headers.get("ETag")
        self.assertTrue(etag)
        self.assertIn("no-cache", headers.get("Cache-Control", ""))
        status, headers, body = self.request(
            "/media/ds/images/a.png", headers={"If-None-Match": etag}
        )
        self.assertEqual(status, 304)
        self.assertEqual(body, b"")

    # ----------------------------------------------------------- 导入
    def test_import_zip_from_disk(self) -> None:
        root = Path(self.tmp.name)
        archive_path = root / "pack.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(
                "tasks.jsonl",
                json.dumps(
                    {
                        "type": "pointwise",
                        "id": "Z1",
                        "prompt": "p",
                        "image": "images/a.png",
                        "items": [{"dim": "d1", "score": 1}],
                    }
                ),
            )
            archive.writestr("images/a.png", b"\x89PNG\r\n\x1a\n" + b"0" * 16)
        meta = import_zip_path(self.storage, "diskds", archive_path)
        self.assertEqual(meta["task_count"], 1)
        self.assertTrue((self.storage.dataset_dir("diskds") / "images/a.png").is_file())

    def test_fractional_score_rejected(self) -> None:
        root = Path(self.tmp.name)
        make_image(root / "frac.png")
        path = root / "frac.jsonl"
        path.write_text(
            json.dumps(
                {
                    "type": "pointwise",
                    "id": "F1",
                    "prompt": "p",
                    "image": "frac.png",
                    "items": [{"dim": "d1", "score": 0.9}],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(ImportProblem) as ctx:
            from cv.importer import import_dataset

            import_dataset(self.storage, "frac", path)
        self.assertTrue(any("整数" in message for message in ctx.exception.messages))

    def test_csv_note_from_any_row(self) -> None:
        root = Path(self.tmp.name)
        make_image(root / "n.png")
        path = root / "note.csv"
        path.write_text(
            "type,id,prompt,image,item_id,score,note\n"
            "pointwise,N1,p,n.png,d1,1,\n"
            "pointwise,N1,p,n.png,d2,0,第二行才写的备注\n",
            encoding="utf-8",
        )
        from cv.importer import import_dataset

        import_dataset(self.storage, "noteds", path)
        tasks = self.storage.tasks("noteds")
        self.assertEqual(tasks[0].get("note"), "第二行才写的备注")


if __name__ == "__main__":
    unittest.main()
