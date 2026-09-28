"""口语清洗服务（模块 1 语音输入）：用 DeepSeek 把带口头禅的口语整理成书面语并提取关键词。

要求（开发流程 §4.4 / §7.4）：
- 输出 {"formattedText": "...", "keywords": [...]}
- 任何异常都降级为原始文本，送 Agent 兜底，不能让流程中断。
"""

import json
import re
from datetime import datetime

from langchain_openai import ChatOpenAI

from app.core.config import settings

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

SYSTEM_PROMPT = """你是企业空间预约系统的"语音需求清洗助手"。用户会给你一段语音识别出来的口语文本，\
里面可能有口头禅（嗯、啊、呃、那个、就是说、对吧、然后呢）、重复语句、以及\
"明天/周五下午"这类模糊时间。

你要做三件事：
1. 去掉口头禅和废话，把内容整理成通顺、简洁的书面语；必须保留用户的全部真实需求\
（时间、人数、场地类型、设备、预算、特殊要求），不得编造任何用户没说过的信息。
2. 结合用户告知的今天日期，把"明天、周五、下周一"这类相对时间补成具体日期（格式 YYYY-MM-DD）。
3. 提取关键词，每个关键词形如 "人数：40"、"时间：2026-09-25 下午"、"场地：展厅"、\
"设备：投影仪x2"、"预算：1000元以内"。

只输出一个 JSON 对象，不要输出任何解释或 markdown，格式严格如下：
{"formattedText": "整理后的书面语", "keywords": ["时间：...", "人数：..."]}

如果文本实在无法整理，formattedText 就原样返回用户的话。"""


def _today_str() -> str:
    now = datetime.now()
    return f"{now.year}年{now.month}月{now.day}日 {WEEKDAYS[now.weekday()]}"


def _extract_json(content: str) -> dict:
    """从模型输出里提取 JSON，兼容 ```json 代码块包裹。"""
    match = re.search(r"\{.*\}", content, re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except Exception:  # noqa: BLE001 - 模型输出不可信，任何解析失败都按「没提取到」处理
        return {}


async def format_spoken_text(raw_text: str) -> dict:
    """清洗口语，返回 {"formattedText": ..., "keywords": [...]}；失败降级为原文。"""
    if not raw_text or not raw_text.strip():
        return {"formattedText": raw_text, "keywords": []}

    llm = ChatOpenAI(
        model=settings.DEEPSEEK_MODEL,
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        temperature=0.1,
        timeout=settings.LLM_TIMEOUT,
        max_retries=settings.LLM_MAX_RETRIES,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"今天是{_today_str()}。\n用户原话：{raw_text}"},
    ]

    try:
        resp = await llm.ainvoke(messages)
        parsed = _extract_json(resp.content)
        formatted = parsed.get("formattedText") or raw_text
        keywords = parsed.get("keywords", [])
        if not isinstance(keywords, list):
            keywords = []
        return {"formattedText": formatted, "keywords": [str(k) for k in keywords]}
    except Exception:  # noqa: BLE001 - 降级：模型/网络任何异常都用原始文本兜底，不能中断流程
        return {"formattedText": raw_text, "keywords": []}
