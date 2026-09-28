"""
多语气模板：3 语气 × 3 角色全渲染，且任何缺字段、超长输入都不能抛异常
"""
from __future__ import annotations

import pytest

from app.agent.prompts.notify_templates import (
    CONTENT_MAX,
    ROLE_KEYS,
    ROLE_SYSTEM_ADMIN,
    TITLE_MAX,
    TONES,
    clip_text,
    render_fallback,
    resolve_notify_type,
    resolve_tone,
)
from app.core.response import ApiError

# 一套完整事实，覆盖全部模板占位符
FULL_FACTS = {
    "user_name": "张三",
    "user_role": "普通使用者",
    "space_name": "A栋3楼展厅",
    "prev_space": "A栋301会议室",
    "next_space": "A栋3楼展厅",
    "capacity": 40,
    "attendee_count": 12,
    "ratio": 3.33,
    "device_name": "无人机-1",
    "device_type": "无人机",
    "start_time": "2026-09-25 14:00",
    "end_time": "2026-09-25 16:00",
    "start_hm": "14:00",
    "prev_end": "2026-09-25 13:00",
    "next_start": "2026-09-25 13:08",
    "gap_minutes": 8,
    "date": "2026-09-25",
    "occupied_hours": 9.5,
    "threshold_hours": 8.0,
    "order_count": 3,
    "idle_days": 14,
    "last_order_time": "2026-09-01 10:00",
    "order_id": 101,
    "order_ids_text": "101、102",
    "rule_label": "连续活动无休息",
    "reason": "两场活动之间仅有 8 分钟间隔。",
    "suggestion": "建议将后一场活动延后 30 分钟。",
}


def _literal_facts(tone_key):
    """
    该语气下必然出现、且不含占位符的事实片段。

    断言这些片段真的出现在文案里，比泛泛断言「含场地名」更能抓住模板退化：
    故障告警类模板关注设备而非场地，不应强行要求出现场地名。
    """
    if tone_key == "故障告警":
        return ["无人机-1"]
    return ["A栋3楼展厅"]


@pytest.mark.parametrize("tone_key", list(TONES))
@pytest.mark.parametrize("role_key", ROLE_KEYS)
def test_all_tone_role_combinations_render(tone_key, role_key):
    """3 语气 × 3 角色 = 9 套模板全部可渲染且非空"""
    title, content = render_fallback(tone_key, role_key, FULL_FACTS)
    assert title
    assert content
    # 不留未渲染的占位符
    assert "{" not in title
    assert "{" not in content
    # 模板里出现的事实必须真的落进文案（未被吞掉）
    for token in _literal_facts(tone_key):
        assert token in title or token in content


@pytest.mark.parametrize("tone_key", list(TONES))
@pytest.mark.parametrize("role_key", ROLE_KEYS)
def test_empty_facts_do_not_raise(tone_key, role_key):
    """facts 为空字典时不得抛 KeyError —— _SafeDict 生效"""
    title, content = render_fallback(tone_key, role_key, {})
    assert isinstance(title, str)
    assert isinstance(content, str)
    assert title


def test_unknown_placeholder_is_ignored():
    """模板里没有的字段不应影响渲染"""
    title, content = render_fallback("提醒", "预约人", {"space_name": "A栋展厅"})
    assert "A栋展厅" in title


def test_unknown_role_falls_back_to_system_admin():
    title, content = render_fallback("提醒", "不存在的角色", FULL_FACTS)
    expected = render_fallback("提醒", ROLE_SYSTEM_ADMIN, FULL_FACTS)
    assert (title, content) == expected


def test_clip_text_collapses_whitespace():
    """连续空白折叠为一个空格，首尾空白去掉"""
    assert clip_text("  多   余\n空 白 ", 100) == "多 余 空 白"


def test_clip_text_truncates_with_ellipsis():
    result = clip_text("字" * 500, TITLE_MAX)
    assert len(result) == TITLE_MAX
    assert result.endswith("…")


def test_long_facts_are_clipped():
    """超长事实不能让落库失败"""
    title, content = render_fallback(
        "提醒", "预约人", {**FULL_FACTS, "space_name": "超长" * 3000}
    )
    assert len(title) <= TITLE_MAX
    assert len(content) <= CONTENT_MAX


# ---------- 语气解析 ----------


def test_resolve_tone_by_chinese_name():
    assert resolve_tone("延期致歉").notify_type == 2
    assert resolve_tone("提醒").notify_type == 1
    assert resolve_tone("故障告警").notify_type == 3


def test_resolve_tone_by_notify_type_integer():
    assert resolve_tone(1).key == "提醒"
    assert resolve_tone(2).key == "延期致歉"
    assert resolve_tone("3").key == "故障告警"


def test_resolve_tone_accepts_aliases():
    assert resolve_tone("变更致歉").key == "延期致歉"
    assert resolve_tone("apology").key == "延期致歉"


def test_resolve_notify_type_matches_contract_example():
    """契约示例：{"type": "延期致歉"} → notify_type 2"""
    assert resolve_notify_type("延期致歉") == 2


def test_resolve_tone_rejects_unknown():
    with pytest.raises(ApiError) as exc:
        resolve_tone("不存在的语气")
    assert exc.value.code == 400


def test_resolve_tone_rejects_unknown_integer():
    with pytest.raises(ApiError) as exc:
        resolve_tone(99)
    assert exc.value.code == 400
