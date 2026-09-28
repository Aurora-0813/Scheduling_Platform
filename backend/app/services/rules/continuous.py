"""
① 连续活动无休息

同一预约人的两场活动之间没有留出休息与转场时间。
"""
from __future__ import annotations

from app.services.rules.base import (
    AUDIENCE_OWNER_AND_ADMIN,
    OrderView,
    RuleContext,
    RuleHit,
    fmt_dt,
)


class ContinuousActivityRule:
    code = "continuous_activity"
    label = "连续活动无休息"

    def detect(self, ctx: RuleContext) -> list[RuleHit]:
        hits: list[RuleHit] = []
        gap_limit = ctx.config.continuous_gap_minutes

        by_user: dict[int, list[OrderView]] = {}
        for order in ctx.orders:
            by_user.setdefault(order.user_id, []).append(order)

        for user_id, orders in by_user.items():
            ordered = sorted(orders, key=lambda o: (o.start_time, o.id))
            for prev, nxt in zip(ordered, ordered[1:]):
                # 只看未来，避免对历史订单反复报警
                if nxt.start_time < ctx.now:
                    continue
                # 同一场地紧邻排期视为同一场活动的连续使用，不算冲突
                if prev.space_id == nxt.space_id:
                    continue

                gap_minutes = (nxt.start_time - prev.end_time).total_seconds() / 60
                # gap < 0 属于时段重叠，那是硬冲突，由后端事务兜底，不在本引擎职责内
                if not (0 <= gap_minutes < gap_limit):
                    continue

                prev_space = ctx.space_name(prev.space_id)
                next_space = ctx.space_name(nxt.space_id)
                user_name = ctx.user_name(user_id)
                gap = round(gap_minutes)

                hits.append(
                    RuleHit(
                        rule_code=self.code,
                        rule_label=self.label,
                        order_ids=(prev.id, nxt.id),
                        user_id=user_id,
                        space_id=nxt.space_id,
                        audience=AUDIENCE_OWNER_AND_ADMIN,
                        reason=(
                            f"预约人 {user_name} 的上一场活动在 {prev_space} 至 "
                            f"{fmt_dt(prev.end_time)} 结束，下一场在 {next_space} "
                            f"{fmt_dt(nxt.start_time)} 开始，中间仅有 {gap} 分钟，"
                            f"没有休息与转场时间。"
                        ),
                        facts={
                            "user_name": user_name,
                            "space_name": next_space,
                            "prev_space": prev_space,
                            "next_space": next_space,
                            "gap_minutes": gap,
                            "prev_end": fmt_dt(prev.end_time),
                            "next_start": fmt_dt(nxt.start_time),
                            "start_time": fmt_dt(nxt.start_time),
                            "end_time": fmt_dt(nxt.end_time),
                            "start_hm": fmt_dt(nxt.start_time, with_date=False),
                            "order_id": nxt.id,
                            "order_ids_text": f"{prev.id}、{nxt.id}",
                        },
                        severity="low",
                    )
                )
        return hits
