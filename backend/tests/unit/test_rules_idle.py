"""
⑤ 长期闲置
"""
from __future__ import annotations

from datetime import datetime

from app.services.rules.base import (
    AUDIENCE_ADMIN_ONLY,
    ConflictRuleConfig,
    RuleContext,
    SpaceView,
    UserView,
)
from app.services.rules.idle import SpaceIdleRule

NOW = datetime(2026, 9, 25, 10, 0)
# 14 天窗口的截止点：2026-09-11 10:00
CUTOFF = datetime(2026, 9, 11, 10, 0)


def _rules():
    return SpaceIdleRule()


def _ctx(spaces, last_order_at, *, config=None):
    return RuleContext(
        orders=(),
        spaces=spaces,
        devices={},
        users={1: UserView(id=1, username="张三")},
        now=NOW,
        config=config or ConflictRuleConfig(),
        space_last_order_at=last_order_at,
    )


SPACES = {
    1: SpaceView(id=1, space_name="A栋301会议室", capacity=20, status=1),
    2: SpaceView(id=2, space_name="A栋3楼展厅", capacity=40, status=1),
    3: SpaceView(id=3, space_name="B栋多功能厅", capacity=80, status=1),
}


def test_space_never_used_is_idle(make_context):
    """从未有预约记录的场地也是闲置的（模板里显示「无预约记录」）"""
    hits = _rules().detect(make_context(space_last_order_at={}))

    assert len(hits) == 3
    assert all(h.rule_code == "space_idle" for h in hits)
    assert hits[0].facts["last_order_time"] == "无预约记录"


def test_space_used_before_cutoff_is_idle():
    spaces = {1: SPACES[1]}
    hits = _rules().detect(_ctx(spaces, {1: datetime(2026, 9, 1, 9, 0)}))

    assert len(hits) == 1
    assert hits[0].facts["idle_days"] == 14
    assert hits[0].facts["last_order_time"] == "2026-09-01 09:00"
    assert "A栋301会议室" in hits[0].reason


def test_space_used_after_cutoff_is_not_idle():
    spaces = {1: SPACES[1]}
    assert _rules().detect(_ctx(spaces, {1: datetime(2026, 9, 20, 9, 0)})) == []


def test_boundary_exactly_at_cutoff_is_not_idle():
    """边界：恰好在 14 天前用过 → 不算闲置（判定为 last_at >= cutoff 即排除）"""
    spaces = {1: SPACES[1]}
    assert _rules().detect(_ctx(spaces, {1: CUTOFF})) == []


def test_boundary_one_second_before_cutoff_is_idle():
    """边界另一侧：早一秒就该命中"""
    spaces = {1: SPACES[1]}
    from datetime import timedelta

    hits = _rules().detect(_ctx(spaces, {1: CUTOFF - timedelta(seconds=1)}))
    assert len(hits) == 1


def test_disabled_space_is_skipped():
    """停用的场地不参与闲置判定，否则会被无意义地反复提醒"""
    spaces = {9: SpaceView(id=9, space_name="已停用库房", capacity=10, status=0)}
    assert _rules().detect(_ctx(spaces, {})) == []


def test_order_ids_is_empty_tuple():
    """闲置冲突没有具体订单，契约允许空数组"""
    spaces = {1: SPACES[1]}
    hit = _rules().detect(_ctx(spaces, {}))[0]
    assert hit.order_ids == ()
    assert hit.space_id == 1
    assert hit.user_id is None


def test_audience_is_admin_only():
    spaces = {1: SPACES[1]}
    hit = _rules().detect(_ctx(spaces, {}))[0]
    assert hit.audience == AUDIENCE_ADMIN_ONLY


def test_idle_days_is_configurable():
    """阈值可调：改成 3 天时，9-20 用过的场地也变成闲置"""
    cfg = ConflictRuleConfig(idle_days=3)
    spaces = {1: SPACES[1]}
    hits = _rules().detect(
        _ctx(spaces, {1: datetime(2026, 9, 20, 9, 0)}, config=cfg)
    )
    assert len(hits) == 1
    assert hits[0].facts["idle_days"] == 3


def test_no_spaces_is_safe():
    assert _rules().detect(_ctx({}, {})) == []
