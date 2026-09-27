"""设备查询 service —— **桩函数**（阶段 3 任务 3-2）。

来源约定：流程文档阶段 3 §3.1「设备查询（模块 5）」｜负责人：杨睿坤。
"""
from __future__ import annotations

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.resource import DeviceResource

__all__ = ["query_devices"]


def _to_dict(row: DeviceResource) -> dict:
    """ORM 行 → 传输结构（camelCase）。"""
    return {
        "id": row.id,
        "deviceName": row.device_name,
        "deviceType": row.device_type,
        "deviceStatus": row.device_status,
        "totalCount": row.total_count,
        "availableCount": row.available_count,
    }


async def query_devices(device_type: str) -> dict:
    """[桩] 设备查询：按设备类型检索设备。

    TODO(杨睿坤): 替换为模块 5 的真实设备查询 service，替换时只换函数体。
    签名未锁定,可能与真实 service 不一致,替换时需核对。

    参数：
        device_type: 设备类型中文名，与 `device_resource.device_type` 存储值一致，
                     如 '投影仪' / '音响' / '显示屏' / '无人机' / '直播设备'。

    返回：
        {"count": int,
         "devices": [ {id, deviceName, deviceType, deviceStatus, totalCount, availableCount} ]}

    ⚠️ 关键设计：本桩**有意不在这里过滤可用性**，返回该类型的全部设备。

    按阶段 4 §3.2，`device_status=1 AND available_count>0` 这层过滤是 **Tool 层的责任**
    （「模型不该有机会看到不可用设备」）。如果桩提前滤掉，阶段 4 的 `AGENT-U-02`
    就无法证明 Tool 真的在过滤——因为无论如何结果里都不会有坏设备，用例会变成假绿。
    数据由种子脚本 `docs/seed.sql` 保证提供两个独立见证者：
        id=13 无人机02   ：deviceStatus=2 且 availableCount=1 → 只该被「状态」筛掉
        id=15 直播设备02 ：deviceStatus=1 且 availableCount=0 → 只该被「可用数」筛掉
    """
    stmt = (
        select(DeviceResource)
        .where(DeviceResource.device_type == device_type)
        .order_by(DeviceResource.id)
    )
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(stmt)).scalars().all()
    return {"count": len(rows), "devices": [_to_dict(r) for r in rows]}
