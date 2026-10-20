"""导入校验测试。"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from cv.importer import ImportProblem, import_dataset, import_zip_bytes
from cv.storage import Storage


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    return path


class ImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.storage = Storage(self.root / "data")
        make_image(self.root / "a.png")
        make_image(self.root / "b.png")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_jsonl_import(self) -> None:
        tasks = self.root / "tasks.jsonl"
        write(
            tasks,
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "pointwise",
                            "id": "T1",
                            "prompt": "p1",
                            "image": "a.png",
                            "items": [{"id": "d1", "score": 1, "label": "准确性"}],
                        }
                    ),
                    json.dumps(
                        {
                            "type": "pairwise",
                            "id": "P1",
                            "prompt": "p2",
                            "images": {"A": "a.png", "B": "b.png"},
                            "criteria": [{"id": "q1", "label": "质感"}],
                            "scores": {"A": {"q1": 7}, "B": {"q1": 3}},
                        }
                    ),
                ]
            ),
        )
        meta = import_dataset(self.storage, "demo", tasks)
        self.assertEqual(meta["task_count"], 2)
        loaded = self.storage.tasks("demo")
        self.assertEqual(loaded[0]["image"], "images/a.png")
        self.assertEqual(loaded[1]["images"]["B"], "images/b.png")
        self.assertTrue((self.storage.dataset_dir("demo") / "images/a.png").is_file())
        self.assertEqual(self.storage.meta("demo")["config"]["dimensions"][0]["label"], "准确性")

    def test_csv_import(self) -> None:
        path = self.root / "tasks.csv"
        write(
            path,
            "type,id,prompt,image,axis,lang,item_id,item_label,score,rationale\n"
            "pointwise,C1,p,img.png,服饰,zh,d1,准确性,1,ok\n"
            "pointwise,C1,p,img.png,服饰,zh,d2,错配,0,bad\n",
        )
        make_image(self.root / "img.png")
        meta = import_dataset(self.storage, "csv", path)
        tasks = self.storage.tasks("csv")
        self.assertEqual(meta["task_count"], 1)
        self.assertEqual(len(tasks[0]["items"]), 2)
        self.assertEqual(tasks[0]["items"][1]["dim"], "d2")
        self.assertEqual(tasks[0]["items"][1]["score"], 0)

    def test_pairwise_csv(self) -> None:
        path = self.root / "pairs.csv"
        write(
            path,
            "type,id,prompt,images_a,images_b,criterion_id,criterion_label,score_a,score_b\n"
            "pairwise,P1,p,a.png,b.png,q1,质感,7,3\n"
            "pairwise,P1,p,a.png,b.png,q2,细节,9,6\n",
        )
        meta = import_dataset(self.storage, "pairs", path)
        tasks = self.storage.tasks("pairs")
        self.assertEqual(meta["pairwise"], 1)
        self.assertEqual(len(tasks[0]["criteria"]), 2)
        self.assertEqual(tasks[0]["scores"]["A"]["q2"], 9)

    def test_missing_image_reports_error(self) -> None:
        path = self.root / "bad.jsonl"
        write(
            path,
            json.dumps(
                {
                    "type": "pointwise",
                    "id": "T1",
                    "prompt": "p",
                    "image": "nope.png",
                    "items": [{"dim": "d1", "score": 1}],
                }
            ),
        )
        with self.assertRaises(ImportProblem) as ctx:
            import_dataset(self.storage, "bad", path)
        self.assertIn("找不到图片", ctx.exception.messages[0])
        self.assertFalse(self.storage.exists("bad"))

    def test_invalid_score(self) -> None:
        path = self.root / "bad.jsonl"
        write(
            path,
            json.dumps(
                {
                    "type": "pointwise",
                    "id": "T1",
                    "prompt": "p",
                    "image": "a.png",
                    "items": [{"dim": "d1", "score": 2}],
                }
            ),
        )
        with self.assertRaises(ImportProblem) as ctx:
            import_dataset(self.storage, "bad", path)
        self.assertTrue(any("0/1" in message for message in ctx.exception.messages))

    def test_duplicate_ids(self) -> None:
        path = self.root / "dup.jsonl"
        write(
            path,
            "\n".join(
                json.dumps(
                    {
                        "type": "pointwise",
                        "id": "T1",
                        "prompt": "p",
                        "image": "a.png",
                        "items": [{"dim": "d1", "score": 1}],
                    }
                )
                for _ in range(2)
            ),
        )
        with self.assertRaises(ImportProblem) as ctx:
            import_dataset(self.storage, "dup", path)
        self.assertTrue(any("重复" in message for message in ctx.exception.messages))

    def test_zip_import(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
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
            archive.writestr(
                "config.json",
                json.dumps({"title": "zip 测试", "dimensions": [{"id": "d1", "label": "自定义"}]}),
            )
        meta = import_zip_bytes(self.storage, "zipdemo", buffer.getvalue())
        self.assertEqual(meta["task_count"], 1)
        self.assertEqual(meta["title"], "zip 测试")
        self.assertIn("自定义", json.dumps(self.storage.meta("zipdemo")["config"], ensure_ascii=False))

    def test_zip_slip_rejected(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../evil.txt", "bad")
            archive.writestr("tasks.jsonl", "{}")
        with self.assertRaises(ImportProblem):
            import_zip_bytes(self.storage, "evil", buffer.getvalue())
        self.assertFalse((self.root / "evil.txt").exists())

    def test_overwrite_guard(self) -> None:
        path = write(
            self.root / "t.jsonl",
            json.dumps(
                {
                    "type": "pointwise",
                    "id": "T1",
                    "prompt": "p",
                    "image": "a.png",
                    "items": [{"dim": "d1", "score": 1}],
                }
            ),
        )
        import_dataset(self.storage, "same", path)
        self.storage.save_annotation(
            "same",
            {
                "task_id": "T1",
                "annotator": "qa",
                "verdicts": {"d1": {"agree": True}},
                "mode": "pointwise",
            },
        )
        with self.assertRaises(ImportProblem):
            import_dataset(self.storage, "same", path)
        meta = import_dataset(self.storage, "same", path, overwrite=True)
        self.assertEqual(meta["task_count"], 1)
        self.assertEqual(self.storage.annotations("same"), [])


if __name__ == "__main__":
    unittest.main()
