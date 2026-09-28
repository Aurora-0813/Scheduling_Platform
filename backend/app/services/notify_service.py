"""
通知服务层

职责：
1. 解析收件人（预约人 + 全体管理员），并按角色给出不同语气
2. 组装通知事实载荷（与规则引擎共用同一套 facts 词表）
3. 去重 → 生成文案 → 写入 notify_message

三条边界：
- 本模块只写 notify_message，reserve_order 全程只读
- 收件人一律来自数据库，绝不采信请求体里的 userId/receiverId
- 去重占位先于文案生成：被判重压掉的通知不该白烧一次 token。
  代价是从「占位」到「写入」这一步始终处在调用方的短事务内，
  因此调用方必须保证同一时刻只跑一个写库段（定时任务串行、事件总线逐个派发），
  不得并发发起多轮扫描 —— 否则大模型耗时会与数据库连接互相拖累。
"""
from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.chains.notify_chain import NotifyDraft, generate_notify_content
from app.agent.prompts.notify_templates import (
    ROLE_OWNER,
    ROLE_RESOURCE_ADMIN,
    ROLE_SYSTEM_ADMIN,
    ToneSpec,
    render_fallback,
    resolve_tone,
)
from app.core.config import settings
from app.core.database import session_scope
from app.core.response import ApiError
from app.models.notification import NotifyMessage
from app.models.reservation import ReserveOrder
from app.models.resource import SpaceResource
from app.models.system import SysRole, SysUser
from app.services.dedup import Dedup, DedupKey, build_dedup
from app.services.rules.base import AUDIENCE_OWNER_AND_ADMIN, normalize_token

logger = logging.getLogger(__name__)

# 请求体里出现这些键一律忽略：身份与收件人只能来自 JWT 与数据库
# （开发流程.md 5.1 禁止从请求体传入身份标识，防止身份伪造）
PAYLOAD_IGNORED_KEYS: frozenset[str] = frozenset(
    {
        # 驼峰与蛇形都列上：载荷键名会先经 to_snake_key 归一化再比对
        "userId", "user_id",
        "receiverId", "receiver_id",
        "notifyType", "notify_type", "type",
        "handlerId", "handler_id",
        "inspectorId", "inspector_id",
    }
)


@dataclass(frozen=True, slots=True)
class Recipient:
    """一个通知收件人及其语气角色"""

    user_id: int
    username: str
    role_key: str
    role_name: str | None = None


@dataclass(frozen=True, slots=True)
class OrderSnapshot:
    """
    订单快照（通知路径专用）。

    与规则引擎的 OrderView 分开：OrderView 服务于规则判定，
    这里额外带上场地名与容量等文案所需字段。
    """

    id: int
    user_id: int
    space_id: int
    start_time: datetime
    end_time: datetime
    order_status: int
    user_name: str | None = None
    user_role_name: str | None = None
    space_name: str | None = None
    capacity: int | None = None
    device_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """一次派发的结果计数，便于定时任务汇总与断言"""

    created: int = 0
    skipped: int = 0
    failed: int = 0
    drafts: Mapping[str, NotifyDraft] = field(default_factory=dict)

    @property
    def targeted(self) -> int:
        """本次尝试触达的收件人总数"""
        return self.created + self.skipped + self.failed

    def merge(self, other: DispatchResult) -> DispatchResult:
        return DispatchResult(
            created=self.created + other.created,
            skipped=self.skipped + other.skipped,
            failed=self.failed + other.failed,
            drafts={**self.drafts, **other.drafts},
        )


# ---------- 角色语气 ----------


def is_normal_role(role_name: str | None) -> bool:
    """是否为「普通使用者」角色。角色未知时返回 False（不假定其为管理员）"""
    if not role_name:
        return False
    return normalize_token(role_name) in {
        normalize_token(r) for r in settings.normal_role_names
    }


