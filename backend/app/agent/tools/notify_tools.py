"""
Agent 工具：通知文案生成

供主调度 Agent（模块 4）注册使用：用户说「提前通知参会人员」时，
Agent 调用本工具生成并推送通知文案。

开发流程.md 9.3 的两条硬约束：
1. Agent 只能通过 Tool 调用 `services/` 层，禁止直连数据库
2. Tool 内禁止直接使用 `AsyncSession`

因此本文件里没有任何数据库对象：会话由 services 层自建。
本工具也**只生成文案，不改变任何业务状态** —— 预约的创建、变更、取消
必须走各自的业务接口（开发流程.md 4.4：AI 只负责生成文案）。

注意：内部 Tool 不注册为公开 HTTP 端点，本模块不提供任何路由。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import tool

from app.agent.prompts.notify_templates import ROLE_OWNER
from app.services.notify_service import dispatch_order_notification, pick_draft

logger = logging.getLogger(__name__)


@tool
async def generate_notification(
    order_id: int,
    notify_type: str = "提醒",
    reason: str = "",
) -> str:
    """为指定预约生成一条多语气通知文案，保存并推送给预约人及相关管理员。

    仅在用户明确要求通知/提醒/致歉时调用。本工具只生成文案，
    不会创建、修改或取消预约。

    Args:
        order_id: 预约订单ID（整数）。
        notify_type: 通知语气，可选「提醒」「延期致歉」「故障告警」。
        reason: 需要告知对方的原因，例如「设备临时检修」。可为空。

    Returns:
        JSON 字符串：成功时含 title 与 content；失败时含 code 与 message。
    """
    if not isinstance(order_id, int) or isinstance(order_id, bool) or order_id <= 0:
        return _fail(f"order_id 必须是正整数，收到 {order_id!r}", code=400)

    try:
        result = await dispatch_order_notification(
            order_id=order_id,
            notify_type=notify_type,
            rule_code="agent_manual",
            rule_label=notify_type,
            reason=reason or None,
            source="agent",
        )
    except Exception as exc:  # noqa: BLE001 —— 工具必须给出可读结果而不是抛栈
        logger.exception("Agent 调用通知工具失败：订单 %s", order_id)
        return _fail(f"通知生成失败：{exc}", code=500)

    draft = pick_draft(result, ROLE_OWNER)
    if draft is None:
        return _fail(f"订单 {order_id} 不存在，或该订单没有可通知的收件人")

    return json.dumps(
        {
            "code": 200,
            "title": draft.title,
            "content": draft.content,
            "receivers": result.targeted,
        },
        ensure_ascii=False,
    )


def _fail(message: str, *, code: int = 404) -> str:
    """工具失败时也返回 JSON，让模型能读懂并回复用户，而不是抛异常打断对话"""
    return json.dumps({"code": code, "message": message}, ensure_ascii=False)


# 供主 Agent 注册的工具清单（开发流程.md 8.5：工具集中在 tools/ 包内）
NOTIFY_TOOLS: tuple[Any, ...] = (generate_notification,)
