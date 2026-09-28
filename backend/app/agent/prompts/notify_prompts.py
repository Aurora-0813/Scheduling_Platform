"""
通知文案生成的 Prompt 构造

两条硬性约束来自开发流程.md：
- 4.3 / 9.3：AI 只输出建议、方案、文案，禁止宣称已完成业务动作
- 7.4：强制约束输出格式为 JSON
"""
from __future__ import annotations

from typing import Any, Mapping

from app.agent.prompts.notify_templates import ToneSpec

NOTIFY_SYSTEM_PROMPT = """你是企业空间与设备调度平台的「智能通知文案助手」。

硬性约束（违反任意一条即视为失败）：
1. 只能使用【输入事实】中出现的信息。严禁编造场地名、设备名、时间、金额、人名。
2. 你只负责生成文案，不得声称已完成任何业务动作。
   禁止出现「已为您取消」「已改期」「已释放资源」「已通知全体参会人」等表述。
   需要动作时改写成建议口吻，例如「如需改期，请联系资源管理员」。
3. 输出必须是严格 JSON，不要 Markdown 代码围栏，不要任何解释性文字，格式固定为：
   {{"title": "标题，不超过30字", "content": "正文，不超过200字"}}
4. 使用简体中文。
5. 语气要求：{tone_style}
6. 收件人角色：{recipient_role}，请按该角色的关注点组织内容。"""

# 事实字段的中文标签，让 Prompt 读起来是业务语言而不是变量名
FACT_LABELS: dict[str, str] = {
    "user_name": "预约人",
    "user_role": "预约人角色",
    "space_name": "场地",
    "prev_space": "上一场场地",
    "next_space": "下一场场地",
    "capacity": "场地容量",
    "attendee_count": "需求人数",
    "ratio": "容量与需求倍数",
    "device_name": "设备名称",
    "device_type": "设备类型",
    "start_time": "开始时间",
    "end_time": "结束时间",
    "start_hm": "开始时刻",
    "prev_end": "上一场结束时间",
    "next_start": "下一场开始时间",
    "gap_minutes": "间隔分钟数",
    "date": "日期",
    "occupied_hours": "当日累计占用小时",
    "threshold_hours": "占用阈值小时",
    "order_count": "涉及订单数",
    "idle_days": "闲置天数",
    "last_order_time": "最后使用时间",
    "order_id": "订单号",
    "order_ids_text": "关联订单",
}


def build_notify_system_prompt(tone: ToneSpec, recipient_role: str) -> str:
    """系统提示：把语气风格与收件人角色注入约束"""
    return NOTIFY_SYSTEM_PROMPT.format(
        tone_style=tone.tone_style,
        recipient_role=recipient_role,
    )


def format_facts(facts: Mapping[str, Any]) -> str:
    """
    把事实渲染成扁平列表。

    刻意不塞 JSON —— 嵌套结构会让模型更容易输出格式错乱，
    而本项目对 JSON 容错的要求已经很高，输入端能简化就简化。
    """
    lines: list[str] = []
    for key, value in facts.items():
        if value is None or value == "":
            continue
        lines.append(f"- {FACT_LABELS.get(key, key)}：{value}")
    return "\n".join(lines) if lines else "- （无额外事实）"


def build_notify_user_prompt(
    *,
    tone: ToneSpec,
    recipient_role: str,
    facts: Mapping[str, Any],
    rule_label: str | None = None,
    reason: str | None = None,
) -> str:
    """用户提示：按固定小节罗列本次通知的全部事实依据"""
    sections: list[str] = [
        f"【通知类型】{tone.label}",
        f"【收件人角色】{recipient_role}",
    ]
    if rule_label:
        sections.append(f"【冲突类型】{rule_label}")
    if reason:
        sections.append(f"【事实描述】{reason}")
    sections.append("【输入事实】\n" + format_facts(facts))
    sections.append("请依据以上事实，输出严格的 JSON。")
    return "\n\n".join(sections)
