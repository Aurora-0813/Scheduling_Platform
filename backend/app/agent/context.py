"""Agent 调用上下文 —— 身份与需求原文注入 Tool 的唯一通道。

## 为什么需要这个文件

主文档 5.3 冻结的 `lock_resources(space_id, device_ids, start_time, end_time)` **没有
`user_id` 参数**；而模块 3 的 `create_order` 里 `user_id` 是必填。阶段 4 §3.3 给的处置是
「在 API 层从 JWT 解出 `user_id`，通过 Agent 的调用上下文传给 Tool，Tool 内部不用模型去猜」。
本文件就是那句「调用上下文」的落点。

**为什么不把 `user_id` 加进 Tool 签名**：签名是阶段 3 就冻结的，改签名等于让阶段 3 的桩、
阶段 7 的用例一起返工；而且 Tool 参数是**模型填的**——把 `user_id` 放进参数表，等于把
「替谁预约」交给模型决定，与主文档 5.1/9.1「身份一律从 JWT 解析」直接冲突。

## 方向是单向的：只写读、不写回

本文件只有**两个只读**变量，都由 API 层在 `astream()` 之前 `set()`：

| 变量 | 写入方 | 读取方 |
| --- | --- | --- |
| `_user_id` | API 层（JWT 解析后） | `lock_resources` |
| `_raw_request` | API 层（`ScheduleRequest.text`） | `lock_resources` |

**这里不放「Tool 写、调用方读」的变量**，这是一个实测过的坑，不是设计偏好：

LangGraph 的 `ToolNode` 用 `asyncio.gather()` 并发跑工具，`gather` 内部走
`ensure_future` → **创建 Task → 拷贝当前 context**。子任务里的 `ContextVar.set()`
**不会回写父 context**。所以「Tool 里 `set()` 一个方案对象、`run_schedule` 再 `get()`
出来」这条路径**根本不通**——在真实模型下会静默拿到 `None`，方案永远为空，
且本地用假 LLM 时可能因为执行路径不同而偶然通过，属于最难查的一类 bug。

需要「Tool 产出 → 调用方消费」的数据（模型交出的方案、落库的订单 ID），
一律从 **LangGraph 的 `messages` 流**里提取：
`AIMessage.tool_calls[].args` 拿入参、`ToolMessage.content` 拿返回。
那是框架的正式状态载体，跨 context 拷贝、跨版本都成立。
提取逻辑见 `app/agent/chains/builder.py`。
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

__all__ = ["get_agent_user_id", "get_raw_request", "agent_run_context"]

# 调用者身份。默认 None —— **不允许有任何兜底值**：读不到就是读不到，
# `lock_resources` 会据此返回明确失败，而不是编一个用户 ID 顶上。
_user_id: ContextVar[int | None] = ContextVar("agent_user_id", default=None)

# 用户原始需求原文，落 `reserve_order.agent_request`（主文档 6.3 表 6）。
_raw_request: ContextVar[str | None] = ContextVar("agent_raw_request", default=None)


def get_agent_user_id() -> int | None:
    """读当前调用上下文里的用户 ID。未注入时返回 `None`。"""
    return _user_id.get()


def get_raw_request() -> str | None:
    """读当前调用上下文里的用户原始需求。"""
    return _raw_request.get()


@contextmanager
def agent_run_context(user_id: int, raw_request: str) -> Iterator[None]:
    """一次 Agent 运行的上下文。API 层用它包住 `astream()`。

    读方向的值只在本块内可见：出了 with 块，任何 Tool 都读不到身份——
    防止一次运行的凭据被后续运行复用（同一个 worker 处理第二个请求时，
    若上一次的值还在，`lock_resources` 会拿**上一个用户**的身份落库）。

    用 `try/finally` + `set(None)` 复位而不是依赖 context 变量自动回收：
    `astream()` 内部会创建子任务，靠 `token` 复位在异常路径上更容易漏。
    """
    _user_id.set(user_id)
    _raw_request.set(raw_request)
    try:
        yield
    finally:
        _user_id.set(None)
        _raw_request.set(None)
