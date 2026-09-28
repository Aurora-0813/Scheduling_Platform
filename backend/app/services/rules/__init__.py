"""
软冲突规则引擎

开发流程.md 4.4 模块7 明确区分两类冲突：
- 硬冲突（同一场地同时段重复预约）：由后端事务 + idx_space_time 兜底，不在本包内
- 软冲突（同用户连续活动无休息、高价值设备被低优先级占用、容量远超需求等）：AI 扫描

本包内的规则 detect() 全部是同步纯函数，输入为不可变快照，不碰数据库也不碰 LLM。
"""
from app.services.rules.base import (
    AUDIENCE_ADMIN_ONLY,
    AUDIENCE_OWNER_AND_ADMIN,
    ConflictRuleConfig,
    DeviceView,
    OrderView,
    RuleContext,
    RuleHit,
    SoftConflictRule,
    SpaceView,
    UserView,
    fmt_dt,
)
from app.services.rules.registry import RULES, run_all

__all__ = [
    "AUDIENCE_ADMIN_ONLY",
    "AUDIENCE_OWNER_AND_ADMIN",
    "ConflictRuleConfig",
    "DeviceView",
    "OrderView",
    "RULES",
    "RuleContext",
    "RuleHit",
    "SoftConflictRule",
    "SpaceView",
    "UserView",
    "fmt_dt",
    "run_all",
]
