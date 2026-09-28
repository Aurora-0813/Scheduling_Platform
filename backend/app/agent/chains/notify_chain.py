"""
AI 通知文案生成链 —— 三级降级

降级阶梯（每一级都产出可落库的文案，绝不抛出异常给调用方）：

| 级 | 条件                                   | source     | degraded_reason   |
|----|----------------------------------------|------------|-------------------|
| 0  | AI_ENABLED=False                       | template   | ai_disabled       |
| 1  | 调用成功且解析出合法 JSON              | ai_json    | -                 |
| 2  | 调用成功但返回自然语言散文             | ai_text    | json_parse_failed |
| 3  | JSON 破损 / 超时 / 调用异常 / 空响应   | template   | 相应原因          |

第 2 级是刻意设计的：开发流程.md 7.4 要求「大模型输出必须做 JSON 解析容错，
异常时返回自然语言文本」—— 直接丢弃一段通顺的散文去套模板并不符合文档原意。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.chains.json_utils import coerce_content, looks_like_prose, parse_llm_json
from app.agent.chains.llm import build_llm
from app.agent.prompts.notify_prompts import (
    build_notify_system_prompt,
    build_notify_user_prompt,
)
from app.agent.prompts.notify_templates import (
    CONTENT_MAX,
    ROLE_OWNER,
    TITLE_MAX,
    clip_text,
    render_fallback,
    resolve_tone,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

SourceType = Literal["ai_json", "ai_text", "template"]


@dataclass(frozen=True, slots=True)
class NotifyDraft:
    """
    生成结果。

    source 与 degraded_reason 是内部字段，用于日志、监控与测试断言，
    不进 API 响应（契约只允许 title / content）。
    """

    title: str
    content: str
    source: SourceType
    degraded_reason: str | None = None


async def generate_notify_content(
    *,
    notify_type: str | int,
    facts: Mapping[str, Any],
    recipient_role: str = ROLE_OWNER,
    rule_label: str | None = None,
    reason: str | None = None,
    llm: BaseChatModel | None = None,
    timeout: float | None = None,
) -> NotifyDraft:
    """
    生成一条通知文案。

    :param notify_type: 语气，接受整数 notify_type 或中文名（"延期致歉"）
    :param facts: 已结构化的事实，供 Prompt 与兜底模板共同使用
    :param llm: 注入点。测试传假 LLM；不传则按配置构造
    :param timeout: 覆盖 settings.LLM_TIMEOUT，便于测试超时分支
    """
    # 非法 type 在此抛出 ApiError(400)，由全局异常处理器转成统一响应体
    tone = resolve_tone(notify_type)
    fallback_title, fallback_content = render_fallback(tone, recipient_role, facts)

    # 级 0：AI 总开关关闭
    if not settings.AI_ENABLED:
        return NotifyDraft(
            fallback_title, fallback_content, "template", "ai_disabled"
        )

    model = llm if llm is not None else build_llm()
    effective_timeout = (
        timeout if timeout is not None else settings.LLM_TIMEOUT
    )

    messages = [
        SystemMessage(content=build_notify_system_prompt(tone, recipient_role)),
        HumanMessage(
            content=build_notify_user_prompt(
                tone=tone,
                recipient_role=recipient_role,
                facts=facts,
                rule_label=rule_label,
                reason=reason,
            )
        ),
    ]

    try:
        # 双层超时：SDK 层超时对连接挂死不总可靠，外层再兜一道
        response = await asyncio.wait_for(
            model.ainvoke(messages), timeout=effective_timeout
        )
    except asyncio.TimeoutError:
        logger.warning("通知文案生成超时（%.2fs），降级为模板", effective_timeout)
        return NotifyDraft(fallback_title, fallback_content, "template", "timeout")
    except Exception:
        logger.exception("通知文案生成调用失败，降级为模板")
        return NotifyDraft(fallback_title, fallback_content, "template", "api_error")

    raw_text = coerce_content(getattr(response, "content", response)).strip()
    if not raw_text:
        logger.warning("通知文案生成返回空内容，降级为模板")
        return NotifyDraft(fallback_title, fallback_content, "template", "empty")

    # 级 1：合法 JSON
    parsed = parse_llm_json(raw_text)
    if parsed:
        title = clip_text(str(parsed.get("title") or ""), TITLE_MAX)
        content = clip_text(str(parsed.get("content") or ""), CONTENT_MAX)
        if title and content:
            return NotifyDraft(title, content, "ai_json")

    # 级 2：模型回了通顺的自然语言，按文档要求复用文本，仅标题回退到模板
    if looks_like_prose(raw_text):
        return NotifyDraft(
            fallback_title,
            clip_text(raw_text, CONTENT_MAX),
            "ai_text",
            "json_parse_failed",
        )

    # 级 3：内容既非 JSON 也不像可用文本
    logger.warning("通知文案生成结果无法使用，降级为模板：%r", raw_text[:120])
    return NotifyDraft(fallback_title, fallback_content, "template", "json_parse_failed")
