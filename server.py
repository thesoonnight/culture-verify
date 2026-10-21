#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Culture Verify 本地服务 / 数据集工具。

常用：
    python server.py serve --port 8765
    python server.py import --name culture-v1 --tasks tasks.jsonl --images ./images
    python server.py import --name culture-v1 --zip culture-v1.zip
    python server.py list
    python server.py export --name culture-v1 --kind verdicts --out verdicts.csv
    python server.py rm --name culture-v1 --dataset
    python server.py rm --name culture-v1 --annotator lin
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import webbrowser
from pathlib import Path

from cv.analysis import analyze
from cv.exporting import (
    CONSISTENCY_COLUMNS,
    VERDICT_COLUMNS,
    annotations_jsonl,
    consistency_rows,
    summary_json,
    to_csv,
    verdict_rows,
)
from cv.importer import ImportProblem, import_dataset, import_zip_file
from cv.server import make_server
from cv.storage import Storage

ROOT = Path(__file__).resolve().parent
DEFAULT_DATA = Path(os.environ.get("CV_DATA") or (ROOT / "data"))
WEB_DIR = ROOT / "prototype"


def _storage(args) -> Storage:
    return Storage(Path(args.data))


def _port_busy(host: str, port: int) -> bool:
    """Windows 上 SO_REUSEADDR 允许两个进程同时绑同一端口：不先探一下，
    第二个 serve 会"启动成功"但一个请求都收不到（全被老进程接走）。"""
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "", "::", "*") else host
    try:
        with socket.create_connection((probe_host, port), timeout=0.5):
            return True
    except OSError:
        return False


def cmd_serve(args) -> int:
    storage = _storage(args)
    datasets = storage.list_datasets()
    if _port_busy(args.host, args.port):
        print(
            f"端口 {args.port} 已经被占用 —— 很可能已经有一个 serve 在跑。\n"
            f"  · 直接用浏览器打开 http://127.0.0.1:{args.port}/ 看是不是那个实例；\n"
            f"  · 或者换一个端口：--port {args.port + 1}；\n"
            f"  · 或者先停掉旧的 python 进程再启动。",
            file=sys.stderr,
        )
        return 2
    try:
        httpd = make_server(args.host, args.port, storage, WEB_DIR)
    except OSError as exc:
        print(f"启动失败（端口 {args.port}）：{exc}", file=sys.stderr)
        return 2
    print(f"Culture Verify · 数据目录 {storage.root}")
    print(f"数据集 {len(datasets)} 个：{', '.join(d['name'] for d in datasets) or '（空，可在页面里导入 zip）'}")
    url = f"http://{args.host}:{args.port}/"
    print(f"打开 {url}")
    if args.open:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n再见。")
    finally:
        httpd.server_close()
    return 0


def cmd_import(args) -> int:
    storage = _storage(args)
    try:
        if args.zip:
            meta = import_zip_file(
                storage, args.name, args.zip, title=args.title, overwrite=args.overwrite
            )
        else:
            if not args.tasks:
                raise ImportProblem("需要 --tasks 或 --zip")
            meta = import_dataset(
                storage,
                args.name,
                args.tasks,
                images_dir=args.images,
                config_path=args.config,
                title=args.title,
                overwrite=args.overwrite,
            )
    except ImportProblem as exc:
        print("导入失败：", file=sys.stderr)
        for message in exc.messages:
            print("  -", message, file=sys.stderr)
        return 2
    print(f"已导入 {meta['name']}：{meta['task_count']} 题（单图 {meta['pointwise']} / 双图 {meta['pairwise']}）")
    print(f"图片目录：{storage.dataset_dir(meta['name']) / 'images'}")
    return 0


def cmd_list(args) -> int:
    storage = _storage(args)
    datasets = storage.list_datasets()
    if not datasets:
        print("还没有数据集。用 python server.py import ... 或页面里的「导入」。")
        return 0
    print(f"{'name':<22}{'单图':>6}{'双图':>6}{'标注':>6}  标题")
    for meta in datasets:
        print(
            f"{meta['name']:<22}{meta.get('pointwise', 0):>6}{meta.get('pairwise', 0):>6}"
            f"{meta.get('annotation_count', 0):>6}  {meta.get('title', '')}"
        )
    return 0