def role_key_for(role_name: str | None) -> str:
    """
    把角色名映射到语气角色。

    - 普通使用者 / 角色未知 → 预约人视角（最保守，不会对普通用户讲管理口径）
    - 系统管理员 → 系统管理员视角
    - 其余（资源管理员及其他运维角色）→ 资源管理员视角
    """
    if not role_name or is_normal_role(role_name):
        return ROLE_OWNER
    token = normalize_token(role_name)
    if "系统" in token:
        return ROLE_SYSTEM_ADMIN
    return ROLE_RESOURCE_ADMIN


# ---------- 数据库读取 ----------


async def load_recipient(session: AsyncSession, user_id: int) -> Recipient | None:
    """按用户ID取收件人（含角色名），用户不存在返回 None"""
    stmt = (
        select(SysUser.id, SysUser.username, SysRole.role_name)
        .join(SysRole, SysRole.id == SysUser.role_id, isouter=True)
        .where(SysUser.id == user_id)
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    return Recipient(
        user_id=int(row[0]),
        username=row[1] or f"用户#{row[0]}",
        role_name=row[2],
        role_key=role_key_for(row[2]),
    )


async def load_admin_recipients(session: AsyncSession) -> list[Recipient]:
    """
    取全部启用的管理员账号（角色不是普通使用者）。

    只读 sys_user ⋈ sys_role 一条 JOIN 查询，不做 N+1。
    """
    stmt = (
        select(SysUser.id, SysUser.username, SysRole.role_name)
        .join(SysRole, SysRole.id == SysUser.role_id, isouter=True)
        .where(SysUser.status == 1)
    )
    rows = (await session.execute(stmt)).all()

    recipients: list[Recipient] = []
    for row in rows:
        role_name = row[2]
        # 角色为空的账号无法确认是管理员，不进管理侧通知，避免误打扰
        if not role_name or is_normal_role(role_name):
            continue
        recipients.append(
            Recipient(
                user_id=int(row[0]),
                username=row[1] or f"用户#{row[0]}",
                role_name=role_name,
                role_key=role_key_for(role_name),
            )
        )
    return recipients


async def load_order_snapshot(
    session: AsyncSession, order_id: int
) -> OrderSnapshot | None:
    """
    按订单ID取文案所需的订单事实。

    一条 JOIN 查询同时取回预约人、角色、场地名与容量，
    绝不惰性加载（开发流程.md 3.5：异步会话下 relationship 惰性加载会抛 MissingGreenlet）。
    """
    stmt = (
        select(
            ReserveOrder.id,
            ReserveOrder.user_id,
            ReserveOrder.space_id,
            ReserveOrder.start_time,
            ReserveOrder.end_time,
            ReserveOrder.order_status,
            ReserveOrder.device_ids,
            SysUser.username,
            SysRole.role_name,
            SpaceResource.space_name,
            SpaceResource.capacity,
        )
        .join(SysUser, SysUser.id == ReserveOrder.user_id, isouter=True)
        .join(SysRole, SysRole.id == SysUser.role_id, isouter=True)
        .join(SpaceResource, SpaceResource.id == ReserveOrder.space_id, isouter=True)
        .where(ReserveOrder.id == order_id)
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None

    device_ids = row[6]
    if isinstance(device_ids, (list, tuple)):
        normalized_devices = tuple(int(d) for d in device_ids if d is not None)
    else:
        normalized_devices = ()

    return OrderSnapshot(
        id=int(row[0]),
        user_id=int(row[1]),
        space_id=int(row[2]),
        start_time=row[3],
        end_time=row[4],
        order_status=int(row[5]),
        device_ids=normalized_devices,
        user_name=row[7],
        user_role_name=row[8],
        space_name=row[9],
        capacity=row[10],
    )


async def resolve_recipients(
    session: AsyncSession,
    *,
    audience: frozenset[str],
    owner_id: int | None,
    admin_only: frozenset[str] | None = None,
) -> list[Recipient]:
    """
    按受众范围解析收件人列表。

    audience 里含 'owner' 时加入预约人本人；含 'admin' 时加入全部管理员。
    同一个用户只保留一条（管理员自己预约时不应收到两遍）。
    """
    from app.services.rules.base import AUDIENCE_ADMIN, AUDIENCE_OWNER

    recipients: list[Recipient] = []
    seen: set[int] = set()

    if AUDIENCE_OWNER in audience and owner_id is not None:
        owner = await load_recipient(session, owner_id)
        if owner is not None:
            recipients.append(owner)
            seen.add(owner.user_id)

    if AUDIENCE_ADMIN in audience:
        for admin in await load_admin_recipients(session):
            if admin.user_id in seen:
                continue
            recipients.append(admin)
            seen.add(admin.user_id)

    return recipients


# ---------- 事实载荷 ----------


_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def to_snake_key(key: str) -> str:
    """
    把契约载荷的驼峰键名规范成模板占位符用的蛇形键名。

    没有这一步，前端按契约传的 spaceName / ruleLabel / deviceName
    一个都填不进模板占位符，生成出来的文案会缺字段。
    """
    if "_" in key or not key.isascii():
        return key
    return _CAMEL_BOUNDARY.sub("_", key).lower()


def build_order_facts(
    snapshot: OrderSnapshot | None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    组装通知事实。

    词表与规则引擎的 facts 保持一致，这样模板与 Prompt 两条路径共用一套占位符。
    优先级：数据库事实 > 请求载荷。数据库里有的一律以库为准，
    避免请求体传入错误的场地名后被 AI 写进正式通知。
    """
    facts: dict[str, Any] = {}

    if snapshot is not None:
        facts.update(
            {
                "order_id": snapshot.id,
                "order_ids_text": str(snapshot.id),
                "user_name": snapshot.user_name or f"用户#{snapshot.user_id}",
                "user_role": snapshot.user_role_name or "普通使用者",
                "space_name": snapshot.space_name or f"场地#{snapshot.space_id}",
                "start_time": _fmt(snapshot.start_time),
                "end_time": _fmt(snapshot.end_time),
                "start_hm": _fmt(snapshot.start_time, with_date=False),
                "date": snapshot.start_time.strftime("%Y-%m-%d")
                if snapshot.start_time
                else "",
            }
        )
        if snapshot.capacity is not None:
            facts["capacity"] = snapshot.capacity

    if extra:
        for raw_key, value in extra.items():
            if value is None:
                continue
            key = to_snake_key(str(raw_key))
            if key in PAYLOAD_IGNORED_KEYS:
                continue
            # 数据库已提供的事实不被载荷覆盖
            if key in facts:
                continue
            facts[key] = value

    return facts


def _fmt(value: datetime | None, *, with_date: bool = True) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M" if with_date else "%H:%M")


# ---------- 派发 ----------


async def generate_and_dispatch(
    *,
    session: AsyncSession,
    recipients: Sequence[Recipient],
    dedup: Dedup,
    notify_type: str | int,
    facts: Mapping[str, Any],
    rule_code: str,
    rule_label: str | None = None,
    reason: str | None = None,
    order_ids: Sequence[int] = (),
    space_id: int | None = None,
    order_id: int | None = None,
    llm: Any = None,
    timeout: float | None = None,
    source: str = "scan",
    precomputed: Mapping[str, NotifyDraft] | None = None,
) -> DispatchResult:
    """
    为一组收件人生成并写入通知。

    同一语气角色的多个收件人共用一次大模型调用 ——
    否则「100 个管理员」会变成 100 次 API 调用，在 2 核 2G 上不可接受。

    去重占位发生在生成之前：被判重压掉的通知不该白烧一次 token。
    模板标题（而非 AI 标题）参与判重，因为它是确定性的、可提前算出的。

    :param precomputed: 已生成好的 {语气角色: 文案}。接口层需要把
        调用方视角的文案直接返回给前端，把那一份预生成结果传进来即可，
        避免同一角色被调用两次模型。
    """
    if not recipients:
        return DispatchResult()

    tone: ToneSpec = resolve_tone(notify_type)

    by_role: dict[str, list[Recipient]] = {}
    for recipient in recipients:
        by_role.setdefault(recipient.role_key, []).append(recipient)

    created = skipped = failed = 0
    drafts: dict[str, NotifyDraft] = {}

    for role_key, group in by_role.items():
        template_title, _ = render_fallback(tone, role_key, facts)

        pending: list[tuple[Recipient, DedupKey]] = []
        for recipient in group:
            key = DedupKey(
                receiver_id=recipient.user_id,
                notify_type=tone.notify_type,
                rule_code=rule_code,
                template_title=template_title,
                order_ids=tuple(order_ids),
                space_id=space_id,
                source=source,
            )
            if await dedup.claim(key):
                pending.append((recipient, key))
            else:
                skipped += 1

        if not pending:
            continue

        draft = precomputed.get(role_key) if precomputed else None
        if draft is None:
            draft = await generate_notify_content(
                notify_type=notify_type,
                facts=facts,
                recipient_role=role_key,
                rule_label=rule_label,
                reason=reason,
                llm=llm,
                timeout=timeout,
            )
        drafts[role_key] = draft

        for recipient, key in pending:
            try:
                session.add(
                    NotifyMessage(
                        receiver_id=recipient.user_id,
                        notify_type=tone.notify_type,
                        order_id=order_id,
                        title=draft.title,
                        content=draft.content,
                        is_read=0,
                    )
                )
                # 立即 flush：既让数据库兜底判重能看到本批次已写入的行，
                # 也让列宽超限之类的约束错误在此处暴露并被计数
                await session.flush()
                created += 1
            except Exception:  # noqa: BLE001 —— 单个收件人失败不影响其余收件人
                await dedup.release(key)
                failed += 1
                logger.exception(
                    "写入通知失败（收件人 %s，规则 %s）", recipient.user_id, rule_code
                )

    return DispatchResult(
        created=created, skipped=skipped, failed=failed, drafts=drafts
    )


def pick_draft(
    result: DispatchResult, role_key: str | None = None
) -> NotifyDraft | None:
    """
    从派发结果里挑一份文案返回给接口调用方。

    优先返回调用者自身角色视角的那一份：管理员点「生成通知」时
    应看到管理口径的文案，而不是给预约人看的那版。
    """
    if not result.drafts:
        return None
    if role_key and role_key in result.drafts:
        return result.drafts[role_key]
    if ROLE_OWNER in result.drafts:
        return result.drafts[ROLE_OWNER]
    return next(iter(result.drafts.values()))


# ---------- 业务事件 / Agent 工具的统一入口 ----------


async def dispatch_order_notification(
    *,
    order_id: int | None,
    notify_type: str | int,
    rule_code: str,
    rule_label: str | None = None,
    reason: str | None = None,
    extra_facts: Mapping[str, Any] | None = None,
    audience: frozenset[str] = AUDIENCE_OWNER_AND_ADMIN,
    llm: Any = None,
    timeout: float | None = None,
    source: str = "event",
) -> DispatchResult:
    """
    按业务事件（或 Agent 工具调用）推送一条通知。

    分两段：段1 短事务读订单事实与收件人，段2 短事务做「去重 → 生成 → 写库」。
    两段之间只有纯内存的事实组装，不持有任何数据库连接。

    :param order_id: 关联订单。设备故障之类没有订单的事件可传 None，
        此时受众自动退化为管理员（resolve_recipients 拿不到 owner_id 会跳过预约人）。
    :param reason: 需要告知对方的原因，会注入事实载荷供模板与 Prompt 填充。
    :param extra_facts: 载荷补充的事实（如 deviceName / deviceType）。
        库中已有的事实不会被它们覆盖。
    :param source: 去重指纹的来源标识。事件推送与定时扫描用不同 source，
        避免两条来源的通知互相遮蔽。
    """
    # 段1：读订单快照与收件人（短事务）
    async with session_scope() as session:
        snapshot: OrderSnapshot | None = None
        if order_id is not None:
            snapshot = await load_order_snapshot(session, order_id)
            if snapshot is None:
                logger.warning("事件 %s 关联的订单 %s 不存在，通知已跳过", rule_code, order_id)
        recipients = await resolve_recipients(
            session,
            audience=audience,
            owner_id=snapshot.user_id if snapshot is not None else None,
        )

    if not recipients:
        logger.info("事件 %s 未解析到收件人，已跳过", rule_code)
        return DispatchResult()

    payload: dict[str, Any] = dict(extra_facts or {})
    if reason:
        payload.setdefault("reason", reason)
    facts = build_order_facts(snapshot, payload)

    # 段2：去重 → 生成 → 写库（短事务）
    async with session_scope() as session:
        dedup = build_dedup(session)
        try:
            result = await generate_and_dispatch(
                session=session,
                recipients=recipients,
                dedup=dedup,
                notify_type=notify_type,
                facts=facts,
                rule_code=rule_code,
                rule_label=rule_label,
                reason=reason,
                order_ids=(snapshot.id,) if snapshot is not None else (),
                space_id=snapshot.space_id if snapshot is not None else None,
                order_id=snapshot.id if snapshot is not None else None,
                llm=llm,
                timeout=timeout,
                source=source,
            )
            await session.commit()
        finally:
            await dedup.aclose()

    logger.info(
        "事件 %s 推送完成：写入 %s 条，去重跳过 %s 条，失败 %s 条",
        rule_code,
        result.created,
        result.skipped,
        result.failed,
    )
    return result


# ---------- 模块 4 Tool 的 service 入口 ----------


async def generate_notification(order_info: dict) -> dict:
    """
    模块 4 的 Tool `generate_notification` 调用的 service 入口。

    入参 `order_info` 是主文档 5.3「模块 7 `POST /api/v1/notify/generate`」载荷里的
    `orderInfo` 对象（驼峰键，只带非 None 字段）：`notifyType` / `orderId` /
    `receiverId` / `spaceName` / `startTime` / `endTime`。

    返回形状由模块 4 冻结的 Tool 契约决定（见 `app/agent/tools/generate_notification.py`）：
    成功 `{"ok": True, "notifyType": <int>, "title": ..., "content": ...}`；
    失败 `{"ok": False, "reason": ...}`。**不返回 `stub` 键**，表示这是真实实现。

    ⚠️ 与 `services/` 层「失败一律抛 `BizError` 子类」的约定不同，本函数不抛异常：
    它服务的边界是 Agent Tool，抛栈会打断对话（主文档 9.3）。异常一律转成
    `ok=False` + `reason` 返回。

    已知限制：`receiverId` 当前不被采纳。收件人由 `resolve_recipients` 按订单预约人与
    管理员**角色**解析（`dispatch_order_notification` 的 `audience` 收角色集合，不收单个
    用户 ID）。要按人指定收件人需另立接口。
    """
    data = {to_snake_key(str(key)): value for key, value in (order_info or {}).items()}
    raw_type = data.get("notify_type") or "提醒"
    order_id = data.get("order_id")
    reason = data.get("reason")

    if order_id is not None and (
        not isinstance(order_id, int) or isinstance(order_id, bool)
    ):
        return {"ok": False, "reason": f"orderId 必须是整数，收到 {order_id!r}"}

    # 先解析语气：字典外的取值在这里就拦下，不落库、不猜数字
    try:
        tone = resolve_tone(raw_type)
    except Exception as exc:  # noqa: BLE001 —— 见 docstring：本入口不抛异常
        return {"ok": False, "reason": str(exc)}

    extra_facts = {
        key: data[key]
        for key in ("space_name", "start_time", "end_time")
        if data.get(key) is not None
    }

    try:
        result = await dispatch_order_notification(
            order_id=order_id,
            notify_type=raw_type,
            rule_code="agent_manual",
            rule_label=str(raw_type),
            reason=reason,
            extra_facts=extra_facts or None,
            source="agent",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Agent 通知入口失败：order_id=%s", order_id)
        return {"ok": False, "reason": f"通知生成失败：{exc}"}

    draft = pick_draft(result)
    if draft is None:
        return {
            "ok": False,
            "reason": (
                f"未生成文案：订单 {order_id} 不存在、没有可通知的收件人，"
                "或该通知已被去重跳过"
            ),
        }

    return {
        "ok": True,
        "notifyType": tone.notify_type,
        "title": draft.title,
        "content": draft.content,
    }
