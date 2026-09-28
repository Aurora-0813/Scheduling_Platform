"""
③ 高价值设备被低优先级占用
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.services.rules.base import (
    ConflictRuleConfig,
    DeviceView,
    OrderView,
    RuleContext,
    SpaceView,
    UserView,
)
from app.services.rules.high_value import HighValueDeviceRule

NOW = datetime(2026, 9, 25, 10, 0)
SPACES = {1: SpaceView(id=1, space_name="A栋301会议室", space_type=1, capacity=20)}


def _rules():
    return HighValueDeviceRule()


def _ctx(orders, users, devices, *, config=None):
    return RuleContext(
        orders=tuple(orders),
        spaces=SPACES,
        devices=devices,
        users=users,
        now=NOW,
        config=config or ConflictRuleConfig(),
    )


DRONES = {2: DeviceView(id=2, device_name="无人机-1", device_type="无人机")}
PROJECTORS = {1: DeviceView(id=1, device_name="投影仪-1", device_type="投影仪")}
NORMAL_USER = {1: UserView(id=1, username="张三", role_id=1, role_name="普通使用者")}
ADMIN_USER = {2: UserView(id=2, username="李管理", role_id=2, role_name="资源管理员")}


def _order(device_ids, **kw):
    data = dict(
        id=1,
        user_id=1,
        space_id=1,
        start_time=NOW + timedelta(hours=2),
        end_time=NOW + timedelta(hours=3),
        order_status=2,
        device_ids=device_ids,
    )
    data.update(kw)
    return OrderView(**data)


def test_hit_when_normal_user_takes_high_value_device():
    hits = _rules().detect(_ctx([_order((2,))], NORMAL_USER, DRONES))

    assert len(hits) == 1
    hit = hits[0]
    assert hit.rule_code == "high_value_device_low_priority"
    assert hit.order_ids == (1,)
    assert hit.facts["device_name"] == "无人机-1"
    assert hit.facts["device_type"] == "无人机"
    assert hit.facts["user_role"] == "普通使用者"


def test_no_hit_for_ordinary_device():
    assert _rules().detect(_ctx([_order((1,))], NORMAL_USER, PROJECTORS)) == []


def test_no_hit_when_no_device_attached():
    """device_ids 为空元组是常见脏数据，不得崩溃"""
    assert _rules().detect(_ctx([_order(())], NORMAL_USER, DRONES)) == []


def test_no_hit_for_admin_user():
    """管理员自己用高价值设备属于合理分配"""
    order = _order((2,), user_id=2)
    assert _rules().detect(_ctx([order], ADMIN_USER, DRONES)) == []


def test_unknown_role_is_treated_as_normal():
    """
    角色查询不到时保守提醒 —— 宁可多提醒一次，也不漏报高价值资源占用
    """
    users = {1: UserView(id=1, username="张三", role_id=None, role_name=None)}
    hits = _rules().detect(_ctx([_order((2,))], users, DRONES))
    assert len(hits) == 1
    assert hits[0].facts["user_role"] == "普通使用者"


def test_missing_user_record_is_treated_as_normal():
    hits = _rules().detect(_ctx([_order((2,))], {}, DRONES))
    assert len(hits) == 1


def test_no_hit_for_finished_orders():
    """只关心尚未结束的占用"""
    order = _order(
        (2,), start_time=NOW - timedelta(hours=5), end_time=NOW - timedelta(hours=4)
    )
    assert _rules().detect(_ctx([order], NORMAL_USER, DRONES)) == []


def test_order_ending_exactly_now_still_counts():
    """边界：恰好在 now 结束算「未结束」，保守提醒"""
    order = _order((2,), start_time=NOW - timedelta(hours=1), end_time=NOW)
    assert len(_rules().detect(_ctx([order], NORMAL_USER, DRONES))) == 1


def test_two_high_value_devices_yield_two_hits():
    """一个订单占用两台高价值设备应产生两条，便于分别处置"""
    devices = {
        2: DeviceView(id=2, device_name="无人机-1", device_type="无人机"),
        3: DeviceView(id=3, device_name="直播推流机", device_type="直播设备"),
    }
    hits = _rules().detect(_ctx([_order((2, 3))], NORMAL_USER, devices))
    assert len(hits) == 2
    assert {h.facts["device_name"] for h in hits} == {"无人机-1", "直播推流机"}


def test_missing_device_record_is_skipped():
    """订单引用了已删除的设备 → 跳过，不猜"""
    assert _rules().detect(_ctx([_order((99,))], NORMAL_USER, DRONES)) == []


def test_device_without_type_is_skipped():
    devices = {2: DeviceView(id=2, device_name="未分类设备", device_type=None)}
    assert _rules().detect(_ctx([_order((2,))], NORMAL_USER, devices)) == []


def test_whitelist_comparison_is_whitespace_and_case_insensitive():
    """device_type 白名单比对要归一化，避免「无人机 」带空格漏判"""
    devices = {2: DeviceView(id=2, device_name="无人机-2", device_type=" 无人机 ")}
    assert len(_rules().detect(_ctx([_order((2,))], NORMAL_USER, devices))) == 1


def test_whitelist_is_configurable():
    """白名单来自配置，运维可随设备盘点调整"""
    cfg = ConflictRuleConfig(high_value_device_types=frozenset({"投影仪"}))
    hits = _rules().detect(_ctx([_order((1,))], NORMAL_USER, PROJECTORS, config=cfg))
    assert len(hits) == 1
