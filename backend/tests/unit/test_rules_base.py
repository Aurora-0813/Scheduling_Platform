"""
规则引擎的公共设施

`fmt_dt`、`normalize_token` 与 `RuleContext` 的名字查询是 5 条规则共用的地基。
它们各自只有一两行，但错了会让所有规则的 reason 文本一起出错 ——
而 reason 会直接进 AI 的 prompt 与模板的兜底文案。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.services.rules.base import (
    ConflictRuleConfig,
    DeviceView,
    RuleContext,
    SpaceView,
    UserView,
    fmt_dt,
    normalize_token,
)

NOW = datetime(2026, 9, 25, 10, 0)


def _context(**overrides) -> RuleContext:
    base = {
        "orders": (),
        "spaces": {1: SpaceView(id=1, space_name="A栋3楼展厅")},
        "devices": {7: DeviceView(id=7, device_name="无人机-1")},
        "users": {1: UserView(id=1, username="张三")},
        "now": NOW,
    }
    base.update(overrides)
    return RuleContext(**base)


# ---------- fmt_dt ----------


def test_fmt_dt_renders_a_full_timestamp():
    assert fmt_dt(NOW) == "2026-09-25 10:00"


def test_fmt_dt_renders_only_the_clock_when_asked():
    assert fmt_dt(NOW, with_date=False) == "10:00"


def test_fmt_dt_maps_none_to_an_empty_string():
    """★ 时间缺失时要给空串而不是抛异常：模板占位符会直接用它拼接"""
    assert fmt_dt(None) == ""
    assert fmt_dt(None, with_date=False) == ""


# ---------- normalize_token ----------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("无人机", "无人机"),
        ("  无人机 ", "无人机"),
        ("DRONE", "drone"),
        ("dRoNe", "drone"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_token_is_case_and_space_insensitive(raw, expected):
    """白名单比对靠它：设备类型写成 DRONE 不该逃过高价值设备规则"""
    assert normalize_token(raw) == expected


# ---------- RuleContext 的名字查询 ----------


def test_space_name_resolves_from_the_snapshot():
    assert _context().space_name(1) == "A栋3楼展厅"


def test_space_name_gives_a_readable_placeholder_for_an_unknown_id():
    """场地被删了也要能生成文案，不能让规则在组装 reason 时崩掉"""
    assert _context().space_name(999) == "场地#999"


def test_space_name_maps_none_to_an_empty_string():
    assert _context().space_name(None) == ""


def test_user_name_resolves_from_the_snapshot():
    assert _context().user_name(1) == "张三"


def test_user_name_gives_a_readable_placeholder_for_an_unknown_id():
    assert _context().user_name(999) == "用户#999"


def test_user_name_maps_none_to_an_empty_string():
    assert _context().user_name(None) == ""


# ---------- 阈值快照 ----------


def test_config_defaults_are_self_contained():
    """测试可以只构造 ConflictRuleConfig()，不读 .env"""
    cfg = ConflictRuleConfig()

    assert cfg.continuous_gap_minutes > 0
    assert cfg.capacity_ratio > 1
    assert cfg.idle_days > 0
    assert cfg.normal_role_names, "普通使用者白名单不能为空，否则高价值设备规则永不命中"


def test_config_from_settings_matches_the_application_settings():
    from app.core.config import settings

    cfg = ConflictRuleConfig.from_settings()

    assert cfg.continuous_gap_minutes == settings.CONFLICT_CONTINUOUS_GAP_MINUTES
    assert cfg.high_value_device_types == settings.high_value_device_types
    assert cfg.normal_role_names == settings.normal_role_names
    assert cfg.idle_days == settings.CONFLICT_IDLE_DAYS


def test_context_snapshots_are_immutable():
    """★ 快照不可变是这个模块的结构性前提：规则改不动它，也就不会互相污染"""
    ctx = _context()

    with pytest.raises(Exception):
        ctx.now = datetime(2030, 1, 1)  # type: ignore[misc]
