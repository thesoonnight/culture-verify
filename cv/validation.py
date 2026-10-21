"""标注载荷校验。

前端的 UI 只会写出结构正确的标注，但 `POST /api/datasets/<name>/annotations`
是公开契约：脚本、seed 工具、第三方导出器都会直接往里写。
一条结构不对的记录就足以让 `/stats` 和全部导出 500（`verdict.get` 撞到 str），
而 SQLite 里删记录又得停服手动来 —— 所以在入库前必须校验一次。

校验失败抛 `AnnotationInvalid`（ValueError 子类，带 `messages`），由 HTTP 层转成 400。
"""
from __future__ import annotations

from typing import Any

# 单图判定项的修正值 / 双图评分维度的修正值，按题目类型分开校验
POINTWISE_CORRECTIONS = {"0", "1", "?"}
PAIRWISE_CORRECTIONS = {"A", "B", "tie", "gap"}
ALLOWED_CORRECTIONS = POINTWISE_CORRECTIONS | PAIRWISE_CORRECTIONS

# "?" = 不确定，是「不知道真值」，不算一次修正；其余都算修正
COUNTED_CORRECTIONS = {"0", "1", "A", "B", "tie", "gap"}

ALLOWED_OVERALL = {"A", "B", "tie"}
ALLOWED_STATUS = {"doing", "done", "skipped", "flagged"}
ALLOWED_SHOWN_AS = {"AB", "BA"}
TIME_FIELDS = ("started_at", "finished_at", "updated_at")

MAX_ANNOTATOR = 64
MAX_NOTE = 20000


class AnnotationInvalid(ValueError):
    """标注结构不合法；`messages` 里是全部问题的清单。"""

    def __init__(self, messages: list[str] | str):
        if isinstance(messages, str):
            messages = [messages]
        self.messages = list(messages)
        super().__init__("；".join(self.messages[:4]))


def task_item_ids(task: dict) -> list[str]:
    if task.get("mode") == "pointwise":
        return [item["dim"] for item in task.get("items", [])]
    return [crit["id"] for crit in task.get("criteria", [])]


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _clean_correction(value: Any, mode: str) -> tuple[str | None, str | None]:
    """返回 (规范化的修正值, 错误信息)。"""
    if value is None or value == "":
        return None, None
    if isinstance(value, bool):
        return None, f"correction 不能是布尔值：{value!r}"
    if _is_number(value):
        # 脚本常把 0/1 当数字塞进来；统一成字符串，免得导出和 '0' 打架
        if float(value).is_integer():
            value = str(int(value))
        else:
            return None, f"correction 取值不合法：{value!r}"
    text = str(value).strip()
    allowed = POINTWISE_CORRECTIONS if mode == "pointwise" else PAIRWISE_CORRECTIONS
    if text not in allowed:
        return None, f"correction 只能是 {'/'.join(sorted(allowed))}，收到 {text!r}"
    return text, None


def validate_annotation(payload: dict, task: dict) -> dict:
    """校验并规范化一条标注；不合法时抛 AnnotationInvalid（列出全部问题）。"""
    errors: list[str] = []
    cleaned: dict[str, Any] = {}

    cleaned["task_id"] = task["id"]
    # mode 以题目为准，避免同一题被以另一个 mode 落库后前端读不回来
    cleaned["mode"] = task.get("mode")

    annotator = str(payload.get("annotator") or "").strip()
    if not annotator:
        errors.append("annotator 不能为空")
    elif len(annotator) > MAX_ANNOTATOR:
        errors.append(f"annotator 太长（上限 {MAX_ANNOTATOR} 字符）")
    cleaned["annotator"] = annotator

    status = payload.get("status")
    if status in (None, ""):
        cleaned["status"] = "doing"
    elif status in ALLOWED_STATUS:
        cleaned["status"] = status
    else:
        errors.append(f"status 只能是 {'/'.join(sorted(ALLOWED_STATUS))}，收到 {status!r}")
        cleaned["status"] = "doing"

    verdicts = payload.get("verdicts")
    if verdicts is None:
        verdicts = {}
    if not isinstance(verdicts, dict):
        errors.append("verdicts 必须是对象（形如 {\"d1\": {\"agree\": true}}）")
        verdicts = {}
    expected = task_item_ids(task)
    expected_set = set(expected)
    clean_verdicts: dict[str, dict] = {}
    for key, value in verdicts.items():
        dim = str(key)
        if expected_set and dim not in expected_set:
            errors.append(f"verdicts 里有本题不存在的判定项：{dim}（本题是 {', '.join(expected)}）")
            continue
        if not isinstance(value, dict):
            errors.append(f"verdicts.{dim} 必须是对象，收到 {type(value).__name__}")
            continue
        agree = value.get("agree")
        if not isinstance(agree, bool):
            errors.append(f"verdicts.{dim}.agree 必须是 true / false，收到 {agree!r}")
            continue
        correction, problem = _clean_correction(value.get("correction"), task.get("mode") or "")
        if problem:
            errors.append(f"verdicts.{dim}.{problem}")
            continue
        verdict = {"agree": agree}
        if correction is not None:
            verdict["correction"] = correction
        clean_verdicts[dim] = verdict
    cleaned["verdicts"] = clean_verdicts

    if "overall" in payload:
        overall = payload.get("overall")
        if overall in (None, ""):
            cleaned["overall"] = None
        elif overall in ALLOWED_OVERALL:
            cleaned["overall"] = overall
        else:
            errors.append(f"overall 只能是 A/B/tie，收到 {overall!r}")

    if "note" in payload:
        note = payload.get("note")
        if note is None:
            cleaned["note"] = ""
        elif not isinstance(note, str):
            errors.append("note 必须是字符串")
        elif len(note) > MAX_NOTE:
            errors.append(f"note 太长（上限 {MAX_NOTE} 字符）")
        else:
            cleaned["note"] = note

    if "shown_as" in payload:
        shown_as = payload.get("shown_as")
        if shown_as in (None, ""):
            cleaned["shown_as"] = None
        elif shown_as in ALLOWED_SHOWN_AS:
            cleaned["shown_as"] = shown_as
        else:
            errors.append(f"shown_as 只能是 AB/BA，收到 {shown_as!r}")

    if "duration_ms" in payload:
        duration = payload.get("duration_ms")
        if duration in (None, ""):
            cleaned["duration_ms"] = None
        elif not _is_number(duration) or duration < 0:
            errors.append(f"duration_ms 必须是非负数，收到 {duration!r}")
        else:
            cleaned["duration_ms"] = duration

    for field in TIME_FIELDS:
        if field in payload and payload[field] not in (None, ""):
            if not isinstance(payload[field], str):
                errors.append(f"{field} 必须是 ISO 时间字符串")
            else:
                cleaned[field] = payload[field]

    if errors:
        raise AnnotationInvalid(errors)
    return cleaned
