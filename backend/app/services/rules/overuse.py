"""
④ 资源过度占用

同一场地单日累计占用时长超过阈值，说明该资源被长时间垄断。
"""
from __future__ import annotations

from datetime import date, datetime, time as dt_time, timedelta

from app.services.rules.base import (
    AUDIENCE_ADMIN_ONLY,
    OrderView,
    RuleContext,
    RuleHit,
)


def _merged_hours(orders: list[OrderView], day: date) -> float:
    """
    计算订单集合在指定自然日内的累计占用小时数。

    两处必须做对：
    1. 跨天订单按天切分，只统计落在当天的部分
    2. 先合并重叠区间再求和，否则时段重叠会被重复计时
    """
    day_start = datetime.combine(day, dt_time.min)
    day_end = day_start + timedelta(days=1)

    intervals: list[tuple[datetime, datetime]] = []
    for order in orders:
        start = max(order.start_time, day_start)
        end = min(order.end_time, day_end)
        if end > start:
            intervals.append((start, end))

    if not intervals:
        return 0.0

    intervals.sort()
    merged: list[tuple[datetime, datetime]] = [intervals[0]]
    for start, end in intervals[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    total_seconds = sum((end - start).total_seconds() for start, end in merged)
    return total_seconds / 3600


class SpaceOveruseRule:
    code = "space_overuse"
    label = "资源过度占用"

    def detect(self, ctx: RuleContext) -> list[RuleHit]:
        hits: list[RuleHit] = []
        cfg = ctx.config

        # 只看今天与明天：对历史做占用通知没有意义，只会刷屏
        today = ctx.now.date()
        focus_days = {today, today + timedelta(days=1)}

        groups: dict[tuple[int, date], list[OrderView]] = {}
        for order in ctx.orders:
            for day in focus_days:
                day_start = datetime.combine(day, dt_time.min)
                day_end = day_start + timedelta(days=1)
                # 与该自然日无交集
                if order.end_time <= day_start or order.start_time >= day_end:
                    continue
                groups.setdefault((order.space_id, day), []).append(order)

        for (space_id, day), orders in groups.items():
            if len(orders) < cfg.daily_occupy_min_orders:
                continue

            occupied_hours = _merged_hours(orders, day)
            if occupied_hours <= cfg.daily_occupy_hours:
                continue

            space_name = ctx.space_name(space_id)
            order_ids = tuple(sorted(order.id for order in orders))
            rounded = round(occupied_hours, 1)

            hits.append(
                RuleHit(
                    rule_code=self.code,
                    rule_label=self.label,
                    order_ids=order_ids,
                    space_id=space_id,
                    # 过度占用是运维视角的问题，不打扰普通用户
                    audience=AUDIENCE_ADMIN_ONLY,
                    reason=(
                        f"场地 {space_name} 在 {day.isoformat()} 当天累计被占用 "
                        f"{rounded} 小时，涉及 {len(orders)} 笔订单，"
                        f"超过单日 {cfg.daily_occupy_hours} 小时的占用上限，"
                        f"其他团队可能难以预约到该场地。"
                    ),
                    facts={
                        "space_name": space_name,
                        "date": day.isoformat(),
                        "occupied_hours": rounded,
                        "threshold_hours": cfg.daily_occupy_hours,
                        "order_count": len(orders),
                        "order_id": order_ids[0] if order_ids else None,
                        "order_ids_text": "、".join(str(i) for i in order_ids),
                    },
                    severity="medium",
                )
            )
        return hits
