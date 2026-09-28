"""
① 连续活动无休息
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.services.rules.continuous import ContinuousActivityRule


def _rules():
    return ContinuousActivityRule()


def test_hit_when_gap_below_threshold(now, make_order, make_context):
    prev = make_order(1, start=now + timedelta(hours=2), end=now + timedelta(hours=3))
    nxt = make_order(
        2,
        user_id=1,
        space_id=2,
        start=now + timedelta(hours=3, minutes=8),
        end=now + timedelta(hours=4),
    )
    hits = _rules().detect(make_context([prev, nxt]))

    assert len(hits) == 1
    hit = hits[0]
    assert hit.rule_code == "continuous_activity"
    assert hit.order_ids == (1, 2)
    assert hit.facts["gap_minutes"] == 8
    assert hit.facts["prev_space"] == "A栋301会议室"
    assert hit.facts["next_space"] == "A栋3楼展厅"
    assert hit.facts["user_name"] == "张三"


def test_no_hit_when_gap_equals_threshold(now, make_order, make_context):
    """边界：gap 恰等于 15 分钟不命中（判定为严格小于）"""
    prev = make_order(1, start=now + timedelta(hours=2), end=now + timedelta(hours=3))
    nxt = make_order(
        2, space_id=2, start=now + timedelta(hours=3, minutes=15),
        end=now + timedelta(hours=4),
    )
    assert _rules().detect(make_context([prev, nxt])) == []


def test_hit_at_one_minute_below_threshold(now, make_order, make_context):
    prev = make_order(1, start=now + timedelta(hours=2), end=now + timedelta(hours=3))
    nxt = make_order(
        2, space_id=2, start=now + timedelta(hours=3, minutes=14),
        end=now + timedelta(hours=4),
    )
    assert len(_rules().detect(make_context([prev, nxt]))) == 1


def test_overlap_is_not_our_business(now, make_order, make_context):
    """gap < 0 是时段重叠（硬冲突），由预约事务兜底，规则引擎不得越权报警"""
    prev = make_order(1, start=now + timedelta(hours=2), end=now + timedelta(hours=4))
    nxt = make_order(
        2, space_id=2, start=now + timedelta(hours=3), end=now + timedelta(hours=5)
    )
    assert _rules().detect(make_context([prev, nxt])) == []


def test_same_space_is_not_a_conflict(now, make_order, make_context):
    """同一场地紧邻排期是同一场活动的连续使用，不算转场冲突"""
    prev = make_order(1, space_id=1, start=now + timedelta(hours=2),
                      end=now + timedelta(hours=3))
    nxt = make_order(2, space_id=1, start=now + timedelta(hours=3, minutes=5),
                     end=now + timedelta(hours=4))
    assert _rules().detect(make_context([prev, nxt])) == []


def test_past_orders_are_ignored(now, make_order, make_context):
    """只看未来：历史订单不反复报警"""
    prev = make_order(1, start=now - timedelta(hours=4), end=now - timedelta(hours=3))
    nxt = make_order(2, space_id=2, start=now - timedelta(hours=2, minutes=52),
                     end=now - timedelta(hours=2))
    assert _rules().detect(make_context([prev, nxt])) == []


def test_different_users_do_not_interfere(now, make_order, make_context):
    prev = make_order(1, user_id=1, start=now + timedelta(hours=2),
                      end=now + timedelta(hours=3))
    nxt = make_order(2, user_id=2, space_id=2,
                     start=now + timedelta(hours=3, minutes=5),
                     end=now + timedelta(hours=4))
    assert _rules().detect(make_context([prev, nxt])) == []


def test_cancelled_orders_never_reach_the_rule(now, make_order, make_context):
    """
    已取消订单在快照装载阶段就被过滤掉（ACTIVE_ORDER_STATUSES）。
    这里验证规则自身也不依赖该前提：传入状态 3 的订单仍应按时间判定，
    真正排除它的是 SQL 层，所以本用例只断言不会崩溃。
    """
    prev = make_order(1, status=3, start=now + timedelta(hours=2),
                      end=now + timedelta(hours=3))
    nxt = make_order(2, space_id=2, start=now + timedelta(hours=3, minutes=5),
                     end=now + timedelta(hours=4))
    assert len(_rules().detect(make_context([prev, nxt]))) == 1


def test_chain_of_three_orders_yields_two_hits(now, make_order, make_context):
    a = make_order(1, start=now + timedelta(hours=2), end=now + timedelta(hours=3))
    b = make_order(2, space_id=2, start=now + timedelta(hours=3, minutes=5),
                   end=now + timedelta(hours=4))
    c = make_order(3, space_id=3, start=now + timedelta(hours=4, minutes=6),
                   end=now + timedelta(hours=5))

    hits = _rules().detect(make_context([a, b, c]))

    assert len(hits) == 2
    assert hits[0].order_ids == (1, 2)
    assert hits[1].order_ids == (2, 3)


def test_unsorted_input_is_handled(now, make_order, make_context):
    """快照顺序不保证，规则内部必须自行排序"""
    prev = make_order(1, start=now + timedelta(hours=2), end=now + timedelta(hours=3))
    nxt = make_order(2, space_id=2, start=now + timedelta(hours=3, minutes=5),
                     end=now + timedelta(hours=4))
    assert len(_rules().detect(make_context([nxt, prev]))) == 1


def test_unknown_space_and_user_get_readable_placeholders(make_order, make_context):
    """场地被删除、用户被停用时文案不能出现 None"""
    prev = make_order(1, user_id=99, space_id=99,
                      start=datetime(2026, 9, 25, 12, 0),
                      end=datetime(2026, 9, 25, 13, 0))
    nxt = make_order(2, user_id=99, space_id=98,
                     start=datetime(2026, 9, 25, 13, 5),
                     end=datetime(2026, 9, 25, 14, 0))

    hits = _rules().detect(make_context([prev, nxt]))

    assert len(hits) == 1
    assert hits[0].facts["user_name"] == "用户#99"
    assert hits[0].facts["prev_space"] == "场地#99"
    assert "None" not in hits[0].reason
