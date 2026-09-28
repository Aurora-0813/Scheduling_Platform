"""
AI 通知文案生成接口

契约（开发流程.md 5.3 模块7）：
    POST /api/v1/notify/generate
    入：{ "type": "延期致歉", "orderInfo": {} }
    出：{ "title": "...", "content": "..." }

响应严格保持 title / content 两个字段，不加任何额外字段。

三段式执行，理由同 /conflicts/scan：中间要等大模型，
不能把数据库连接握在手里。身份一律取 JWT，请求体里的
userId / receiverId 一律忽略（开发流程.md 5.1 防身份伪造）。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from langchain_core.language_models import BaseChatModel

from app.agent.chains.notify_chain import generate_notify_content
from app.agent.prompts.notify_templates import render_fallback, resolve_tone
from app.api.deps import CurrentUser, get_current_user, get_llm
from app.core.database import session_scope
from app.core.response import ApiResponse, ok
from app.schemas.notify import NotifyContent, NotifyGenerateRequest
from app.services.dedup import build_dedup
from app.services.notify_service import (
    Recipient,
    build_order_facts,
    generate_and_dispatch,
    load_order_snapshot,
    pick_draft,
    resolve_recipients,
    role_key_for,
)
from app.services.rules.base import AUDIENCE_OWNER_AND_ADMIN

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notify", tags=["AI冲突预警与智能通知"])


def extract_order_id(order_info: dict[str, Any]) -> int | None:
    """从载荷里取订单ID，取不到返回 None（此时只生成文案、不落库）"""
    raw = order_info.get("orderId")
    if raw is None:
        raw = order_info.get("order_id")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("orderInfo.orderId 不是合法整数：%r", raw)
        return None


@router.post(
    "/generate",
    response_model=ApiResponse[NotifyContent],
    summary="AI 生成通知文案（生成并落库）",
)
async def generate_notification(
    payload: NotifyGenerateRequest,
    user: CurrentUser = Depends(get_current_user),
    llm: BaseChatModel = Depends(get_llm),
) -> ApiResponse[NotifyContent]:
    """
    生成一条多语气通知文案并写入 notify_message。

    - 语气非法 → 业务码 400
    - 订单不存在 → 只用载荷生成文案且**不落库**，避免 AI 编造的资源名进入正式通知
    - 数据库里有的事实以库为准，请求载荷不能覆盖
    """
    tone = resolve_tone(payload.notify_type)
    requester_role = role_key_for(user.role)
    order_id = extract_order_id(payload.order_info)

    # 段1：短事务读订单与收件人
    snapshot = None
    recipients: list[Recipient] = []
    if order_id is not None:
        async with session_scope() as session:
            snapshot = await load_order_snapshot(session, order_id)
            if snapshot is not None:
                recipients = await resolve_recipients(
                    session,
                    audience=AUDIENCE_OWNER_AND_ADMIN,
                    owner_id=snapshot.user_id,
                )
        if snapshot is None:
            logger.warning("orderInfo.orderId=%s 在库中不存在，仅生成文案不落库", order_id)

    facts = build_order_facts(snapshot, payload.order_info)

    # 段2：AI 生成（不持有连接）。调用方自己视角的那一份文案必然生成，
    # 既用作响应，也复用为派发时该角色分组的文案，避免同一角色调两次模型。
    draft = await generate_notify_content(
        notify_type=payload.notify_type,
        facts=facts,
        recipient_role=requester_role,
        rule_label=payload.order_info.get("ruleLabel"),
        reason=payload.order_info.get("reason"),
        llm=llm,
    )

    if snapshot is None:
        # 无订单上下文：只回文案，不落库
        return ok(NotifyContent(title=draft.title, content=draft.content))

    # 调用者本人也应是收件人，否则他看不到自己刚生成的通知
    if all(recipient.user_id != user.user_id for recipient in recipients):
        recipients.append(
            Recipient(
                user_id=user.user_id,
                username=user.username or f"用户#{user.user_id}",
                role_name=user.role,
                role_key=requester_role,
            )
        )

    # 段3：短事务派发落库
    async with session_scope() as session:
        dedup = build_dedup(session)
        try:
            result = await generate_and_dispatch(
                session=session,
                recipients=recipients,
                dedup=dedup,
                notify_type=payload.notify_type,
                facts=facts,
                rule_code="manual_notify",
                rule_label=payload.order_info.get("ruleLabel"),
                reason=payload.order_info.get("reason"),
                order_ids=(snapshot.id,),
                space_id=snapshot.space_id,
                order_id=snapshot.id,
                llm=llm,
                precomputed={requester_role: draft},
                source="manual",
            )
            await session.commit()
        finally:
            await dedup.aclose()

    logger.info(
        "手动生成通知：订单 %s，语气 %s，写入 %s 条，去重跳过 %s 条",
        snapshot.id,
        tone.key,
        result.created,
        result.skipped,
    )

    # 响应始终用调用者视角的那一份；若该角色分组全部被去重压掉，
    # pick_draft 仍能取到其它角色的文案，取不到才回退模板
    chosen = result.drafts.get(requester_role) or pick_draft(result, requester_role)
    if chosen is None:
        title, content = render_fallback(tone, requester_role, facts)
        return ok(NotifyContent(title=title, content=content))

    return ok(NotifyContent(title=chosen.title, content=chosen.content))
