"""HTTP API 测试（真实起一个本地 server）。"""
from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from cv.importer import import_dataset
from cv.server import make_server
from cv.storage import Storage

WEB_DIR = Path(__file__).resolve().parents[1] / "prototype"


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        (root / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
        (root / "b.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"1" * 32)
        tasks = root / "tasks.jsonl"
        tasks.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "pointwise",
                            "id": "T1",
                            "prompt": "p",
                            "image": "a.png",
                            "items": [{"dim": "d1", "score": 1}],
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
        import_dataset(cls.storage, "ds", tasks)
        cls.httpd = make_server("127.0.0.1", 0, cls.storage, WEB_DIR)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def request(self, path: str, method: str = "GET", data: bytes | None = None,
                headers: dict | None = None):
        req = urllib.request.Request(self.base + path, data=data, method=method)
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status, res.headers, res.read()

    def json_request(self, path: str, method: str = "GET", payload: dict | None = None):
        body = json.dumps(payload).encode() if payload is not None else None
        status, headers, raw = self.request(
            path, method, body, {"Content-Type": "application/json"}
        )
        return status, json.loads(raw)

    def test_health_and_datasets(self) -> None:
        status, data = self.json_request("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        status, data = self.json_request("/api/datasets")
        self.assertIn("ds", [item["name"] for item in data["datasets"]])

    def test_tasks_endpoint(self) -> None:
        status, data = self.json_request("/api/datasets/ds/tasks")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["tasks"]), 2)
        self.assertEqual(data["config"]["dimensions"][0]["id"], "d1")

    def test_save_annotation_and_stats(self) -> None:
        payload = {
            "annotation": {
                "task_id": "T1",
                "mode": "pointwise",
                "annotator": "qa",
                "status": "done",
                "verdicts": {"d1": {"agree": False, "correction": "0"}},
                "duration_ms": 1234,
            }
        }
        status, data = self.json_request("/api/datasets/ds/annotations", "POST", payload)
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])

        status, annotations = self.json_request("/api/datasets/ds/annotations?annotator=qa")
        self.assertEqual(len(annotations["annotations"]), 1)
        self.assertEqual(annotations["annotations"][0]["verdicts"]["d1"]["correction"], "0")

        status, stats = self.json_request("/api/datasets/ds/stats")
        self.assertGreaterEqual(stats["overall"]["n"], 1)
        self.assertIn("qa", stats["annotators"])

    def test_export_csv_and_bom(self) -> None:
        self.json_request(
            "/api/datasets/ds/annotations",
            "POST",
            {
                "annotation": {
                    "task_id": "T1",
                    "mode": "pointwise",
                    "annotator": "exportuser",
                    "status": "done",
                    "verdicts": {"d1": {"agree": True}},
                }
            },
        )
        status, headers, body = self.request("/api/datasets/ds/export?kind=verdicts")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers.get("Content-Disposition", ""))
        self.assertTrue(body.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"task_id,mode,annotator", body)
        status, headers, body = self.request("/api/datasets/ds/export?kind=consistency")
        self.assertIn(b"kappa", body)
        status, headers, body = self.request("/api/datasets/ds/export?kind=annotations")
        self.assertIn(b"exportuser", body)

    def test_media(self) -> None:
        status, headers, body = self.request("/media/ds/images/a.png")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get_content_type(), "image/png")
        self.assertGreater(len(body), 8)

    def test_update_config(self) -> None:
        status, data = self.json_request(
            "/api/datasets/ds/config", "POST", {"labels": {"d1": "改名后"}, "questions": {}}
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["config"]["dimensions"][0]["label"], "改名后")
        status, data = self.json_request("/api/datasets/ds/tasks")
        self.assertEqual(data["config"]["dimensions"][0]["label"], "改名后")

    def test_import_zip_endpoint(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "tasks.jsonl",
                json.dumps(
                    {
                        "type": "pointwise",
                        "id": "Z1",
                        "prompt": "p",
                        "image": "images/z.png",
                        "items": [{"dim": "d1", "score": 1}],
                    }
                ),
            )
            archive.writestr("images/z.png", b"\x89PNG\r\n\x1a\n" + b"z" * 16)
        status, headers, raw = self.request(
            "/api/datasets/import?name=zipds", "POST", buffer.getvalue(), {"Content-Type": "application/zip"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(raw)["ok"])
        status, data = self.json_request("/api/datasets/zipds/tasks")
        self.assertEqual(len(data["tasks"]), 1)

    def test_unknown_dataset_is_404(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.request("/api/datasets/nope/tasks")
        self.assertEqual(ctx.exception.code, 404)

    def test_invalid_annotation_is_400(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.json_request("/api/datasets/ds/annotations", "POST", {"annotation": {}})
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
