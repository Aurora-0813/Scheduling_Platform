"""
冲突扫描响应模型

契约（开发流程.md 5.3 模块7）：
GET /api/v1/conflicts/scan → [ { "conflictType": "软冲突", "orderIds": [1,2], "suggestion": "..." } ]
"""
from __future__ import annotations

from pydantic import Field

from app.schemas.common import CamelModel

# 契约锁定的冲突类别。硬冲突由后端事务兜底（开发流程.md 4.4 模块7），
# 本模块只产出软冲突，故此值恒定。
CONFLICT_TYPE_SOFT = "软冲突"


class ConflictItem(CamelModel):
    """单条冲突扫描结果"""

    conflict_type: str = Field(
        default=CONFLICT_TYPE_SOFT,
        description="冲突类别，本模块恒为「软冲突」",
    )
    order_ids: list[int] = Field(
        default_factory=list,
        description="关联订单ID；长期闲置类冲突无关联订单，返回空数组",
    )
    suggestion: str = Field(description="AI 生成的处置建议")

    # 契约追加字段（追加式变更，不破坏既有消费方）。
    # conflictType 是类别不是规则名，前端要按规则分色/分组必须有它。
    rule_code: str = Field(
        description="规则内部编码，如 continuous_activity / space_idle",
    )

    # ---- 以下为 2026-10-10 追加：让每条冲突**可被区分** ----
    #
    # ⚠️ 为什么必须加（真实反馈：「软冲突有那么多一样的」）：
    #   规则是「**一个闲置场地一条**」——8 个场地里 7 个闲置就产 7 条。
    #   但原先响应只有 conflictType / orderIds / suggestion / ruleCode 四个字段，
    #   而闲置冲突的 orderIds 恒为空数组、suggestion 又是**按 ruleCode 查表的
    #   固定模板**（`suggest_for` 不看具体是哪条 hit）——
    #   于是 7 条在响应里**逐字段完全相同**，前端只能显示 7 条无差别条目。
    #   数据本来就存在 `RuleHit` 里（`space_id` / `reason` / `rule_label` /
    #   `severity`），只是组装响应时没往外传。
    #
    # ⚠️ 改动是**纯追加**：不改任何既有字段名与语义，老消费方不受影响。
    rule_label: str = Field(
        default="",
        description="规则中文名，如「长期闲置」；前端可直接当分组标题",
    )
    space_id: int | None = Field(
        default=None,
        description="涉及的场地ID；长期闲置类冲突靠它区分（无关联订单时用）",
    )
    reason: str = Field(
        default="",
        description="事实陈述（含场地名等上下文），与 suggestion 的建议分开",
    )
    severity: str = Field(
        default="medium",
        description="严重程度：low / medium / high",
    )
