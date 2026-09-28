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
