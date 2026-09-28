"""
参会人数抽取链：AI 为主、正则兜底、全失败返回 None

「抽不到就跳过」是本模块的既定口径 ——
拿不准的人数会让「容量远超需求」规则误报，比漏报更伤演示可信度。
"""
from __future__ import annotations

import pytest

from app.agent.chains.extract_chain import (
    _chinese_to_int,
    extract_attendee_by_regex,
    extract_attendee_count,
)
from app.core.config import settings

# pytest.ini 已设 asyncio_mode=auto，async 用例无需再逐条打标记


def _llm_returning(payload: str):
    from app.agent.chains.llm import build_fake_llm

    return build_fake_llm([payload])


# ---------- AI 优先 ----------


async def test_ai_result_wins_over_regex():
    """
    需求原文同时含场地容量与人数时，只有 AI 能区分二者 ——
    这正是 AI 为主的原因。这里 AI 给出 40，正则本会先看到 200。
    """
    llm = _llm_returning('{"attendeeCount": 40}')
    value = await extract_attendee_count("200 人的大展厅，实际来 40 人", llm=llm)

    assert value == 40


async def test_ai_snake_case_key_is_accepted():
    llm = _llm_returning('{"attendee_count": 25}')
    assert await extract_attendee_count("约 25 人", llm=llm) == 25


async def test_ai_string_number_is_coerced():
    llm = _llm_returning('{"attendeeCount": "30"}')
    assert await extract_attendee_count("三十来号人", llm=llm) == 30


async def test_ai_null_falls_back_to_regex():
    llm = _llm_returning('{"attendeeCount": null}')
    assert await extract_attendee_count("预计 18 人参加", llm=llm) == 18


async def test_ai_irrelevant_payload_falls_back_to_regex():
    llm = _llm_returning('{"remark": "信息不足"}')
    assert await extract_attendee_count("大概 15 人", llm=llm) == 15


# ---------- 降级：任何失败都静默交给正则 ----------


async def test_api_error_falls_back_to_regex(raising_llm):
    assert await extract_attendee_count("预计 22 人", llm=raising_llm) == 22


async def test_timeout_falls_back_to_regex(slow_llm):
    assert await extract_attendee_count("预计 33 人", llm=slow_llm, timeout=0.05) == 33


async def test_garbage_ai_output_falls_back_to_regex(fake_llm_broken):
    assert await extract_attendee_count("约有 12 人", llm=fake_llm_broken) == 12


async def test_ai_disabled_goes_straight_to_regex(monkeypatch, raising_llm):
    monkeypatch.setattr(settings, "AI_ENABLED", False)
    assert await extract_attendee_count("大概 40 人来", llm=raising_llm) == 40


# ---------- 全失败：返回 None，让容量规则自动跳过 ----------


async def test_no_number_anywhere_returns_none():
    llm = _llm_returning('{"attendeeCount": null}')
    assert await extract_attendee_count("周末办个小型交流活动", llm=llm) is None


async def test_empty_text_returns_none():
    assert await extract_attendee_count(None) is None
    assert await extract_attendee_count("") is None
    assert await extract_attendee_count("   ") is None


async def test_absurd_ai_value_is_discarded():
    """模型偶尔会给出离谱数值，宁可返回 None 也不让它触发误报"""
    llm = _llm_returning('{"attendeeCount": 999999}')
    assert await extract_attendee_count("人很多", llm=llm) is None


async def test_negative_ai_value_is_discarded():
    llm = _llm_returning('{"attendeeCount": -5}')
    assert await extract_attendee_count("人数待定", llm=llm) is None


async def test_boolean_ai_value_is_discarded():
    """bool 是 int 的子类，必须显式排除，否则 True 会变成 1 人"""
    llm = _llm_returning('{"attendeeCount": true}')
    value = await extract_attendee_count("人数待定", llm=llm)
    assert value is None


# ---------- 正则兜底本身 ----------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("预计 40 人", 40),
        ("40人参加", 40),
        ("大概 40 来人", 40),
        ("约 40 多号人", 40),
        ("四十人左右", 40),
        ("四十五人来参会", 45),
        ("二十来号人", 20),
        ("十几个人", None),  # 「十几」无法确定，不猜
        ("人数还没定", None),
        ("", None),
    ],
)
def test_regex_extraction(text, expected):
    assert extract_attendee_by_regex(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("十", 10),
        ("二十", 20),
        ("四十", 40),
        ("四十五", 45),
        ("一两", 12),
        ("", None),
        ("abc", None),
        ("二十X", None),
    ],
)
def test_chinese_numeral_conversion(text, expected):
    assert _chinese_to_int(text) == expected


def test_regex_picks_the_first_match():
    """
    取证：正则在「容量 + 人数」并存时无法区分，会取到第一次出现的数字。
    这个用例把该缺陷固定下来，提醒后来者不要指望正则处理这类原文。
    """
    assert extract_attendee_by_regex("200 人的大展厅，实际来 40 人") == 200


async def test_final_result_feeds_the_capacity_rule(now, make_order, make_context):
    """
    端到端闭环：抽取到的人数回填到订单快照后，容量规则才能命中。
    这条用例把「AI 富化 → 规则判定」两个阶段连起来验证。
    """
    from app.services.rules.capacity import CapacityOverflowRule

    llm = _llm_returning('{"attendeeCount": 12}')
    count = await extract_attendee_count("在展厅办个十来人的分享会", llm=llm)
    assert count == 12

    order = make_order(1, space_id=2, attendee_count=count)
    hits = CapacityOverflowRule().detect(make_context([order]))
    assert len(hits) == 1
    assert hits[0].facts["attendee_count"] == 12
