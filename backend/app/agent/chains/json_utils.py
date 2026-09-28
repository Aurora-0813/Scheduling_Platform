"""
大模型输出解析容错

开发流程.md 7.4：大模型输出必须做 JSON 解析容错，异常时返回自然语言文本。
开发流程.md 13 风险表：Agent 输出 JSON 格式错乱 → 后端增加 JSON 解析容错。
"""
from __future__ import annotations

import ast
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
# 允许字段值里出现转义字符
_TITLE_RE = re.compile(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"')
_CONTENT_RE = re.compile(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"')


def coerce_content(raw: Any) -> str:
    """
    把 AIMessage.content 归一成字符串。

    不能直接 .strip()：langchain-openai 1.x 在新输出格式下
    content 可能是 [{"type": "text", "text": "..."}] 列表，会抛 AttributeError。
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts: list[str] = []
        for block in raw:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(raw)


def _unescape(raw: str) -> str:
    """把正则抢救出来的裸字符串按 JSON 规则还原转义字符"""
    try:
        return json.loads(f'"{raw}"')
    except (ValueError, TypeError):
        return raw


def _loads(text: str) -> dict | None:
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_llm_json(text: str) -> dict | None:
    """
    六级容错解析，全部失败返回 None：

    1. 直接 json.loads
    2. 剥离 Markdown 代码围栏
    3. 截取首个 { 到末个 } 再解析
    4. 对同一片段用 ast.literal_eval（治单引号等 Python 字面量写法）
    5. 正则逐字段抢救（title 与 content 都拿到才算成功）
    6. 放弃
    """
    if not text:
        return None
    candidate = text.strip()

    # 1) 直接解析
    parsed = _loads(candidate)
    if parsed is not None:
        return parsed

    # 2) 剥离 Markdown 代码围栏
    fence = _FENCE_RE.search(candidate)
    if fence:
        fenced = fence.group(1).strip()
        parsed = _loads(fenced)
        if parsed is not None:
            return parsed
        candidate = fenced

    # 3) 截取首个 { 到末个 }
    start, end = candidate.find("{"), candidate.rfind("}")
    if start != -1 and end > start:
        snippet = candidate[start : end + 1]

        parsed = _loads(snippet)
        if parsed is not None:
            return parsed

        # 4) 治单引号
        try:
            literal = ast.literal_eval(snippet)
        except (ValueError, SyntaxError):
            literal = None
        if isinstance(literal, dict):
            return literal

    # 5) 正则逐字段抢救：只有两个字段都拿到才认，避免半个结果污染通知
    title_match = _TITLE_RE.search(candidate)
    content_match = _CONTENT_RE.search(candidate)
    if title_match and content_match:
        logger.info("LLM 输出 JSON 破损，已通过正则抢救出 title/content")
        return {
            "title": _unescape(title_match.group(1)),
            "content": _unescape(content_match.group(1)),
        }

    # 6) 放弃
    return None


def looks_like_prose(text: str) -> bool:
    """
    判断是否为「像样的自然语言散文」。

    用于第二级降级：文档要求「异常时返回自然语言文本」，
    所以当模型回了一段没有 JSON 结构的通顺文字时，应当复用这段文字，
    而不是整条丢弃去套模板。
    """
    stripped = (text or "").strip()
    return len(stripped) >= 10 and "{" not in stripped
