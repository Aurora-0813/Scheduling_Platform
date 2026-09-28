"""
冲突扫描编排服务

扫描任务被刻意切成四段：

    段1 短事务读快照 → 段2 无 session 调 AI 富化 → 段3 无 session 跑纯函数规则 → 段4 短事务写库

原因是**绝不能在持有数据库连接时调用大模型**：一次调用 3~20 秒，
连接池会被瞬间占死，而部署目标只有 2 核 2G（开发流程.md 12.1）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.chains.extract_chain import extract_attendee_count
from app.agent.chains.llm import build_llm
from app.core.config import settings
from app.core.database import session_scope
from app.models.notification import NOTIFY_TYPE_REMIND
from app.models.reservation import ReserveOrder
from app.models.resource import DeviceResource, SpaceResource
from app.models.system import SysRole, SysUser
from app.schemas.conflict import CONFLICT_TYPE_SOFT, ConflictItem
from app.services.dedup import Dedup, build_dedup
from app.services.notify_service import (
    DispatchResult,
    generate_and_dispatch,
    resolve_recipients,
)
from app.services.rules.base import (
    ACTIVE_ORDER_STATUSES,
    ConflictRuleConfig,
    DeviceView,
    HISTORY_ORDER_STATUSES,
    OrderView,
    RuleContext,
    RuleHit,
    SpaceView,
    UserView,
)
from app.services.rules.registry import run_all

logger = logging.getLogger(__name__)

# 单轮扫描最多为多少笔订单调用大模型抽取人数。
# 这是成本护栏而非业务阈值，故不进 .env：富化按开始时间就近优先，
# 超出部分留待下一轮，扫描窗口内的订单最多几轮就能全部富化完。
MAX_ENRICH_ORDERS = 20

# 每条规则内置的处置建议。
#
# 为什么不让 AI 逐条生成建议：GET /conflicts/scan 是看板轮询的只读接口，
# 一次请求可能命中十几条冲突，逐条调大模型会让接口从毫秒级变成几十秒级。
# AI 生成的正式文案走 POST /notify/generate 与定时推送。
SUGGESTIONS: dict[str, str] = {
    "continuous_activity": (
        "建议将后一场活动延后至少 15 分钟，或改到同一场地连排，"
        "为预约人留出转场与休息时间。"
    ),
    "capacity_overflow": (
        "建议改约容量更匹配的场地，或缩短占用时长，"
        "把大空间让给确有需要的团队。"
    ),
    "high_value_device_low_priority": (
        "建议管理员复核该设备的分配优先级，必要时与预约人协商调整使用时段。"
    ),
    "space_overuse": (
        "建议与预约方沟通，将部分活动分流到其他场地，避免单日被长时间垄断。"
    ),
    "space_idle": (
        "建议评估该场地的配置与开放时段，或通过内部宣传提升使用率。"
    ),
}

DEFAULT_SUGGESTION = "建议管理员复核该预约的资源分配情况。"


@dataclass(frozen=True, slots=True)
class ScanSummary:
    """一轮扫描的结果计数，供定时任务日志与接口断言"""

    scanned_orders: int = 0
    hits: int = 0
    enriched: int = 0
    created: int = 0
    skipped: int = 0
    failed: int = 0


# ---------- 段1：读快照 ----------


async def load_rule_context(
    session: AsyncSession, *, now: datetime | None = None
) -> RuleContext:
    """
    用一个短事务读出规则引擎所需的全部快照。

    固定 5 条查询，不做 N+1：
    1. 窗口内的有效订单（带 LIMIT 保护内存）
    2. 场地种子数据
    3. 设备种子数据
    4. 用户 ⋈ 角色
    5. 各场地最后一次有效预约的结束时间（闲置判定用，窗口外也需要）
    """
    moment = now or datetime.now()
    window_start = moment - timedelta(days=settings.CONFLICT_PAST_WINDOW_DAYS)
    window_end = moment + timedelta(days=settings.CONFLICT_FUTURE_WINDOW_DAYS)

    # ① 订单：与窗口有交集且未被取消
    order_stmt = (
        select(
            ReserveOrder.id,
            ReserveOrder.user_id,
            ReserveOrder.space_id,
            ReserveOrder.start_time,
            ReserveOrder.end_time,
            ReserveOrder.order_status,
            ReserveOrder.device_ids,
            ReserveOrder.agent_request,
        )
        .where(
            ReserveOrder.order_status.in_(ACTIVE_ORDER_STATUSES),
            ReserveOrder.end_time >= window_start,
            ReserveOrder.start_time <= window_end,
        )
        .order_by(ReserveOrder.start_time, ReserveOrder.id)
        .limit(settings.CONFLICT_MAX_ORDERS_IN_SNAPSHOT)
    )
    order_rows = (await session.execute(order_stmt)).all()

    orders: list[OrderView] = []
    for row in order_rows:
        raw_devices = row[6]
        if isinstance(raw_devices, (list, tuple)):
            device_ids = tuple(int(d) for d in raw_devices if d is not None)
        else:
            device_ids = ()
        orders.append(
            OrderView(
                id=int(row[0]),
                user_id=int(row[1]),
                space_id=int(row[2]),
                start_time=row[3],
                end_time=row[4],
                order_status=int(row[5]),
                device_ids=device_ids,
                agent_request=row[7],
            )
        )

    # ② 场地
    space_rows = (
        await session.execute(
            select(
                SpaceResource.id,
                SpaceResource.space_name,
                SpaceResource.space_type,
                SpaceResource.capacity,
                SpaceResource.status,
            )
        )
    ).all()
    spaces = {
        int(r[0]): SpaceView(
            id=int(r[0]),
            space_name=r[1] or f"场地#{r[0]}",
            space_type=int(r[2] or 1),
            capacity=int(r[3] or 0),
            status=int(r[4] if r[4] is not None else 1),
        )
        for r in space_rows
    }

    # ③ 设备
    device_rows = (
        await session.execute(
            select(
                DeviceResource.id,
                DeviceResource.device_name,
                DeviceResource.device_type,
                DeviceResource.device_status,
            )
        )
    ).all()
    devices = {
        int(r[0]): DeviceView(
            id=int(r[0]),
            device_name=r[1] or f"设备#{r[0]}",
            device_type=r[2],
            device_status=int(r[3] if r[3] is not None else 1),
        )
        for r in device_rows
    }

    # ④ 用户 ⋈ 角色（显式 JOIN，不用 relationship 惰性加载）
    user_rows = (
        await session.execute(
            select(SysUser.id, SysUser.username, SysUser.role_id, SysRole.role_name)
            .join(SysRole, SysRole.id == SysUser.role_id, isouter=True)
        )
    ).all()
    users = {
        int(r[0]): UserView(
            id=int(r[0]),
            username=r[1] or f"用户#{r[0]}",
            role_id=int(r[2]) if r[2] is not None else None,
            role_name=r[3],
        )
        for r in user_rows
    }

    # ⑤ 各场地最后一次有效预约的结束时间。
    # 扫描窗口默认 ±7 天，闲置判定默认 14 天，仅靠窗口内订单会误判，故单独聚合。
    # 这里刻意用 HISTORY 口径（含已完成）：问的是「场地最近被用过吗」，
    # 用前瞻口径会把已完成的历史预约全部丢掉，导致场地被误判为长期闲置。
    last_rows = (
        await session.execute(
            select(ReserveOrder.space_id, func.max(ReserveOrder.end_time))
            .where(ReserveOrder.order_status.in_(HISTORY_ORDER_STATUSES))
            .group_by(ReserveOrder.space_id)
        )
    ).all()
    space_last_order_at = {
        int(r[0]): r[1] for r in last_rows if r[0] is not None and r[1] is not None
    }

    return RuleContext(
        orders=tuple(orders),
        spaces=spaces,
        devices=devices,
        users=users,
        now=moment,
        config=ConflictRuleConfig.from_settings(),
        space_last_order_at=space_last_order_at,
    )


# ---------- 段2：AI 富化（不持有 session） ----------


async def enrich_attendees(
    ctx: RuleContext, *, llm: Any = None, timeout: float | None = None
) -> tuple[RuleContext, int]:
    """
    用 AI 从订单原始需求文本中抽取参会人数，回填到快照。

    只对**尚未结束**的订单富化：已结束的预约再提醒「容量浪费」没有意义，
    既打扰用户也白烧 token。

    任何单笔抽取失败都静默跳过 —— 抽不到就跳过该规则，绝不猜测。
    本函数不接收 session，调用方必须保证它不在数据库事务内执行。
    """
    candidates = [
        order
        for order in ctx.orders
        if order.attendee_count is None
        and order.agent_request
        and order.end_time >= ctx.now
    ]
    if not candidates:
        return ctx, 0

    candidates.sort(key=lambda o: (o.start_time, o.id))
    selected = candidates[:MAX_ENRICH_ORDERS]

    model = llm
    if model is None and settings.AI_ENABLED:
        model = build_llm()

    filled: dict[int, int] = {}
    for order in selected:
        try:
            count = await extract_attendee_count(
                order.agent_request, llm=model, timeout=timeout
            )
        except Exception:  # noqa: BLE001 —— 抽取链自身已降级，这里是最后一道保险
            logger.exception("参会人数抽取异常，跳过订单 %s", order.id)
            continue
        if count is not None:
            filled[order.id] = count

    if not filled:
        return ctx, 0

    enriched_orders = tuple(
        replace(order, attendee_count=filled[order.id])
        if order.id in filled
        else order
        for order in ctx.orders
    )
    return replace(ctx, orders=enriched_orders), len(filled)


# ---------- 段3：跑规则（纯函数） ----------


def suggest_for(hit: RuleHit) -> str:
    """按规则给出确定性处置建议"""
    return SUGGESTIONS.get(hit.rule_code, DEFAULT_SUGGESTION)


def build_conflict_items(hits: list[RuleHit]) -> list[ConflictItem]:
    """
    把规则命中转成契约响应项。

    字段恰好是 conflictType / orderIds / suggestion / ruleCode ——
    CamelModel 负责蛇形到驼峰的转换，改动字段名会破坏前端契约。
    """
    return [
        ConflictItem(
            conflict_type=CONFLICT_TYPE_SOFT,
            order_ids=list(hit.order_ids),
            suggestion=suggest_for(hit),
            rule_code=hit.rule_code,
        )
        for hit in hits
    ]


# ---------- 段4：写库 ----------


async def persist_conflict_notifications(
    session: AsyncSession,
    hits: list[RuleHit],
    *,
    dedup: Dedup,
    llm: Any = None,
    timeout: float | None = None,
) -> DispatchResult:
    """
    把规则命中转成通知并落库（本模块只写 notify_message）。

    软冲突统一落 notify_type=1 预约提醒：表只定义了 3 类，
    资源占用与闲置属于提醒语义，真正的变更致歉由业务事件触发。
    """
    total = DispatchResult()
    if not hits:
        return total

    model = llm
    if model is None and settings.AI_ENABLED:
        model = build_llm()

    for hit in hits:
        recipients = await resolve_recipients(
            session, audience=hit.audience, owner_id=hit.user_id
        )
        if not recipients:
            logger.warning("冲突 %s 未解析到收件人，已跳过", hit.rule_code)
            continue

        result = await generate_and_dispatch(
            session=session,
            recipients=recipients,
            dedup=dedup,
            notify_type=NOTIFY_TYPE_REMIND,
            facts=hit.facts,
            rule_code=hit.rule_code,
            rule_label=hit.rule_label,
            reason=hit.reason,
            order_ids=hit.order_ids,
            space_id=hit.space_id,
            order_id=hit.order_ids[0] if hit.order_ids else None,
            llm=model,
            timeout=timeout,
            source="scan",
        )
        total = total.merge(result)

    return total


# ---------- 定时任务入口 ----------


async def scan_and_notify_job(
    *, llm: Any = None, now: datetime | None = None
) -> ScanSummary:
    """
    一轮完整的扫描与推送。

    段1/段4 各自开一个短事务，段2/段3 不持有任何数据库连接。
    """
    moment = now or datetime.now()

    # 段1：读快照（短事务）
    async with session_scope() as session:
        ctx = await load_rule_context(session, now=moment)

    # 段2：AI 富化（无 session）
    ctx, enriched = await enrich_attendees(ctx, llm=llm)

    # 段3：跑纯函数规则（无 session）
    hits = run_all(ctx)

    summary = ScanSummary(
        scanned_orders=len(ctx.orders), hits=len(hits), enriched=enriched
    )
    if not hits:
        return summary

    # 段4：写库（短事务）
    async with session_scope() as session:
        dedup = build_dedup(session)
        try:
            result = await persist_conflict_notifications(
                session, hits, dedup=dedup, llm=llm
            )
            await session.commit()
        finally:
            await dedup.aclose()

    return replace(
        summary,
        created=result.created,
        skipped=result.skipped,
        failed=result.failed,
    )
