"""
业务事件 → 通知推送

对接方式（开发流程.md 2.5）：其他模块在自己的业务事务**提交之后**加一行

    from app.core.events import EVENT_ORDER_CREATED, bus
    await bus.publish(EVENT_ORDER_CREATED, {"orderId": order.id, "userId": order.user_id})

即使一行都没加，`GET /api/v1/conflicts/scan` 与周期扫描仍完整可用 ——
本模块不因外部未接线而不可演示。

载荷键名做驼峰/蛇形双向容错：约定的是 orderId，对方写成 order_id 也能跑。
身份标识（userId 等）在载荷里出现也会被忽略 —— 收件人只由订单事实推导，
见 notify_service.build_order_facts 的 PAYLOAD_IGNORED_KEYS。
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from app.core.events import (
    EVENT_DEVICE_FAULT,
    EVENT_ORDER_CANCELLED,
    EVENT_ORDER_CREATED,
    EVENT_ORDER_RESCHEDULED,
    Event,
    EventBus,
    Unsubscribe,
)
from app.services.notify_service import DispatchResult, dispatch_order_notification

logger = logging.getLogger(__name__)

# 事件载荷里可能表示订单ID的键（按优先级尝试）
_ORDER_KEYS: tuple[str, ...] = (
    "orderId",
    "order_id",
    "reserveOrderId",
    "reserve_order_id",
)

# 允许进入文案的载荷键白名单。
# 不做整包透传：载荷里的身份字段与技术字段不该混进给用户看的文案。
_FACT_KEYS: tuple[str, ...] = (
    "spaceName",
    "space_name",
    "userName",
    "user_name",
    "deviceName",
    "device_name",
    "deviceType",
    "device_type",
    "ruleLabel",
    "rule_label",
    "suggestion",
    "reason",
)


# ---------- 载荷解析 ----------


def _as_int(event: Event, keys: tuple[str, ...]) -> int | None:
    raw = event.get(*keys)
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("事件 %s 的载荷字段不是合法整数：%r", event.name, raw)
        return None


def _as_text(event: Event, *keys: str) -> str | None:
    """取文本型载荷字段，空串视为没有"""
    for key in keys:
        value = event.payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, (dict, list, bool)):
            return str(value)
    return None


def _extra_facts(event: Event) -> dict[str, Any]:
    """从载荷里挑出可进文案的事实字段"""
    return {
        key: value
        for key, value in event.payload.items()
        if key in _FACT_KEYS and value is not None
    }


def _order_facts(event: Event) -> dict[str, Any]:
    facts = _extra_facts(event)
    facts.pop("reason", None)  # reason 单独走参数，避免一处填两遍
    return facts


# ---------- 订阅者 ----------


async def on_order_created(event: Event) -> DispatchResult:
    """订单创建 → 给预约人与管理员发预约提醒"""
    return await dispatch_order_notification(
        order_id=_as_int(event, _ORDER_KEYS),
        notify_type="提醒",
        rule_code="order_created",
        rule_label="预约成功提醒",
        reason=_as_text(event, "reason", "remark", "suggestion")
        or "预约已创建，请按时到场使用。",
        extra_facts=_order_facts(event),
    )


async def on_order_cancelled(event: Event) -> DispatchResult:
    """订单取消 → 致歉类文案（表只定义了三类通知，变更归入 2 变更致歉）"""
    return await dispatch_order_notification(
        order_id=_as_int(event, _ORDER_KEYS),
        notify_type="延期致歉",
        rule_code="order_cancelled",
        rule_label="预约取消致歉",
        reason=_as_text(event, "reason", "remark", "suggestion") or "该预约已取消。",
        extra_facts=_order_facts(event),
    )


async def on_order_rescheduled(event: Event) -> DispatchResult:
    """订单改期 → 致歉 + 新的时间安排"""
    return await dispatch_order_notification(
        order_id=_as_int(event, _ORDER_KEYS),
        notify_type="延期致歉",
        rule_code="order_rescheduled",
        rule_label="预约改期致歉",
        reason=_as_text(event, "reason", "remark", "suggestion")
        or "该预约的时间已调整。",
        extra_facts=_order_facts(event),
    )


async def on_device_fault(event: Event) -> DispatchResult:
    """
    设备故障 → 故障告警。

    载荷里带 orderId 时会一并通知预约人（他需要提前知道设备不可用），
    不带则只通知管理员 —— 现场排障是管理侧的职责。
    """
    return await dispatch_order_notification(
        order_id=_as_int(event, _ORDER_KEYS),
        notify_type="故障告警",
        rule_code="device_fault",
        rule_label="设备故障告警",
        reason=_as_text(event, "reason", "faultDesc", "fault_desc", "description")
        or "设备上报异常，正在处理中。",
        extra_facts=_order_facts(event),
    )


# 事件名 → 订阅者
HANDLERS: Mapping[str, Any] = {
    EVENT_ORDER_CREATED: on_order_created,
    EVENT_ORDER_CANCELLED: on_order_cancelled,
    EVENT_ORDER_RESCHEDULED: on_order_rescheduled,
    EVENT_DEVICE_FAULT: on_device_fault,
}


def subscribe_notify_events(bus: EventBus) -> list[Unsubscribe]:
    """
    把本模块的订阅者挂到总线上（应用启动时调用一次）。

    重复调用是安全的：EventBus 会忽略同一个函数的重复注册。
    """
    unsubscribes = [
        bus.subscribe(event_name, handler) for event_name, handler in HANDLERS.items()
    ]
    logger.info("通知事件订阅完成：%s", "、".join(HANDLERS))
    return unsubscribes
