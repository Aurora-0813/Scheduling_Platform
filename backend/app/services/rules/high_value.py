"""
③ 高价值设备被低优先级占用

高价值设备（无人机、直播设备、显示屏等）被普通使用者预约占用，
建议管理员复核资源分配的合理性。

「高价值」用 device_type 白名单判定（配置项，可随时调整），
不依赖设备表的价值字段 —— 避免为此发起 DDL 变更。
"""
from __future__ import annotations

import logging

from app.services.rules.base import (
    AUDIENCE_OWNER_AND_ADMIN,
    RuleContext,
    RuleHit,
    fmt_dt,
    normalize_token,
)

logger = logging.getLogger(__name__)


class HighValueDeviceRule:
    code = "high_value_device_low_priority"
    label = "高价值设备被低优先级占用"

    def detect(self, ctx: RuleContext) -> list[RuleHit]:
        hits: list[RuleHit] = []
        cfg = ctx.config
        high_value_types = {normalize_token(t) for t in cfg.high_value_device_types}
        normal_roles = {normalize_token(r) for r in cfg.normal_role_names}

        for order in ctx.orders:
            # 只关心尚未结束的占用
            if order.end_time < ctx.now:
                continue
            if not order.device_ids:
                continue

            user = ctx.users.get(order.user_id)
            role_name = user.role_name if user else None
            # 角色未知时保守视为普通使用者：宁可多提醒一次，也不漏报高价值资源占用
            if role_name is not None and normalize_token(role_name) not in normal_roles:
                continue

            for device_id in order.device_ids:
                device = ctx.devices.get(device_id)
                if device is None or not device.device_type:
                    continue
                if normalize_token(device.device_type) not in high_value_types:
                    continue

                user_name = ctx.user_name(order.user_id)
                space_name = ctx.space_name(order.space_id)

                hits.append(
                    RuleHit(
                        rule_code=self.code,
                        rule_label=self.label,
                        order_ids=(order.id,),
                        user_id=order.user_id,
                        space_id=order.space_id,
                        audience=AUDIENCE_OWNER_AND_ADMIN,
                        reason=(
                            f"高价值设备 {device.device_name}（{device.device_type}）"
                            f"被角色为「{role_name or '普通使用者'}」的 {user_name} 占用，"
                            f"使用时段 {fmt_dt(order.start_time)} 至 {fmt_dt(order.end_time)}，"
                            f"地点 {space_name}，订单 {order.id}。"
                        ),
                        facts={
                            "user_name": user_name,
                            "user_role": role_name or "普通使用者",
                            "space_name": space_name,
                            "device_name": device.device_name,
                            "device_type": device.device_type,
                            "start_time": fmt_dt(order.start_time),
                            "end_time": fmt_dt(order.end_time),
                            "start_hm": fmt_dt(order.start_time, with_date=False),
                            "order_id": order.id,
                            "order_ids_text": str(order.id),
                        },
                        severity="medium",
                    )
                )
        return hits
