"""
大模型构建 —— 全模块唯一 LLM 出口

集中在此处是为了三件事：
1. 测试时可注入假 LLM 夹具（函数参数注入 / FastAPI 依赖覆盖）
2. 答辩现场 API 欠费时一键切假 LLM（开发流程.md 13.1 应急预案）
3. 开发期避免误烧 token

开发流程.md 3.3：不训练、不微调任何大模型，不本地运行大权重模型，全部走云端 API。
"""
from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel

from app.core.config import settings

logger = logging.getLogger(__name__)

# 假 LLM 的默认响应：一条合法的通知文案 JSON
FAKE_NOTIFY_JSON = (
    '{"title": "【预约提醒】您的预约即将开始", '
    '"content": "您好，您在 A栋3楼展厅 的预约即将开始，请提前 10 分钟到场布置。'
    '如需调整，请在预约记录中发起变更。"}'
)


def build_fake_llm(
    responses: list[str] | None = None,
    *,
    sleep: float | None = None,
) -> BaseChatModel:
    """
    假 LLM 夹具。文档 10.2 要求「Agent 层测试使用假 LLM 夹具，保证离线可跑」。

    :param responses: 依次返回的内容，缺省为一条合法通知 JSON
    :param sleep: 每次调用阻塞的秒数，用于测试超时降级分支
    """
    from langchain_core.language_models.fake_chat_models import (
        FakeMessagesListChatModel,
    )
    from langchain_core.messages import AIMessage

    payloads = responses or [FAKE_NOTIFY_JSON]
    # 多备几份，避免夹具在连续多次调用时耗尽响应
    return FakeMessagesListChatModel(
        responses=[AIMessage(content=text) for text in payloads] * 3,
        sleep=sleep,
    )


def build_llm(*, temperature: float = 0.4, timeout: float | None = None) -> BaseChatModel:
    """
    构造大模型客户端。

    AI_ENABLED=False 或 AI_USE_FAKE_LLM=True 时返回假 LLM，
    调用方（notify_chain）会因 AI_ENABLED 判断直接走模板，不会真的调用它。
    """
    if settings.AI_USE_FAKE_LLM or not settings.AI_ENABLED:
        logger.info(
            "使用假 LLM 夹具（AI_ENABLED=%s, AI_USE_FAKE_LLM=%s）",
            settings.AI_ENABLED,
            settings.AI_USE_FAKE_LLM,
        )
        return build_fake_llm()

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.LLM_MODEL,
        # 未配置 Key 时给个占位值，让构造成功、调用失败，
        # 从而落到统一的降级链路，而不是在构造期抛出难懂的异常
        api_key=settings.LLM_API_KEY or "NOT_CONFIGURED",
        base_url=settings.LLM_BASE_URL,
        timeout=timeout or settings.LLM_TIMEOUT,
        max_retries=1,
        temperature=temperature,
    )
