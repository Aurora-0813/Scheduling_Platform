"""
⑤ 长期闲置

启用状态的场地在最近 N 天内没有任何有效预约，属于资源浪费。
"""
from __future__ import annotations

from datetime import timedelta

from app.services.rules.base import (
    AUDIENCE_ADMIN_ONLY,
    RuleContext,
    RuleHit,
    fmt_dt,
)


class SpaceIdleRule:
    code = "space_idle"
    label = "长期闲置"

    def detect(self, ctx: RuleContext) -> list[RuleHit]:
        hits: list[RuleHit] = []
        idle_days = ctx.config.idle_days
        cutoff = ctx.now - timedelta(days=idle_days)

        for space in ctx.spaces.values():
            # 停用的场地不参与闲置判定
            if space.status != 1:
                continue

            last_at = ctx.space_last_order_at.get(space.id)
            if last_at is not None and last_at >= cutoff:
                continue

            last_text = fmt_dt(last_at) if last_at else "无预约记录"

            hits.append(
                RuleHit(
                    rule_code=self.code,
                    rule_label=self.label,
                    # 闲置冲突没有具体订单，contract 允许空数组
                    order_ids=(),
                    space_id=space.id,
                    audience=AUDIENCE_ADMIN_ONLY,
                    reason=(
                        f"场地 {space.space_name}（可容纳 {space.capacity} 人）"
                        f"在最近 {idle_days} 天内没有任何有效预约，"
                        f"最后一次使用时间为 {last_text}，资源处于闲置状态。"
                    ),
                    facts={
                        "space_name": space.space_name,
                        "capacity": space.capacity,
                        "idle_days": idle_days,
                        "last_order_time": last_text,
                        "order_ids_text": "",
                    },
                    severity="low",
                )
            )
        return hits
