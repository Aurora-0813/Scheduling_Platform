"""
事件总线：调度语义、异常隔离、载荷只读

最关键的一条：publish 不得等待订阅者。其他模块在订单创建接口里
加一行 `await bus.publish(...)`，不能因为通知要等 3~20 秒的大模型
而把业务接口拖慢。
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.core.events import EVENT_ORDER_CREATED, Event, EventBus


@pytest.fixture
def bus() -> EventBus:
    return EventBus(name="test")


# ---------- 调度语义 ----------


async def test_publish_returns_the_number_of_subscribers(bus):
    async def handler(event):
        return None

    bus.subscribe(EVENT_ORDER_CREATED, handler)
    assert await bus.publish(EVENT_ORDER_CREATED, {"orderId": 1}) == 1
    await bus.drain()


async def test_publish_without_subscribers_returns_zero(bus):
    assert await bus.publish(EVENT_ORDER_CREATED, {"orderId": 1}) == 0


async def test_publish_does_not_wait_for_a_slow_subscriber(bus):
    """★ 业务接口的耗时不能被通知推送绑架"""
    finished = asyncio.Event()

    async def slow(event):
        await asyncio.sleep(0.3)
        finished.set()

    bus.subscribe(EVENT_ORDER_CREATED, slow)

    started = time.monotonic()
    await bus.publish(EVENT_ORDER_CREATED, {"orderId": 1})
    elapsed = time.monotonic() - started

    assert elapsed < 0.1, f"publish 阻塞了 {elapsed:.2f}s，业务接口会被拖慢"
    assert not finished.is_set(), "订阅者不应在 publish 返回前就跑完"

    await bus.drain(timeout=2)
    assert finished.is_set()


async def test_two_subscribers_both_receive_the_event(bus):
    seen: list[str] = []

    async def first(event):
        seen.append("first")

    async def second(event):
        seen.append("second")

    bus.subscribe(EVENT_ORDER_CREATED, first)
    bus.subscribe(EVENT_ORDER_CREATED, second)
    assert await bus.publish(EVENT_ORDER_CREATED) == 2

    await bus.drain()
    assert sorted(seen) == ["first", "second"]


async def test_only_the_requested_event_is_delivered(bus):
    seen: list[str] = []

    async def handler(event):
        seen.append(event.name)

    bus.subscribe("order.created", handler)
    await bus.publish("device.fault", {"deviceId": 2})
    await bus.drain()

    assert seen == []


# ---------- 异常隔离 ----------


async def test_subscriber_exception_does_not_reach_the_publisher(bus):
    """★ 通知推送失败绝不能影响业务主流程"""
    ran: list[str] = []

    async def broken(event):
        ran.append("broken")
        raise RuntimeError("模拟订阅者故障")

    async def healthy(event):
        ran.append("healthy")

    bus.subscribe(EVENT_ORDER_CREATED, broken)
    bus.subscribe(EVENT_ORDER_CREATED, healthy)

    await bus.publish(EVENT_ORDER_CREATED, {"orderId": 1})
    await bus.drain()  # 不应抛出

    assert sorted(ran) == ["broken", "healthy"]


async def test_a_broken_subscriber_does_not_block_later_events(bus):
    attempts: list[int] = []

    async def broken(event):
        attempts.append(1)
        raise RuntimeError("模拟订阅者故障")

    bus.subscribe(EVENT_ORDER_CREATED, broken)

    for _ in range(3):
        await bus.publish(EVENT_ORDER_CREATED, {"orderId": 1})
        await bus.drain()

    assert len(attempts) == 3, "一次订阅者故障不应让后续事件停止投递"


async def test_sync_subscriber_is_supported(bus):
    seen: list[int] = []

    def handler(event):
        seen.append(event.payload["orderId"])

    bus.subscribe(EVENT_ORDER_CREATED, handler)
    await bus.publish(EVENT_ORDER_CREATED, {"orderId": 7})
    await bus.drain()

    assert seen == [7]


# ---------- 订阅管理 ----------


async def test_duplicate_subscription_is_ignored(bus):
    """lifespan 重启一次就多发一条通知，是很容易踩的坑"""
    calls: list[int] = []

    async def handler(event):
        calls.append(1)

    bus.subscribe(EVENT_ORDER_CREATED, handler)
    bus.subscribe(EVENT_ORDER_CREATED, handler)

    assert bus.subscriber_count(EVENT_ORDER_CREATED) == 1
    await bus.publish(EVENT_ORDER_CREATED)
    await bus.drain()
    assert calls == [1]


async def test_unsubscribe_stops_delivery(bus):
    calls: list[int] = []

    async def handler(event):
        calls.append(1)

    unsubscribe = bus.subscribe(EVENT_ORDER_CREATED, handler)
    unsubscribe()
    unsubscribe()  # 重复取消不应抛异常

    await bus.publish(EVENT_ORDER_CREATED)
    await bus.drain()
    assert calls == []


async def test_unsubscribe_all_clears_every_event(bus):
    async def handler(event):
        return None

    bus.subscribe(EVENT_ORDER_CREATED, handler)
    bus.unsubscribe_all()

    assert bus.subscriber_count(EVENT_ORDER_CREATED) == 0
    assert await bus.publish(EVENT_ORDER_CREATED) == 0


# ---------- 载荷 ----------


async def test_payload_cannot_be_mutated_by_subscribers(bus):
    async def handler(event):
        with pytest.raises(TypeError):
            event.payload["injected"] = True  # type: ignore[index]

    bus.subscribe(EVENT_ORDER_CREATED, handler)
    await bus.publish(EVENT_ORDER_CREATED, {"orderId": 1})
    await bus.drain()


async def test_payload_is_copied_at_publish_time(bus):
    """发布后调用方再改自己的 dict，不应影响已发出的事件"""
    source = {"orderId": 1}
    seen: list[int] = []

    async def handler(event):
        seen.append(event.payload["orderId"])

    bus.subscribe(EVENT_ORDER_CREATED, handler)
    await bus.publish(EVENT_ORDER_CREATED, source)
    source["orderId"] = 999
    await bus.drain()

    assert seen == [1]


async def test_event_get_accepts_either_key_style(bus):
    """载荷键名由发布方决定，驼峰与蛇形都要接住"""
    seen: list[int | None] = []

    async def handler(event):
        seen.append(event.get("orderId", "order_id"))

    bus.subscribe(EVENT_ORDER_CREATED, handler)
    await bus.publish(EVENT_ORDER_CREATED, {"order_id": 5})
    await bus.drain()

    assert seen == [5]


def test_event_get_skips_none_and_falls_back():
    event = Event(name="x", payload={"orderId": None, "order_id": 3})
    assert event.get("orderId", "order_id") == 3
    assert event.get("missing", default="兜底") == "兜底"


# ---------- 收敛 ----------


async def test_drain_waits_for_in_flight_handlers(bus):
    order: list[str] = []

    async def slow(event):
        await asyncio.sleep(0.05)
        order.append("handler")

    bus.subscribe(EVENT_ORDER_CREATED, slow)
    await bus.publish(EVENT_ORDER_CREATED)

    await bus.drain(timeout=2)
    order.append("drain")

    # handler 先入列，说明 drain 一直等到了它在途执行完
    assert order == ["handler", "drain"]


async def test_drain_cancels_handlers_that_overrun(bus):
    async def stuck(event):
        await asyncio.sleep(60)

    bus.subscribe(EVENT_ORDER_CREATED, stuck)
    await bus.publish(EVENT_ORDER_CREATED)

    started = time.monotonic()
    await bus.drain(timeout=0.05)
    assert time.monotonic() - started < 1.0

    await asyncio.sleep(0.01)
    assert bus.pending == 0, "超时未完成的任务应被取消并回收"


async def test_drain_is_a_noop_when_nothing_is_pending(bus):
    await bus.drain(timeout=1)


async def test_aclose_clears_subscribers_and_drains(bus):
    calls: list[int] = []

    async def handler(event):
        calls.append(1)

    bus.subscribe(EVENT_ORDER_CREATED, handler)
    await bus.publish(EVENT_ORDER_CREATED)
    await bus.aclose()

    assert calls == [1], "关闭时应把在途任务收敛完"
    assert bus.pending == 0
    assert await bus.publish(EVENT_ORDER_CREATED) == 0
