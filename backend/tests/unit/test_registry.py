"""
规则注册表：条数、口径、以及「单条规则崩溃不得拖垮整体扫描」
"""
from __future__ import annotations

from app.services.rules import registry
from app.services.rules.base import RuleHit

EXPECTED_CODES = {
    "continuous_activity",
    "capacity_overflow",
    "high_value_device_low_priority",
    "space_overuse",
    "space_idle",
}


def test_registry_contains_exactly_the_five_soft_rules():
    assert {rule.code for rule in registry.RULES} == EXPECTED_CODES


def test_no_hard_conflict_detection_lives_here():
    """
    硬冲突（时段重叠）由预约事务 + idx_space_time 兜底，
    规则引擎里不得再出现一份时间重叠检测。
    """
    labels = " ".join(rule.label for rule in registry.RULES)
    assert "重叠" not in labels
    assert "冲突时段" not in labels


def test_run_all_collects_hits_from_every_rule(monkeypatch, make_context, make_order):
    class First:
        code = "first"
        label = "第一条"

        def detect(self, ctx):
            return [RuleHit(rule_code="first", rule_label="第一条", order_ids=(1,), reason="r1")]

    class Second:
        code = "second"
        label = "第二条"

        def detect(self, ctx):
            return [RuleHit(rule_code="second", rule_label="第二条", order_ids=(2,), reason="r2")]

    monkeypatch.setattr(registry, "RULES", (First(), Second()))
    hits = registry.run_all(make_context())

    assert [h.rule_code for h in hits] == ["first", "second"]


def test_run_all_survives_a_failing_rule(monkeypatch, make_context):
    """
    一条规则的边界问题绝不能让全部软冲突预警失效 ——
    这是本模块在演示现场最容易出事的地方。
    """

    class Boom:
        code = "boom"
        label = "会崩的规则"

        def detect(self, ctx):
            raise RuntimeError("模拟规则内部崩溃")

    class Good:
        code = "good"
        label = "正常规则"

        def detect(self, ctx):
            return [
                RuleHit(rule_code="good", rule_label="正常规则", order_ids=(1,), reason="ok")
            ]

    monkeypatch.setattr(registry, "RULES", (Boom(), Good()))
    hits = registry.run_all(make_context())

    assert [h.rule_code for h in hits] == ["good"]


def test_run_all_on_empty_context_does_not_raise(make_context):
    """空快照下不崩，且闲置规则应命中（夹具里三个场地都没有预约记录）"""
    hits = registry.run_all(make_context())
    assert {h.rule_code for h in hits} == {"space_idle"}


def test_rule_hits_are_immutable(make_context):
    """RuleHit 是冻结 dataclass，避免下游误改导致同一份快照被污染"""
    import dataclasses

    import pytest

    hit = registry.run_all(make_context())[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        hit.rule_code = "tampered"  # type: ignore[misc]
