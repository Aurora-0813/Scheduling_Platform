"""
参会人数抽取链

AI 为主，正则兜底。两者都失败返回 None，此时「容量远超需求」规则自动跳过
（既定口径：抽不到就跳过，绝不猜测）。
"""
from __future__ import annotations

import asyncio
import logging
import re

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.chains.json_utils import coerce_content, parse_llm_json
from app.agent.chains.llm import build_llm
from app.agent.prompts.extract_prompts import (
    EXTRACT_SYSTEM_PROMPT,
    build_extract_user_prompt,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

# 阿拉伯数字：「40人」「40 来人」「40多号人」
_ARABIC_RE = re.compile(r"(\d{1,4})\s*(?:来|多|余)?\s*(?:个|号)?\s*人")
# 中文数字：「四十人」「四十来号人」「二十人左右」
_CHINESE_RE = re.compile(
    r"([零一二两三四五六七八九十]{1,3})\s*(?:来|多|余)?\s*(?:个|号)?\s*人"
)

_CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}

# 明显不合理的数值直接丢弃，避免脏数据触发误报
_MIN_SANE = 1
_MAX_SANE = 100000


def _chinese_to_int(text: str) -> int | None:
    """把「四十」「四十五」「二十」这类中文数字转成整数，失败返回 None"""
    if not text:
        return None

    if "十" in text:
        left, _, right = text.partition("十")
        if left and left not in _CN_DIGITS:
            return None
        if right and right not in _CN_DIGITS:
            return None
        tens = _CN_DIGITS[left] if left else 1
        ones = _CN_DIGITS[right] if right else 0
        return tens * 10 + ones

    if all(ch in _CN_DIGITS for ch in text):
        value = 0
        for ch in text:
            value = value * 10 + _CN_DIGITS[ch]
        return value
    return None


def extract_attendee_by_regex(text: str) -> int | None:
    """
    正则兜底抽取。

    注意：需求原文里同时出现「场地容量」与「实际人数」时，
    正则无法可靠区分二者（这正是 AI 为主、正则为辅的原因）。
    """
    if not text:
        return None

    arabic = _ARABIC_RE.search(text)
    if arabic:
        value = int(arabic.group(1))
        if _MIN_SANE <= value <= _MAX_SANE:
            return value

    chinese = _CHINESE_RE.search(text)
    if chinese:
        value = _chinese_to_int(chinese.group(1))
        if value is not None and _MIN_SANE <= value <= _MAX_SANE:
            return value

    return None


def _coerce_count(raw: object) -> int | None:
    """把模型返回的字段值规整成正整数，任何异常形态都返回 None"""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if _MIN_SANE <= value <= _MAX_SANE else None


async def _extract_by_llm(
    text: str,
    *,
    llm: BaseChatModel | None,
    timeout: float | None,
) -> int | None:
    """AI 抽取。任何失败都静默返回 None，由正则兜底接手"""
    model = llm if llm is not None else build_llm()
    effective_timeout = timeout if timeout is not None else settings.LLM_TIMEOUT_SECONDS

    try:
        response = await asyncio.wait_for(
            model.ainvoke(
                [
                    SystemMessage(content=EXTRACT_SYSTEM_PROMPT),
                    HumanMessage(content=build_extract_user_prompt(text)),
                ]
            ),
            timeout=effective_timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("参会人数抽取超时（%.2fs），改用正则兜底", effective_timeout)
        return None
    except Exception:
        logger.exception("参会人数抽取调用失败，改用正则兜底")
        return None

    raw_text = coerce_content(getattr(response, "content", response)).strip()
    parsed = parse_llm_json(raw_text)
    if not parsed:
        return None

    # 兼容 attendeeCount / attendee_count 两种写法
    for key in ("attendeeCount", "attendee_count"):
        if key in parsed:
            return _coerce_count(parsed[key])
    return None


async def extract_attendee_count(
    text: str | None,
    *,
    llm: BaseChatModel | None = None,
    timeout: float | None = None,
) -> int | None:
    """
    从需求原文抽取参会人数，抽不到返回 None。
    """
    if not text or not text.strip():
        return None

    if settings.AI_ENABLED:
        value = await _extract_by_llm(text, llm=llm, timeout=timeout)
        if value is not None:
            return value

    value = extract_attendee_by_regex(text)
    if value is not None:
        logger.info("参会人数由正则兜底抽取：%s", value)
    return value
