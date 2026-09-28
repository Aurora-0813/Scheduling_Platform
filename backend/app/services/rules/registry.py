"""
规则注册表

新增软冲突规则只需实现 detect() 并加入 RULES 元组，无需改动扫描编排逻辑。
"""
from __future__ import annotations

import logging

from app.services.rules.base import RuleContext, RuleHit, SoftConflictRule
from app.services.rules.capacity import CapacityOverflowRule
from app.services.rules.continuous import ContinuousActivityRule
from app.services.rules.high_value import HighValueDeviceRule
from app.services.rules.idle import SpaceIdleRule
from app.services.rules.overuse import SpaceOveruseRule

logger = logging.getLogger(__name__)

RULES: tuple[SoftConflictRule, ...] = (
    ContinuousActivityRule(),
    CapacityOverflowRule(),
    HighValueDeviceRule(),
    SpaceOveruseRule(),
    SpaceIdleRule(),
)


def run_all(ctx: RuleContext) -> list[RuleHit]:
    """
    逐条执行规则。

    单条规则内部崩溃只记日志并跳过，绝不让整个扫描失败 ——
    否则一条规则的边界问题会导致全部冲突预警失效。
    """
    hits: list[RuleHit] = []
    for rule in RULES:
        try:
            hits.extend(rule.detect(ctx))
        except Exception:
            logger.exception("软冲突规则执行失败，已跳过：%s", rule.code)
    return hits
