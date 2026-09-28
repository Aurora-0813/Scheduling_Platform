"""
④ 资源过度占用

重点验证两处容易写错的地方：跨天订单按天切分、重叠区间先合并再求和。
"""
from __future__ import annotations

from datetime import date, datetime

from app.services.rules.base import AUDIENCE_ADMIN_ONLY
from app.services.rules.overuse import SpaceOveruseRule, _merged_hours

TODAY = date(2026, 9, 25)
TOMORROW = date(2026, 9, 26)


def _rules():
    return SpaceOveruseRule()


def _dt(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute)


def test_hit_when_daily_hours_exceed_threshold(now, make_order, make_context):
    a = make_order(1, space_id=1, start=_dt(TODAY, 8), end=_dt(TODAY, 13))
    b = make_order(2, space_id=1, start=_dt(TODAY, 13, 30), end=_dt(TODAY, 17, 30))

    hits = _rules().detect(make_context([a, b]))

    assert len(hits) == 1
    hit = hits[0]
    assert hit.rule_code == "space_overuse"
    assert hit.order_ids == (1, 2)
    assert hit.facts["date"] == "2026-09-25"
    assert hit.facts["occupied_hours"] == 9.0
    assert hit.facts["order_count"] == 2


def test_no_hit_when_exactly_at_threshold(now, make_order, make_context):
    """边界：恰好 8 小时不命中（判定为严格大于）"""
    a = make_order(1, space_id=1, start=_dt(TODAY, 8), end=_dt(TODAY, 12))
    b = make_order(2, space_id=1, start=_dt(TODAY, 12), end=_dt(TODAY, 16))
    assert _rules().detect(make_context([a, b])) == []


def test_overlapping_intervals_are_merged_before_summing(now, make_order, make_context):
    """
    8:00-14:00 与 10:00-12:00 若直接相加是 8 小时（会误报），
    合并后只有 6 小时 —— 这正是必须先去重叠的原因
    """
    a = make_order(1, space_id=1, start=_dt(TODAY, 8), end=_dt(TODAY, 14))
    b = make_order(2, space_id=1, start=_dt(TODAY, 10), end=_dt(TODAY, 12))
    assert _rules().detect(make_context([a, b])) == []


def test_cross_day_order_is_split_per_day(now, make_order, make_context):
    """
    跨天订单 20:00→次日 04:00 应只把当天那 4 小时计入 9-25。
    当天另一笔 08:00-13:00 占 5 小时，合计 9 小时 → 命中 9-25；
    9-26 只有这一笔（4 小时、1 笔订单）→ 不命中。
    """
    overnight = make_order(
        1, space_id=2, start=_dt(TODAY, 20), end=_dt(TOMORROW, 4)
    )
    daytime = make_order(2, space_id=2, start=_dt(TODAY, 8), end=_dt(TODAY, 13))

    hits = _rules().detect(make_context([overnight, daytime]))

    assert len(hits) == 1
    hit = hits[0]
    assert hit.facts["date"] == "2026-09-25"
    assert hit.facts["occupied_hours"] == 9.0
    assert hit.order_ids == (1, 2)


def test_single_long_order_does_not_hit(now, make_order, make_context):
    """单笔 12 小时不命中：判定的是「多笔订单长期垄断」而非单笔长订单"""
    order = make_order(1, space_id=1, start=_dt(TODAY, 8), end=_dt(TODAY, 20))
    assert _rules().detect(make_context([order])) == []


def test_orders_beyond_tomorrow_are_ignored(now, make_order, make_context):
    """只看今天与明天，对历史与远期做占用通知只会刷屏"""
    day = date(2026, 9, 28)
    a = make_order(1, space_id=1, start=_dt(day, 8), end=_dt(day, 14))
    b = make_order(2, space_id=1, start=_dt(day, 14), end=_dt(day, 20))
    assert _rules().detect(make_context([a, b])) == []


def test_yesterday_is_ignored(now, make_order, make_context):
    day = date(2026, 9, 24)
    a = make_order(1, space_id=1, start=_dt(day, 8), end=_dt(day, 14))
    b = make_order(2, space_id=1, start=_dt(day, 14), end=_dt(day, 20))
    assert _rules().detect(make_context([a, b])) == []


