"""
进程内异步事件总线

作用：把业务侧已经发生的事实（订单创建/取消/改期、设备故障）转成本模块的通知推送。

为什么不用消息队列：开发流程.md 12.1 的部署目标是单机 2 核 2G，
Uvicorn 默认单 worker，进程内总线零依赖且够用；引入 RabbitMQ/Kafka
只会增加部署与运维负担，与本模块「不引入新技术栈」的约束一致。

两条硬约束：

1. **publish 不阻塞业务接口**。订单创建接口加一行 `await bus.publish(...)` 之后，
   不应因为通知要等 3~20 秒的大模型而变慢，因此 publish 只把订阅者
   调度成后台任务即返回，真正的等待由 drain() 在应用关闭时收敛。
2. **订阅者异常一律吞掉**。通知推送失败绝不能影响业务主流程
   （开发流程.md 4.2 / 13.1：AI 与通知链路可降级，业务链路不中断）。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any

logger = logging.getLogger(__name__)

# ---------- 事件名 ----------
# 其他模块只需按这些常量发布事件，不需要知道通知是怎么发出去的
EVENT_ORDER_CREATED = "order.created"
EVENT_ORDER_CANCELLED = "order.cancelled"
EVENT_ORDER_RESCHEDULED = "order.rescheduled"
EVENT_DEVICE_FAULT = "device.fault"

ALL_EVENTS: tuple[str, ...] = (
    EVENT_ORDER_CREATED,
    EVENT_ORDER_CANCELLED,
    EVENT_ORDER_RESCHEDULED,
    EVENT_DEVICE_FAULT,
)

Handler = Callable[["Event"], Any]
Unsubscribe = Callable[[], None]


@dataclass(frozen=True, slots=True)
class Event:
    """一次事件。载荷只读 —— 订阅者不得修改别人发出的事实"""

    name: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=datetime.now)

    def get(self, *keys: str, default: Any = None) -> Any:
        """
        按候选键依次取值，兼容驼峰与蛇形两种写法。

        其他模块的载荷键名由各自作者决定，本模块做双向容错，
        避免联调期为了一个键名互相等待。
        """
        for key in keys:
            if key in self.payload:
                value = self.payload[key]
                if value is not None:
                    return value
        return default


class EventBus:
    """
    极简异步事件总线。

    订阅者可以是协程函数，也可以是普通函数；两者都在后台任务里执行。
    """

    def __init__(self, *, name: str = "bus") -> None:
        self._name = name
        self._subscribers: dict[str, list[Handler]] = {}
        self._tasks: set[asyncio.Task] = set()

    # ---------- 订阅 ----------

    def subscribe(self, event_name: str, handler: Handler) -> Unsubscribe:
        """
        注册订阅者，返回取消订阅的回调。

        重复注册同一个函数会被忽略 —— 否则 lifespan 重启一次就多发一条通知。
        """
        handlers = self._subscribers.setdefault(event_name, [])
        if handler not in handlers:
            handlers.append(handler)

        def _unsubscribe() -> None:
            try:
                handlers.remove(handler)
            except ValueError:  # 已被取消过
                pass

        return _unsubscribe

    def unsubscribe_all(self, event_name: str | None = None) -> None:
        if event_name is None:
            self._subscribers.clear()
        else:
            self._subscribers.pop(event_name, None)

    def subscriber_count(self, event_name: str) -> int:
        return len(self._subscribers.get(event_name, ()))

    @property
    def pending(self) -> int:
        """在途（尚未执行完）的订阅者任务数"""
        return len(self._tasks)

    # ---------- 发布 ----------

    async def publish(
        self, event_name: str, payload: Mapping[str, Any] | None = None
    ) -> int:
        """
        发布事件，返回被调度的订阅者数量。

        订阅者在后台任务中执行，本方法**不等待**它们完成 ——
        业务接口不应为通知推送的耗时买单。
        """
        handlers = list(self._subscribers.get(event_name, ()))
        if not handlers:
            return 0

        event = Event(name=event_name, payload=MappingProxyType(dict(payload or {})))
        loop = asyncio.get_running_loop()

        scheduled = 0
        for handler in handlers:
            task = loop.create_task(
                self._invoke(handler, event),
                name=f"{self._name}:{event_name}:{getattr(handler, '__name__', 'handler')}",
            )
            # 持有强引用，避免任务在完成前被垃圾回收
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            scheduled += 1
        return scheduled

    @staticmethod
    async def _invoke(handler: Handler, event: Event) -> None:
        try:
            result = handler(event)
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 —— 订阅者故障不得影响发布方
            logger.exception("事件订阅者执行失败：%s", event.name)

    # ---------- 收敛 ----------

    async def drain(self, timeout: float | None = None) -> None:
        """
        等待在途任务结束（应用关闭时调用）。

        超时未完成的任务会被取消并记日志，绝不无限期挂着。
        """
        pending = [task for task in self._tasks if not task.done()]
        if not pending:
            return
        _, still_running = await asyncio.wait(pending, timeout=timeout)
        if not still_running:
            return
        logger.warning("事件总线仍有 %d 个订阅者任务未完成，已取消", len(still_running))
        for task in still_running:
            task.cancel()

    async def aclose(self, timeout: float | None = 5.0) -> None:
        await self.drain(timeout=timeout)
        self._subscribers.clear()


# 全局总线实例。
# 事件发布方 `from app.core.events import bus` 即可，无需注入。
bus = EventBus()
