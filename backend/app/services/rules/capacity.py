"""
② 容量远超需求

预约人数远小于场地容量，造成空间浪费。

人数不来自数据库字段（reserve_order 没有人数列），而由 AI 从订单的
agent_request 原始需求文本中抽取后回填到 OrderView.attendee_count；
抽取不到时该规则自动跳过 —— 这正是「AI 负责软冲突」的体现。
"""
from __future__ import annotations

from app.services.rules.base import (
    AUDIENCE_OWNER_AND_ADMIN,
    RuleContext,
    RuleHit,
    fmt_dt,
)


class CapacityOverflowRule:
    code = "capacity_overflow"
    label = "容量远超需求"

    def detect(self, ctx: RuleContext) -> list[RuleHit]:
        hits: list[RuleHit] = []
        cfg = ctx.config

        for order in ctx.orders:
            # 人数未抽取到就跳过，不做猜测
            if order.attendee_count is None or order.attendee_count <= 0:
                continue

            # 只关心尚未结束的预约：对已经用完的场地提醒「容量浪费」既无意义也打扰用户，
            # 与「高价值设备」规则保持同一口径
            if order.end_time < ctx.now:
                continue

            space = ctx.spaces.get(order.space_id)
            if space is None or space.capacity < cfg.capacity_min_capacity:
                continue

            # 双条件：倍数与绝对差值都要超标。
            # 只卡倍数会让「8 人占 24 人间」这类小场地误报。
            if space.capacity < order.attendee_count * cfg.capacity_ratio:
                continue
            if space.capacity - order.attendee_count < cfg.capacity_min_abs_gap:
                continue

            ratio = round(space.capacity / order.attendee_count, 2)
            user_name = ctx.user_name(order.user_id)

            hits.append(
                RuleHit(
                    rule_code=self.code,
                    rule_label=self.label,
                    order_ids=(order.id,),
                    user_id=order.user_id,
                    space_id=order.space_id,
                    audience=AUDIENCE_OWNER_AND_ADMIN,
                    reason=(
                        f"订单 {order.id} 预约了 {space.space_name}（可容纳 "
                        f"{space.capacity} 人），但需求人数仅约 {order.attendee_count} 人，"
                        f"容量是需求的 {ratio} 倍，存在空间浪费。"
                    ),
                    facts={
                        "user_name": user_name,
                        "space_name": space.space_name,
                        "capacity": space.capacity,
                        "attendee_count": order.attendee_count,
                        "ratio": ratio,
                        "start_time": fmt_dt(order.start_time),
                        "end_time": fmt_dt(order.end_time),
                        "start_hm": fmt_dt(order.start_time, with_date=False),
                        "order_id": order.id,
                        "order_ids_text": str(order.id),
                    },
                    severity="low",
                )
            )
        return hits
