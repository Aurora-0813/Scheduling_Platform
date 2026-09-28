"""
业务事件 → 通知：载荷解析与受众判定

事件发布方是别的模块（预约、巡检），键名写法不完全受我们控制，
所以这里重点盯「驼峰/蛇形都要接住」与「身份字段不得混进文案」。
"""
from __future__ import annotations

import pytest

from app.core.events import (
    ALL_EVENTS,
    EVENT_DEVICE_FAULT,
    EVENT_ORDER_CANCELLED,
    EVENT_ORDER_CREATED,
    EVENT_ORDER_RESCHEDULED,
    Event,
    EventBus,
)
from app.services import notify_events
from app.services.notify_service import DispatchResult


class Recorder:
    """替换掉真正的派发函数，只记录调用参数"""

    def __init__(self, result: DispatchResult | None = None) -> None:
        self.calls: list[dict] = []
        self._result = result if result is not None else DispatchResult(created=1)

    async def __call__(self, **kwargs) -> DispatchResult:
        self.calls.append(kwargs)
        return self._result

    @property
    def last(self) -> dict:
        return self.calls[-1]


@pytest.fixture
def recorder(monkeypatch) -> Recorder:
    record = Recorder()
    monkeypatch.setattr(notify_events, "dispatch_order_notification", record)
    return record


def _event(name: str, payload: dict | None = None) -> Event:
    return Event(name=name, payload=payload or {})


# ---------- 订单事件 ----------


async def test_order_created_extracts_a_camel_case_order_id(recorder):
    await notify_events.on_order_created(
        _event(EVENT_ORDER_CREATED, {"orderId": 101, "userId": 1})
    )

    assert recorder.last["order_id"] == 101
    assert recorder.last["notify_type"] == "提醒"
    assert recorder.last["rule_code"] == "order_created"


async def test_order_created_accepts_a_snake_case_order_id(recorder):
    await notify_events.on_order_created(
        _event(EVENT_ORDER_CREATED, {"order_id": "202"})
    )

    assert recorder.last["order_id"] == 202


async def test_order_created_skips_when_the_order_id_is_missing(recorder):
    """键名对不上时宁可什么都不发，也不能猜一个订单号去打扰别人"""
    await notify_events.on_order_created(_event(EVENT_ORDER_CREATED, {"id": 9}))

    assert recorder.last["order_id"] is None


async def test_a_non_numeric_order_id_is_treated_as_absent(recorder):
    await notify_events.on_order_created(
        _event(EVENT_ORDER_CREATED, {"orderId": "abc"})
    )

    assert recorder.last["order_id"] is None


async def test_order_created_has_a_default_reason(recorder):
    await notify_events.on_order_created(_event(EVENT_ORDER_CREATED, {"orderId": 1}))

    assert recorder.last["reason"]


async def test_payload_reason_overrides_the_default(recorder):
    await notify_events.on_order_created(
        _event(EVENT_ORDER_CREATED, {"orderId": 1, "reason": "设备例行检修"})
    )

    assert recorder.last["reason"] == "设备例行检修"


async def test_identity_keys_never_reach_the_facts(recorder):
    """★ 开发流程.md 5.1：身份标识禁止从请求体（此处为事件载荷）传入"""
    await notify_events.on_order_created(
        _event(
            EVENT_ORDER_CREATED,
            {"orderId": 1, "userId": 999, "receiverId": 999, "handlerId": 999},
        )
    )

    facts = recorder.last["extra_facts"]
    assert not facts, f"身份字段混进了文案载荷：{facts}"


async def test_only_allowlisted_facts_are_forwarded(recorder):
    """整包透传会把技术字段喂给大模型，这里只放行文案相关字段"""
    await notify_events.on_order_created(
        _event(
            EVENT_ORDER_CREATED,
            {
                "orderId": 1,
                "spaceName": "A栋3楼展厅",
                "ipAddress": "10.0.0.1",
                "traceId": "abc123",
            },
        )
    )

    facts = recorder.last["extra_facts"]
    assert facts == {"spaceName": "A栋3楼展厅"}