def cmd_export(args) -> int:
    storage = _storage(args)
    tasks = storage.tasks(args.name)
    meta = storage.meta(args.name)
    annotations = storage.annotations(args.name, args.annotator)
    config = meta.get("config") or {}
    if args.kind == "verdicts":
        data = to_csv(verdict_rows(tasks, annotations, config), VERDICT_COLUMNS)
        suffix = ".csv"
    elif args.kind == "annotations":
        data = annotations_jsonl(annotations)
        suffix = ".jsonl"
    elif args.kind == "consistency":
        data = to_csv(consistency_rows(analyze(tasks, annotations, config)), CONSISTENCY_COLUMNS)
        suffix = ".csv"
    else:
        data = summary_json(analyze(tasks, annotations, config))
        suffix = ".json"
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"已写入 {path}（{len(data)} 字节）")
    else:
        sys.stdout.buffer.write(data)
        print()
    return 0


def cmd_rm(args) -> int:
    storage = _storage(args)
    try:
        if args.dataset:
            storage.delete_dataset(args.name)
            print(f"已删除数据集 {args.name}（含它的全部标注）")
            return 0
        deleted = storage.delete_annotations(args.name, args.annotator, args.task)
    except KeyError as exc:
        print(exc.args[0], file=sys.stderr)
        return 2
    scope = []
    if args.annotator:
        scope.append(f"标注员 {args.annotator}")
    if args.task:
        scope.append(f"题目 {args.task}")
    print(f"已删除 {deleted} 条标注（{' / '.join(scope) or '全部标注员'}）")
    return 0


def cmd_stats(args) -> int:
    storage = _storage(args)
    tasks = storage.tasks(args.name)
    meta = storage.meta(args.name)
    summary = analyze(tasks, storage.annotations(args.name, args.annotator), meta.get("config") or {})
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"已写入 {args.out}")
    else:
        print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data", default=str(DEFAULT_DATA), help="数据目录（默认 culture-verify/data）")

    parser = argparse.ArgumentParser(prog="server.py", description="Culture Verify 本地服务与数据集工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", parents=[common], help="启动本地服务")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    serve.set_defaults(func=cmd_serve)

    imp = sub.add_parser("import", parents=[common], help="导入评分集 + 图片集")
    imp.add_argument("--name", required=True, help="数据集名称（字母/数字/-/_）")
    imp.add_argument("--tasks", help="tasks.jsonl / tasks.json / tasks.csv")
    imp.add_argument("--images", help="图片目录（图片路径也可以写在 tasks 里）")
    imp.add_argument("--config", help="可选 config.json（维度名称）")
    imp.add_argument("--zip", help="直接导入 zip 包")
    imp.add_argument("--title", default="", help="数据集标题")
    imp.add_argument("--overwrite", action="store_true", help="覆盖同名数据集")
    imp.set_defaults(func=cmd_import)

    lst = sub.add_parser("list", parents=[common], help="列出数据集")
    lst.set_defaults(func=cmd_list)

    exp = sub.add_parser("export", parents=[common], help="导出结果")
    exp.add_argument("--name", required=True)
    exp.add_argument("--kind", default="verdicts", choices=["verdicts", "annotations", "consistency", "summary"])
    exp.add_argument("--annotator", default=None)
    exp.add_argument("--out", default=None)
    exp.set_defaults(func=cmd_export)

    rm = sub.add_parser("rm", parents=[common], help="删数据集或标注（之前只能手动进 sqlite）")
    rm.add_argument("--name", required=True)
    rm.add_argument("--dataset", action="store_true", help="整个数据集（含全部标注）")
    rm.add_argument("--annotator", default=None, help="只删这位标注员的标注")
    rm.add_argument("--task", default=None, help="只删这道题（配合 --annotator 更精确）")
    rm.set_defaults(func=cmd_rm)

    stats = sub.add_parser("stats", parents=[common], help="打印一致性报告")
    stats.add_argument("--name", required=True)
    stats.add_argument("--annotator", default=None)
    stats.add_argument("--out", default=None)
    stats.set_defaults(func=cmd_stats)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
