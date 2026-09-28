"""
多语气通知文案模板

承担两个角色：
1. AI 生成失败/超时/关闭时的兜底（开发流程.md 10.2 强制要求降级用例）
2. 独立的产品功能 —— 三种语气 × 三种收件人角色的差异化文案

三种语气与 notify_message.notify_type 对应：
1 预约提醒 / 2 变更致歉 / 3 故障告警
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.core.response import ApiError

# ---------- 收件人角色 ----------
ROLE_OWNER = "预约人"
ROLE_RESOURCE_ADMIN = "资源管理员"
ROLE_SYSTEM_ADMIN = "系统管理员"
ROLE_KEYS: tuple[str, ...] = (ROLE_OWNER, ROLE_RESOURCE_ADMIN, ROLE_SYSTEM_ADMIN)

# DDL 中 title 是 VARCHAR(255)、content 是 TEXT，这里留足安全边界
TITLE_MAX = 200
CONTENT_MAX = 2000


class _SafeDict(dict):
    """
    缺字段时渲染成空串而不是抛 KeyError。

    模板与 AI 输出都不得因缺失字段让落库失败 —— 硬性防御。
    """

    def __missing__(self, key: str) -> str:
        return ""


def clip_text(text: str, limit: int) -> str:
    """折叠多余空白并截断，避免超长内容写库失败"""
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


@dataclass(frozen=True, slots=True)
class ToneSpec:
    """一种语气的完整规格"""

    key: str
    notify_type: int
    label: str
    aliases: tuple[str, ...]
    tone_style: str
    # role_key -> (标题模板, 正文模板)
    role_templates: Mapping[str, tuple[str, str]]

    def template_for(self, role_key: str) -> tuple[str, str]:
        """取指定角色的模板；缺失时回退到系统管理员视角（最通用的汇总口径）"""
        return self.role_templates.get(role_key) or self.role_templates[ROLE_SYSTEM_ADMIN]


TONES: Mapping[str, ToneSpec] = {
    "提醒": ToneSpec(
        key="提醒",
        notify_type=1,
        label="预约提醒",
        aliases=("预约提醒", "提醒", "remind", "notice"),
        tone_style="友好、简洁的温馨提醒；不使用「紧急」「务必」等施压措辞，不堆砌感叹号",
        role_templates={
            ROLE_OWNER: (
                "【预约提醒】{space_name} {start_hm}",
                "{user_name} 您好，您在 {space_name} 的预约将于 {start_time} 开始，"
                "使用时段 {start_time} 至 {end_time}，订单号 {order_id}。{reason}"
                "建议预留 10 分钟场地布置时间；如需调整，请在预约记录中发起变更。",
            ),
            ROLE_RESOURCE_ADMIN: (
                "【预约提醒·待关注】{rule_label}",
                "本次扫描发现 1 条需关注事项（{rule_label}）：{reason}"
                "关联场地 {space_name}，关联订单 {order_ids_text}，预约人 {user_name}。"
                "请确认资源准备情况，并按需与预约人沟通调整。",
            ),
            ROLE_SYSTEM_ADMIN: (
                "【预约提醒·汇总】{rule_label}",
                "本次扫描命中软冲突 1 条（{rule_label}）：{reason}"
                "涉及场地 {space_name}，涉及订单 {order_ids_text}。"
                "文案已按角色生成并推送，请在管理端复核。",
            ),
        },
    ),
    "延期致歉": ToneSpec(
        key="延期致歉",
        notify_type=2,
        label="变更致歉",
        aliases=("延期致歉", "变更致歉", "致歉", "apology", "change"),
        tone_style="诚恳致歉：先陈述变更事实，再给出替代建议，不推卸责任，不过度客套",
        role_templates={
            ROLE_OWNER: (
                "【预约变更致歉】{space_name} {start_hm}",
                "{user_name} 您好，非常抱歉，您在 {space_name} 的预约"
                "（订单号 {order_id}，{start_time} 至 {end_time}）发生变更。"
                "原因：{reason}建议方案：{suggestion}"
                "给您带来的不便我们深表歉意，如需协助请联系资源管理员。",
            ),
            ROLE_RESOURCE_ADMIN: (
                "【变更致歉·待跟进】{rule_label}",
                "订单 {order_id}（{space_name}，{start_time} 至 {end_time}）"
                "已触发变更类通知，原因：{reason}"
                "预约人 {user_name} 已收到致歉文案，请跟进替代资源的落实。",
            ),
            ROLE_SYSTEM_ADMIN: (
                "【变更致歉·汇总】{rule_label}",
                "变更类通知已生成并推送：{reason}"
                "关联订单 {order_id}，场地 {space_name}。请在管理端关注后续处理进度。",
            ),
        },
    ),
    "故障告警": ToneSpec(
        key="故障告警",
        notify_type=3,
        label="故障告警",
        aliases=("故障告警", "故障", "fault", "alert"),
        tone_style="客观、专业、克制；面向管理员陈述现象与建议动作，不对故障定责",
        role_templates={
            ROLE_OWNER: (
                "【设备故障提醒】{device_name}",
                "{user_name} 您好，您预约使用的设备 {device_name}（{device_type}）"
                "出现异常：{reason}"
                "建议到场前联系资源管理员确认设备可用性，或更换其他可用设备。",
            ),
            ROLE_RESOURCE_ADMIN: (
                "【故障告警】{device_name} 待处理",
                "有 1 条设备故障告警待处理：{reason}"
                "关联设备 {device_name}（{device_type}），关联场地 {space_name}，"
                "关联订单 {order_id}。建议尽快现场确认设备状态并按流程生成维修工单。",
            ),
            ROLE_SYSTEM_ADMIN: (
                "【故障告警·汇总】{device_name}",
                "设备告警：{reason}"
                "关联设备 {device_name}，场地 {space_name}，订单 {order_id}。"
                "已推送资源管理员处理，请在管理端跟踪工单闭环。",
            ),
        },
    ),
}


def _build_alias_index() -> dict[str, str]:
    """别名 → 语气 key 的查找表，兼容契约传入中文名或英文别名"""
    index: dict[str, str] = {}
    for key, spec in TONES.items():
        index[key.strip().lower()] = key
        index[spec.label.strip().lower()] = key
        for alias in spec.aliases:
            index[alias.strip().lower()] = key
    return index


_ALIAS_INDEX = _build_alias_index()


def resolve_tone(raw: str | int) -> ToneSpec:
    """
    把契约传入的 type 解析成语气规格。

    同时接受整数 notify_type（2）与中文语气名（"延期致歉"）。
    """
    text = str(raw).strip()

    # 整数或纯数字字符串按 notify_type 匹配
    if text.lstrip("-").isdigit():
        wanted = int(text)
        for spec in TONES.values():
            if spec.notify_type == wanted:
                return spec
        raise ApiError(f"不支持的通知类型：{raw}", code=400)

    key = _ALIAS_INDEX.get(text.lower())
    if key is None:
        supported = "、".join(TONES)
        raise ApiError(f"不支持的通知类型：{raw}，可选：{supported}", code=400)
    return TONES[key]


def resolve_notify_type(raw: str | int) -> int:
    """解析并返回 notify_type 整数，供落库使用"""
    return resolve_tone(raw).notify_type


def render_fallback(
    raw_tone: ToneSpec | str | int,
    role_key: str,
    facts: Mapping[str, Any],
) -> tuple[str, str]:
    """
    渲染兜底文案，返回 (标题, 正文)。

    raw_tone 同时接受两种形态：
    - 原始值（中文语气名或整数 notify_type）—— 由本函数解析
    - 已解析的 ToneSpec —— 调用方（notify_chain）已解析过，直接复用，不重复解析

    模板与 AI 输出最终都经过 clip_text，确保不会因超长导致落库失败。
    """
    spec = raw_tone if isinstance(raw_tone, ToneSpec) else resolve_tone(raw_tone)
    title_tpl, content_tpl = spec.template_for(role_key)
    safe_facts = _SafeDict(facts)
    return (
        clip_text(title_tpl.format_map(safe_facts), TITLE_MAX),
        clip_text(content_tpl.format_map(safe_facts), CONTENT_MAX),
    )