def test_a_day_with_no_overlap_contributes_zero(now, make_order, make_context):
    """
    ★ 与当天完全无交集的订单必须贡献 0 小时，且不能引发 IndexError。

    直接调 `_merged_hours` 而不是走 `detect()`：`detect` 在分组时已按
    第 70 行剔除了与当日无交集的订单，`intervals` 为空的分支从 `detect`
    走不到。但这层保护不能只靠调用方 —— 切分后区间为空时若继续走
    `merged[-1]`，任何绕过预过滤的直接调用都会当场崩。
    """
    # 9-24 22:00 → 9-25 01:00 对 9-26 完全没有交集
    crossing = make_order(
        1, space_id=1, start=_dt(date(2026, 9, 24), 22), end=_dt(TODAY, 1)
    )

    assert _merged_hours([crossing], TOMORROW) == 0.0
    # 同一笔订单对 9-25 有交集，只算落在 9-25 的那 1 小时
    assert _merged_hours([crossing], TODAY) == 1.0


def test_detect_ignores_an_order_that_only_touches_today(now, make_order, make_context):
    """跨天订单只覆盖了今天，就不该在明天的分组里出现"""
    crossing = make_order(
        1, space_id=1, start=_dt(date(2026, 9, 24), 22), end=_dt(TODAY, 1)
    )
    long_tomorrow = make_order(2, space_id=1, start=_dt(TOMORROW, 8), end=_dt(TOMORROW, 20))

    # 合并后：9-25 算 1 小时，9-26 算 12 小时但只有 1 笔订单
    assert _rules().detect(make_context([crossing, long_tomorrow])) == []


def test_tomorrow_is_in_scope(now, make_order, make_context):
    a = make_order(1, space_id=1, start=_dt(TOMORROW, 8), end=_dt(TOMORROW, 14))
    b = make_order(2, space_id=1, start=_dt(TOMORROW, 14), end=_dt(TOMORROW, 20))

    hits = _rules().detect(make_context([a, b]))

    assert len(hits) == 1
    assert hits[0].facts["date"] == "2026-09-26"


def test_spaces_are_grouped_separately(now, make_order, make_context):
    """
    四个场地各 6 小时：若按场地分组就是各自 6 小时（都不命中），
    若漏了分组而全部累加则会是 12 小时（误报）。
    """
    a = make_order(1, space_id=1, start=_dt(TODAY, 8), end=_dt(TODAY, 11))
    b = make_order(2, space_id=1, start=_dt(TODAY, 14), end=_dt(TODAY, 17))
    c = make_order(3, space_id=2, start=_dt(TODAY, 8), end=_dt(TODAY, 11))
    d = make_order(4, space_id=2, start=_dt(TODAY, 14), end=_dt(TODAY, 17))
    assert _rules().detect(make_context([a, b, c, d])) == []


def test_only_the_offending_space_is_reported(now, make_order, make_context):
    """一个场地超标不应连带另一个场地一起报"""
    a = make_order(1, space_id=1, start=_dt(TODAY, 8), end=_dt(TODAY, 13))
    b = make_order(2, space_id=1, start=_dt(TODAY, 13, 30), end=_dt(TODAY, 17, 30))
    c = make_order(3, space_id=2, start=_dt(TODAY, 8), end=_dt(TODAY, 11))
    d = make_order(4, space_id=2, start=_dt(TODAY, 14), end=_dt(TODAY, 17))

    hits = _rules().detect(make_context([a, b, c, d]))

    assert len(hits) == 1
    assert hits[0].space_id == 1


def test_touching_intervals_count_as_continuous(now, make_order, make_context):
    """8:00-12:00 与 12:00-16:30 首尾相接，合并后 8.5 小时 → 命中"""
    a = make_order(1, space_id=1, start=_dt(TODAY, 8), end=_dt(TODAY, 12))
    b = make_order(2, space_id=1, start=_dt(TODAY, 12), end=_dt(TODAY, 16, 30))

    hits = _rules().detect(make_context([a, b]))

    assert len(hits) == 1
    assert hits[0].facts["occupied_hours"] == 8.5


def test_audience_is_admin_only(now, make_order, make_context):
    """过度占用是运维视角的问题，不打扰普通用户"""
    a = make_order(1, space_id=1, start=_dt(TODAY, 8), end=_dt(TODAY, 13))
    b = make_order(2, space_id=1, start=_dt(TODAY, 13, 30), end=_dt(TODAY, 17, 30))
    hit = _rules().detect(make_context([a, b]))[0]
    assert hit.audience == AUDIENCE_ADMIN_ONLY
    assert hit.user_id is None


def test_order_ids_are_sorted(now, make_order, make_context):
    """orderIds 有稳定顺序，便于前端展示与指纹去重"""
    a = make_order(9, space_id=1, start=_dt(TODAY, 8), end=_dt(TODAY, 13))
    b = make_order(3, space_id=1, start=_dt(TODAY, 13, 30), end=_dt(TODAY, 17, 30))
    hit = _rules().detect(make_context([a, b]))[0]
    assert hit.order_ids == (3, 9)


def test_empty_snapshot_is_safe(make_context):
    assert _rules().detect(make_context()) == []
