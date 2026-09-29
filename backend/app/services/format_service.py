"""口语清洗服务（模块 1 语音输入）：把带口头禅的口语整理成书面语并提取关键词。

要求（开发流程 §4.4 / §7.4）：
- 输出 {"formattedText": "...", "keywords": [...]}
- **任何异常都降级为原始文本**，送 Agent 兜底，不能让流程中断。

⚠️ **2026-09-30 两处修复：**

1. **不再单独用 DeepSeek，改为复用 `LLM_*`（百炼）。**
   原实现用 `settings.DEEPSEEK_*` 这一套独立配置，而 `.env` 里从未填过
   `DEEPSEEK_API_KEY`（全项目其他地方都用百炼），于是这个接口**必然 500**。
   现在统一走 `app/core/llm.py::build_llm()` —— 顺带继承了它的守卫：
   未配置 Key 时它给一个占位值让**构造成功、调用失败**，从而落到本函数的降级分支，
   而不是在构造期抛出一个没人接得住的异常。

2. **把客户端构造挪进了 `try`。**
   原实现的 `try` 从 `llm.ainvoke()` 才开始，而 `ChatOpenAI(...)` 构造在它**外面**
   —— 构造一旦抛异常（缺 Key 就是这个报错）就直接冒到路由层变成 **HTTP 500**，
   那句「失败降级为原文」的承诺**根本没生效**。这是本次 500 的直接原因。
   现在整个「构造 + 调用 + 解析」都在同一个 `try` 里。
"""

import json
import re
from datetime import datetime

from app.core.config import settings
from app.core.llm import build_llm
from app.core.logging import get_logger

logger = get_logger(__name__)

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
    """从模型输出里提取 JSON，兼容 markdown 代码块包裹。"""
    match = re.search(r"\{.*\}", content, re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except Exception:  # noqa: BLE001 - 模型输出不可信，任何解析失败都按「没提取到」处理
        return {}


def _degraded(raw_text: str) -> dict:
    """统一的降级出口：原样返回用户的话。"""
    return {"formattedText": raw_text, "keywords": []}


async def format_spoken_text(raw_text: str) -> dict:
    """清洗口语，返回 {"formattedText": ..., "keywords": [...]}；失败降级为原文。"""
    if not raw_text or not raw_text.strip():
        return _degraded(raw_text)

    # AI 关闭时不必白构造一次客户端 —— 直接按契约降级（与 Agent/看板同口径）。
    if not settings.AI_ENABLED:
        return _degraded(raw_text)

    try:
        # ⚠️ 构造必须在 try **内部**：缺 Key / 端点写错 / SDK 版本变化都可能在
        #    构造期抛异常，放在外面就等于把「降级」这条承诺作废（本次 500 的根因）。
        llm = build_llm(temperature=0.1)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"今天是{_today_str()}。\n用户原话：{raw_text}"},
        ]
        resp = await llm.ainvoke(messages)

        parsed = _extract_json(getattr(resp, "content", "") or "")
        formatted = parsed.get("formattedText") or raw_text
        keywords = parsed.get("keywords", [])
        if not isinstance(keywords, list):
            keywords = []
        return {"formattedText": formatted, "keywords": [str(k) for k in keywords]}
    except Exception:
        # 这里**故意**捕获所有异常（含构造期异常）：契约明文要求「不能让流程中断」。
        # ruff 不认为这是 blind-except，因为下面有 logger.exception 记录，
        # 所以不需要 noqa（加了反而会被 RUF100 判为多余的指令）。
        logger.exception("口语清洗失败，已降级为原文（%d 字）", len(raw_text))
        return _degraded(raw_text)
