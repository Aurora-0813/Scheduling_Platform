"""
参会人数抽取 Prompt

reserve_order 表没有人数字段，而「容量远超需求」规则需要人数，
按既定口径由 AI 从订单的 agent_request 原始需求文本中抽取，抽不到即跳过该规则。
"""
from __future__ import annotations

EXTRACT_SYSTEM_PROMPT = """你从企业空间预约需求文本中抽取「参会人数」。

规则：
1. 只输出严格 JSON，格式为：{{"attendeeCount": 40}}
2. 无法确定时输出：{{"attendeeCount": null}}
3. 注意区分「场地容量」与「实际参会人数」：像「要个能坐40人的展厅」这种
   只给了容量描述的情况，可视为参会人数约 40；若文中另行给出了实际人数，
   则以实际人数为准。
4. 口语表达要正确理解，例如「四十来号人」「大概三十多人」「二十人左右」。
5. 不要输出任何解释性文字，不要加 Markdown 代码围栏。"""


def build_extract_user_prompt(text: str) -> str:
    """把待抽取的原始需求文本包进提示"""
    return f"【需求原文】\n{text}\n\n请抽取参会人数，输出严格 JSON。"