async def test_order_cancelled_uses_the_apology_tone(recorder):
    await notify_events.on_order_cancelled(_event(EVENT_ORDER_CANCELLED, {"orderId": 5}))

    assert recorder.last["notify_type"] == "延期致歉"
    assert recorder.last["rule_code"] == "order_cancelled"


async def test_order_rescheduled_uses_the_apology_tone(recorder):
    await notify_events.on_order_rescheduled(
        _event(EVENT_ORDER_RESCHEDULED, {"orderId": 5, "reason": "场地临时占用"})
    )

    assert recorder.last["notify_type"] == "延期致歉"
    assert recorder.last["rule_code"] == "order_rescheduled"
    assert recorder.last["reason"] == "场地临时占用"


# ---------- 设备故障 ----------


async def test_device_fault_uses_the_alarm_tone_without_an_order(recorder):
    await notify_events.on_device_fault(
        _event(EVENT_DEVICE_FAULT, {"deviceId": 2, "deviceName": "无人机-1"})
    )

    assert recorder.last["order_id"] is None
    assert recorder.last["notify_type"] == "故障告警"
    assert recorder.last["extra_facts"]["deviceName"] == "无人机-1"


async def test_device_fault_uses_the_order_when_the_payload_has_one(recorder):
    """带订单号时预约人也该知道设备不可用 —— 受众由服务层按快照推导"""
    await notify_events.on_device_fault(
        _event(EVENT_DEVICE_FAULT, {"deviceId": 2, "orderId": 33})
    )

    assert recorder.last["order_id"] == 33


@pytest.mark.parametrize("key", ["reason", "faultDesc", "fault_desc", "description"])
async def test_device_fault_accepts_several_reason_keys(recorder, key):
    await notify_events.on_device_fault(
        _event(EVENT_DEVICE_FAULT, {"deviceId": 2, key: "电机异常"})
    )

    assert recorder.last["reason"] == "电机异常"


async def test_device_fault_has_a_default_reason(recorder):
    await notify_events.on_device_fault(_event(EVENT_DEVICE_FAULT, {"deviceId": 2}))

    assert recorder.last["reason"]


async def test_device_fault_cannot_forge_a_reason_from_a_boolean(recorder):
    await notify_events.on_device_fault(
        _event(EVENT_DEVICE_FAULT, {"deviceId": 2, "reason": True})
    )

    assert recorder.last["reason"] != "True"


# ---------- 订阅接线 ----------


def test_every_event_has_a_handler():
    assert set(notify_events.HANDLERS) == set(ALL_EVENTS)


async def test_subscribe_registers_all_handlers():
    bus = EventBus(name="t")
    unsubscribes = notify_events.subscribe_notify_events(bus)

    assert len(unsubscribes) == len(ALL_EVENTS)
    for name in ALL_EVENTS:
        assert bus.subscriber_count(name) == 1


async def test_subscribing_twice_does_not_double_deliver(recorder):
    """lifespan 重启一次就发两条通知，是必须防住的"""
    bus = EventBus(name="t")
    notify_events.subscribe_notify_events(bus)
    notify_events.subscribe_notify_events(bus)

    assert bus.subscriber_count(EVENT_ORDER_CREATED) == 1


async def test_a_published_event_reaches_the_dispatch_service(recorder):
    """端到端：总线 → 订阅者 → 服务层（服务层已被替换）"""
    bus = EventBus(name="t")
    notify_events.subscribe_notify_events(bus)

    await bus.publish(EVENT_ORDER_CREATED, {"orderId": 77})
    await bus.drain()

    assert recorder.last["order_id"] == 77


async def test_handler_failure_is_swallowed_by_the_bus(monkeypatch):
    async def broken(**kwargs):
        raise RuntimeError("模拟通知服务故障")

    monkeypatch.setattr(notify_events, "dispatch_order_notification", broken)

    bus = EventBus(name="t")
    notify_events.subscribe_notify_events(bus)

    await bus.publish(EVENT_ORDER_CREATED, {"orderId": 1})
    await bus.drain()  # 不应抛出 —— 通知失败不得影响业务主流程
