"""
冲突扫描接口

契约（开发流程.md 5.3 模块7）：
    GET /api/v1/conflicts/scan
    → [ { "conflictType": "软冲突", "orderIds": [1,2], "suggestion": "...", "ruleCode": "..." } ]

本接口是**只读**的：不落库、不推送、幂等可重放，看板可以放心轮询。
真正的推送由定时扫描任务与事件总线负责。

注意本端点不使用 get_db 请求级会话：中间要等大模型 3~20 秒，
持有数据库连接会让连接池在 2 核 2G 的部署目标上被占满。
改为「短事务读快照 → 无会话调 AI → 无会话跑规则」三段式。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from langchain_core.language_models import BaseChatModel

from app.api.deps import CurrentUser, get_current_user, get_llm
from app.core.database import session_scope
from app.core.response import ApiResponse, ok
from app.schemas.conflict import ConflictItem
from app.services.conflict_service import (
    build_conflict_items,
    enrich_attendees,
    load_rule_context,
)
from app.services.rules.registry import run_all

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conflicts", tags=["AI冲突预警与智能通知"])


@router.get(
    "/scan",
    response_model=ApiResponse[list[ConflictItem]],
    summary="软冲突扫描（只读）",
)
async def scan_conflicts(
    _user: CurrentUser = Depends(get_current_user),
    llm: BaseChatModel = Depends(get_llm),
) -> ApiResponse[list[ConflictItem]]:
    """
    扫描窗口内的软冲突并返回处置建议。

    规则引擎是同步纯函数，AI 只负责前置的人数抽取（富化），
    因此 AI 不可用时本接口仍能返回全部基于时间与容量的冲突。
    """
    # 段1：短事务读快照
    async with session_scope() as session:
        ctx = await load_rule_context(session)

    # 段2：AI 富化（不持有连接）
    ctx, enriched = await enrich_attendees(ctx, llm=llm)

    # 段3：纯函数规则（不持有连接）
    hits = run_all(ctx)

    logger.info(
        "冲突扫描完成：快照订单 %s 笔，AI 富化 %s 笔，命中软冲突 %s 条",
        len(ctx.orders),
        enriched,
        len(hits),
    )
    return ok(build_conflict_items(hits))
