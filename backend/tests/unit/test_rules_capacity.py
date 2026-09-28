"""
② 容量远超需求
"""
from __future__ import annotations

from datetime import datetime

from app.services.rules.base import (
    ConflictRuleConfig,
    RuleContext,
    SpaceView,
    UserView,
)
from app.services.rules.capacity import CapacityOverflowRule

NOW = datetime(2026, 9, 25, 10, 0)
USERS = {1: UserView(id=1, username="张三", role_name="普通使用者")}


def _rules():
    return CapacityOverflowRule()


def _ctx(orders, spaces, *, config=None):
    return RuleContext(
        orders=tuple(orders),
        spaces=spaces,
        devices={},
        users=USERS,
        now=NOW,
        config=config or ConflictRuleConfig(),
    )


def test_hit_when_capacity_far_exceeds_need(now, make_order, make_context):
    order = make_order(1, space_id=2, attendee_count=12)  # 展厅 40 人 / 需求 12 人
    hits = _rules().detect(make_context([order]))

    assert len(hits) == 1
    hit = hits[0]
    assert hit.rule_code == "capacity_overflow"
    assert hit.order_ids == (1,)
    assert hit.facts["capacity"] == 40
    assert hit.facts["attendee_count"] == 12
    assert hit.facts["ratio"] == 3.33


def test_hit_when_capacity_exactly_at_ratio(now, make_order):
    """
    边界：容量恰为人数的 capacity_ratio 倍时**命中**
    （契约口径为 capacity >= attendee * ratio，含等号）
    """
    order = make_order(1, space_id=1, attendee_count=10)
    ctx = _ctx([order], {1: SpaceView(id=1, space_name="A栋301会议室", capacity=30)})
    assert len(_rules().detect(ctx)) == 1


def test_no_hit_one_person_above_the_ratio(now, make_order):
    """边界：人数再多 1 人，容量就不再是 3 倍，不命中"""
    order = make_order(1, space_id=1, attendee_count=11)
    ctx = _ctx([order], {1: SpaceView(id=1, space_name="A栋301会议室", capacity=30)})
    assert _rules().detect(ctx) == []


def test_no_hit_when_absolute_gap_too_small(now, make_order, make_context):
    """
    双条件防护：20 人间 4 人用（恰好 5 倍）但绝对差只有 16…… 这里换成小场地看差值条件。
    场地 20 人 / 需求 11 人 → 20 < 11*3=33，倍数条件先挡住。
    """
    order = make_order(1, space_id=1, attendee_count=11)
    assert _rules().detect(make_context([order])) == []


def test_no_hit_when_only_absolute_gap_is_met(now, make_order):
    """倍数达标但差值不足 → 不命中（12 人间 1 人用只差 11，若阈值调高则应被挡住）"""
    cfg = ConflictRuleConfig(capacity_min_abs_gap=20)
    order = make_order(1, space_id=1, attendee_count=1)
    ctx = _ctx(
        [order],
        {1: SpaceView(id=1, space_name="A栋301会议室", capacity=12)},
        config=cfg,
    )
    assert _rules().detect(ctx) == []


def test_small_space_is_protected_by_min_capacity(now, make_order):
    """
    容量下限防护：小场地即使倍数与差值都超标也不提醒，
    避免「6 人间 1 人用」这类无意义打扰。
    """
    cfg = ConflictRuleConfig(
        capacity_ratio=1.0, capacity_min_abs_gap=1, capacity_min_capacity=10
    )
    order = make_order(1, space_id=1, attendee_count=1)
    ctx = _ctx(
        [order],
        {1: SpaceView(id=1, space_name="小洽谈间", capacity=6)},
        config=cfg,
    )
    assert _rules().detect(ctx) == []


def test_finished_orders_are_not_reported(now, make_order, make_context):
    """已结束的预约再提醒「容量浪费」没有意义，只会打扰用户"""
    from datetime import timedelta

    order = make_order(
        1,
        space_id=2,
        attendee_count=5,
        start=NOW - timedelta(hours=5),
        end=NOW - timedelta(hours=4),
    )
    assert _rules().detect(make_context([order])) == []


def test_order_ending_exactly_now_still_counts(now, make_order, make_context):
    """边界：恰好在 now 结束算「尚未结束」，保留提醒"""
    from datetime import timedelta

    order = make_order(
        1, space_id=2, attendee_count=5, start=NOW - timedelta(hours=1), end=NOW
    )
    assert len(_rules().detect(make_context([order]))) == 1


def test_skips_when_attendee_count_missing(now, make_order, make_context):
    """人数抽取不到就跳过 —— 不做猜测，这是 AI 富化失败的正常路径"""
    order = make_order(1, space_id=2, attendee_count=None)
    assert _rules().detect(make_context([order])) == []


def test_skips_when_attendee_count_is_zero_or_negative(now, make_order, make_context):
    for count in (0, -3):
        order = make_order(1, space_id=2, attendee_count=count)
        assert _rules().detect(make_context([order])) == []


def test_skips_when_space_is_missing(now, make_order, make_context):
    """场地被删除时不能崩，也不能按未知容量报警"""
    order = make_order(1, space_id=999, attendee_count=2)
    assert _rules().detect(make_context([order])) == []


def test_agent_request_alone_is_not_enough(now, make_order, make_context):
    """原始文本留在订单上，但未经 AI 抽取回填 attendee_count 时规则不得自行解析"""
    order = make_order(1, space_id=2, agent_request="大概来十来个人", attendee_count=None)
    assert _rules().detect(make_context([order])) == []


def test_reason_contains_no_placeholder_leak(now, make_order, make_context):
    order = make_order(1, space_id=2, attendee_count=5)
    hit = _rules().detect(make_context([order]))[0]
    assert "A栋3楼展厅" in hit.reason
    assert "None" not in hit.reason
