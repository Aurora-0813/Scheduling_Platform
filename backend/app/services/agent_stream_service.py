"""流式调度的**任务缓存**（2026-10-13 新增）。

## 为什么是「任务 + 轮询」而不是 SSE

APK（uni-app App 端）的 `uni.request` **拿不到分块响应** —— 收不到 SSE。
既然小程序/APK 必须轮询，Web 也走同一条路：**后端只写一套事件流，两种取法合并成一种**，
前端不用手写流解析（维护成本减半）。观感靠前端一个「本地逐字队列」补齐，与真流式无异。

## 生命周期

    创建任务 → 后台 asyncio 任务跑 Agent，事件不断 append 到 task.events
    前端每 ~400ms  拉一次 GET /agent/schedule/progress?taskId=…&from=N
    跑完 → task.done=True，事件保留 TTL 秒后回收

⚠️ 内存表：部署目标是 2 核 2G（§12.1），所以**有上限、有 TTL**，
且只保留事件文本（不保留 Agent/连接等重对象），过期即删。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.agent.chains.stream import stream_events
from app.core.logging import get_logger
from app.services.agent_service import persist_agent_trace, record_call

logger = get_logger(__name__)

__all__ = ["StreamTask", "create_task", "get_task", "run_task", "gc"]

#: 任务保留时长（秒）。够前端拉完最后一批事件即可，不必长留。
TTL_SECONDS = 300
#: 同时在册的任务上限。超了先淘汰最老的 —— 2 核 2G 上不能让内存表无限长。
MAX_TASKS = 20


@dataclass
class StreamTask:
    id: str
    user_id: int
    events: list[dict] = field(default_factory=list)
    done: bool = False
    order_id: int | None = None
    message: str = ""
    success: bool = False
    created_at: float = field(default_factory=time.time)

    def public(self, start: int) -> dict:
        """给轮询端看的切片。`_outcome` 之类的私有键绝不外传。"""
        return {
            "events": self.events[start:],
            "next": len(self.events),
            "done": self.done,
            "orderId": self.order_id,
            "message": self.message,
            "success": self.success,
        }


_TASKS: dict[str, StreamTask] = {}


def gc() -> None:
    now = time.time()
    for key in [k for k, t in _TASKS.items() if t.done and now - t.created_at > TTL_SECONDS]:
        _TASKS.pop(key, None)
    while len(_TASKS) > MAX_TASKS:
        oldest = min(_TASKS, key=lambda k: _TASKS[k].created_at)
        _TASKS.pop(oldest, None)


def create_task(user_id: int) -> StreamTask:
    gc()
    task = StreamTask(id=uuid.uuid4().hex[:16], user_id=user_id)
    _TASKS[task.id] = task
    return task


def get_task(task_id: str, user_id: int) -> StreamTask | None:
    task = _TASKS.get(task_id)
    # 归属校验：拿别人的 taskId 也不该看得到他的调度过程（可能含订单信息）
    if task is None or task.user_id != user_id:
        return None
    return task


async def run_task(
    task: StreamTask,
    *,
    text: str,
    user_id: int,
    image_context: dict[str, Any] | None = None,
    fast: bool = False,
) -> None:
    """后台跑一次调度，事件不断写进 task。

    收尾（埋点 / agent_trace 补写）与同步接口**完全一致** —— 不能因为改成流式就少做一步，
    否则「在线看得到、事后查不到」。
    """
    outcome = None
    try:
        async for ev in stream_events(
            text=text, user_id=user_id, image_context=image_context, fast=fast
        ):
            data = ev.get("data") or {}
            # _outcome 只在进程内传递，不能进缓存（不可 JSON 序列化，也不该外泄）
            if "_outcome" in data:
                outcome = data.pop("_outcome")
            task.events.append(ev)
    except Exception as exc:  # noqa: BLE001
        logger.exception("流式任务异常 task=%s", task.id)
        task.events.append(
            {"event": "error", "data": {"message": f"AI 调度异常：{type(exc).__name__}"}}
        )
    finally:
        if outcome is not None:
            task.order_id = outcome.data.orderId
            task.message = outcome.message
            task.success = outcome.success
            try:
                record_call(outcome)
                if outcome.locked_order_id:
                    await persist_agent_trace(
                        order_id=outcome.locked_order_id,
                        user_id=user_id,
                        request_text=text,
                        outcome=outcome,
                    )
            except Exception:  # noqa: BLE001 - 附加值拖垮主流程是更糟的选择
                logger.exception("流式任务收尾失败 task=%s", task.id)
        task.done = True
        task.events.append(
            {
                "event": "done",
                "data": {
                    "orderId": task.order_id,
                    "message": task.message,
                    "success": task.success,
                },
            }
        )
