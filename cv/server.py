"""本地 HTTP 服务：静态页面 + 数据集 / 标注 / 统计 / 导入导出 API。"""
from __future__ import annotations

import json
import mimetypes
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .analysis import analyze
from .exporting import (
    CONSISTENCY_COLUMNS,
    VERDICT_COLUMNS,
    annotations_jsonl,
    consistency_rows,
    summary_json,
    to_csv,
    verdict_rows,
)
from .importer import MAX_ZIP_BYTES, ImportProblem, import_zip_path
from .storage import Storage
from .validation import AnnotationInvalid

MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_IMPORT_BYTES = MAX_ZIP_BYTES
UPLOAD_CHUNK = 1024 * 1024

EXTRA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


class Handler(BaseHTTPRequestHandler):
    storage: Storage
    web_dir: Path
    server_version = "CultureVerify/0.2.1"
    protocol_version = "HTTP/1.1"

    # ----------------------------------------------------------------- utils
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        if self.path.startswith("/api/"):
            print(f"[api] {self.command} {self.path}")

    def _send(self, status: int, body: bytes, content_type: str, filename: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, message: str, messages: list[str] | None = None) -> None:
        self._json({"error": message, "messages": messages or []}, status=status)

    def _body(self, limit: int) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ValueError("请求体为空")
        if length > limit:
            raise ValueError("请求体过大")
        return self.rfile.read(length)

    def _body_to_file(self, limit: int) -> Path:
        """把上传流式写到临时文件：GB 级 zip 不再整个读进内存。"""
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ValueError("请求体为空")
        if length > limit:
            raise ValueError(f"上传超过上限（{limit // (1024 ** 3)} GB）")
        path = self.storage.temp_upload()
        remaining = length
        try:
            with path.open("wb") as handle:
                while remaining > 0:
                    chunk = self.rfile.read(min(UPLOAD_CHUNK, remaining))
                    if not chunk:
                        raise ValueError("上传中断")
                    handle.write(chunk)
                    remaining -= len(chunk)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return path

    def _require_json(self) -> None:
        """只收 JSON：挡住跨站 text/plain 的简单请求（no-cors 也能发的那种）。"""
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            raise ValueError(f"这个接口只收 application/json，收到 {content_type or '（空）'}")

    def _send_not_modified(self, etag: str) -> None:
        self.send_response(304)
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

    # ------------------------------------------------------------------ GET
    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)
            if path == "/api/health":
                self._json({"ok": True, "version": self.server_version, "datasets": len(self.storage.list_datasets())})
            elif path.startswith("/api/"):
                self._api_get(path, query)
            elif path.startswith("/media/"):
                self._media(path)
            else:
                self._static(path)
        except KeyError as exc:
            self._error(404, str(exc).strip("'"))
        except ValueError as exc:
            self._error(400, str(exc))
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            self._error(500, "服务器内部错误")

    def _api_get(self, path: str, query: dict) -> None:
        parts = [p for p in path.split("/") if p]
        if parts[:2] != ["api", "datasets"]:
            raise KeyError(f"未知接口：{path}")
        if len(parts) == 2:
            self._json({"datasets": self.storage.list_datasets()})
            return
        name = parts[2]
        if len(parts) == 3:
            meta = self.storage.meta(name)
            meta["annotators"] = self.storage.annotators(name)
            meta["annotation_count"] = self.storage.annotation_count(name)
            self._json({"dataset": meta})
            return

        action = parts[3]
        annotator = (query.get("annotator") or [None])[0]
        if action == "tasks":
            meta = self.storage.meta(name)
            self._json(
                {
                    "dataset": meta,
                    "config": meta.get("config", {}),
                    "tasks": self.storage.tasks(name),
                }
            )
        elif action == "annotations":
            self._json({"annotations": self.storage.annotations(name, annotator)})
        elif action == "stats":
            tasks = self.storage.tasks(name)
            meta = self.storage.meta(name)
            annotations = self.storage.annotations(name, annotator)
            summary = analyze(tasks, annotations, meta.get("config") or {})
            summary["dataset"] = {"name": name, "title": meta.get("title") or name}
            self._json(summary)
        elif action == "export":
            kind = (query.get("kind") or ["verdicts"])[0]
            self._export(name, kind, annotator)
        else:
            raise KeyError(f"未知接口：{path}")

    def _export(self, name: str, kind: str, annotator: str | None) -> None:
        tasks = self.storage.tasks(name)
        meta = self.storage.meta(name)
        config = meta.get("config") or {}
        annotations = self.storage.annotations(name, annotator)
        stem = name + ("-" + annotator if annotator else "")
        if kind == "verdicts":
            rows = verdict_rows(tasks, annotations, config)
            body = to_csv(rows, VERDICT_COLUMNS)
            self._send(200, body, "text/csv; charset=utf-8", f"{stem}-verdicts.csv")
        elif kind == "annotations":
            self._send(200, annotations_jsonl(annotations), "application/x-ndjson; charset=utf-8", f"{stem}-annotations.jsonl")
        elif kind == "consistency":
            summary = analyze(tasks, annotations, config)
            body = to_csv(consistency_rows(summary), CONSISTENCY_COLUMNS)
            self._send(200, body, "text/csv; charset=utf-8", f"{stem}-consistency.csv")
        elif kind == "summary":
            summary = analyze(tasks, annotations, config)
            summary["dataset"] = {"name": name, "title": meta.get("title") or name}
            self._send(200, summary_json(summary), "application/json; charset=utf-8", f"{stem}-summary.json")
        else:
            raise ValueError(f"未知导出类型：{kind}")

    def _media(self, path: str) -> None:
        parts = [p for p in path.split("/") if p]
        if len(parts) < 3:
            raise KeyError("图片路径不完整")
        name = parts[1]
        rel = "/".join(parts[2:])
        target = self.storage.media_path(name, rel)
        if not target.is_file():
            raise KeyError(f"图片不存在：{rel}")
        content_type = EXTRA_TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        stat = target.stat()
        # 覆盖导入后同名图片常见，靠 ETag 让浏览器校验而不是傻缓存一小时
        etag = f'"{int(stat.st_mtime)}-{stat.st_size}"'
        if (self.headers.get("If-None-Match") or "").strip() == etag:
            self._send_not_modified(etag)
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _static(self, path: str) -> None:
        rel = path.lstrip("/") or "index.html"
        if rel.endswith("/"):
            rel += "index.html"
        root = self.web_dir.resolve()
        target = (root / rel).resolve()
        if root not in target.parents and target != root:
            raise KeyError("非法路径")
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            raise KeyError(f"文件不存在：{rel}")
        content_type = EXTRA_TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ----------------------------------------------------------------- POST
    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)
            parts = [p for p in path.split("/") if p]
            if parts[:3] == ["api", "datasets", "import"]:
                self._import(query)
                return
            if len(parts) == 4 and parts[:2] == ["api", "datasets"] and parts[3] == "annotations":
                self._save_annotation(parts[2])
                return
            if len(parts) == 4 and parts[:2] == ["api", "datasets"] and parts[3] == "config":
                self._update_config(parts[2])
                return
            raise KeyError(f"未知接口：{path}")
        except ImportProblem as exc:
            self._error(400, "导入失败", exc.messages)
        except AnnotationInvalid as exc:
            self._error(400, "标注格式不对", exc.messages)
        except KeyError as exc:
            self._error(404, str(exc).strip("'"))
        except ValueError as exc:
            self._error(400, str(exc))
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            self._error(500, "服务器内部错误")

    # --------------------------------------------------------------- DELETE
    def do_DELETE(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)
            parts = [p for p in path.split("/") if p]
            if parts[:2] != ["api", "datasets"] or len(parts) < 3:
                raise KeyError(f"未知接口：{path}")
            name = parts[2]
            if len(parts) == 3:
                self.storage.delete_dataset(name)
                self._json({"ok": True, "deleted_dataset": name})
                return
            if len(parts) == 4 and parts[3] == "annotations":
                annotator = (query.get("annotator") or [None])[0]
                task_id = (query.get("task_id") or [None])[0]
                deleted = self.storage.delete_annotations(name, annotator, task_id)
                self._json({"ok": True, "deleted": deleted})
                return
            raise KeyError(f"未知接口：{path}")
        except KeyError as exc:
            self._error(404, str(exc).strip("'"))
        except ValueError as exc:
            self._error(400, str(exc))
        except OSError as exc:
            self._error(500, f"删除失败：{exc}")
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            self._error(500, "服务器内部错误")

    def _save_annotation(self, name: str) -> None:
        self._require_json()
        raw = self._body(MAX_JSON_BYTES)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 解析失败：{exc}") from exc
        annotation = data.get("annotation") if isinstance(data, dict) else None
        if not isinstance(annotation, dict):
            raise ValueError("需要 {annotation: {...}}")
        saved = self.storage.save_annotation(name, annotation)
        self._json({"ok": True, "annotation": saved})

    def _import(self, query: dict) -> None:
        name = (query.get("name") or [""])[0].strip()
        title = (query.get("title") or [""])[0].strip()
        overwrite = (query.get("overwrite") or ["0"])[0] in ("1", "true", "yes")
        if not name:
            raise ValueError("缺少数据集名称 ?name=")
        upload = self._body_to_file(MAX_IMPORT_BYTES)
        try:
            meta = import_zip_path(self.storage, name, upload, title=title, overwrite=overwrite)
        finally:
            upload.unlink(missing_ok=True)
        self._json({"ok": True, "dataset": meta})

    def _update_config(self, name: str) -> None:
        self._require_json()
        raw = self._body(MAX_JSON_BYTES)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 解析失败：{exc}") from exc
        labels = data.get("labels") if isinstance(data, dict) else None
        questions = data.get("questions") if isinstance(data, dict) else None
        if not isinstance(labels, dict) and not isinstance(questions, dict):
            raise ValueError("需要 {labels: {...}, questions: {...}}")
        config = self.storage.update_config(name, labels or {}, questions or {})
        self._json({"ok": True, "config": config})


def make_server(host: str, port: int, storage: Storage, web_dir: str | Path) -> ThreadingHTTPServer:
    class BoundHandler(Handler):
        pass

    BoundHandler.storage = storage
    BoundHandler.web_dir = Path(web_dir)
    httpd = ThreadingHTTPServer((host, port), BoundHandler)
    httpd.daemon_threads = True
    return httpd
