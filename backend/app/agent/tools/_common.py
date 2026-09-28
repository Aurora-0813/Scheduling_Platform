"""Tool 层共用的小工具：入参校验与统一失败返回。

放这里的都是**纯函数**——不碰库、不碰网络，因此不违反「Tool 不直接使用 AsyncSession」。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

__all__ = ["TIME_FORMATS", "parse_time", "fail", "MAX_REASON_LEN"]

#: 允许的时间格式。模型给的格式不保证唯一——真实调用里 "2026-09-30 14:00" 与
#: ISO 的 "2026-09-30T14:00:00" 都出现过，逐个试比先纠正模型便宜。
TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)

#: 回给模型的失败原因上限。Tool 的返回值会被塞进下一轮 Prompt，
#: 太长会挤掉真正的上下文。
MAX_REASON_LEN = 300


def parse_time(raw: Any) -> datetime | None:
    """解析时间串；解不出返回 `None`（由调用方转成业务失败，**不抛异常**）。

    Tool 里不抛异常是有意的：抛出去 LangGraph 会把它包成 ToolMessage 里的错误文本，
    模型只看到一坨 traceback，既不能自纠也污染 trace；返回结构化失败，模型能看懂并改参数。
    """
    if isinstance(raw, datetime):
        return raw
    if not isinstance(raw, str):
        return None
    text = raw.strip().replace("/", "-")
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def fail(reason: str, **extra: Any) -> dict[str, Any]:
    """Tool 层统一的业务失败返回。

    `ok=False` 是**约定键**：模型据此知道这次调用没成功、需要换参数重试或转备选方案。
    额外字段（如 `spaces`）照常返回空集，保证模型侧读 `result["spaces"]` 不会 KeyError。
    """
    if len(reason) > MAX_REASON_LEN:
        reason = reason[: MAX_REASON_LEN - 3] + "..."
    return {"ok": False, "reason": reason, **extra}
