"""场地查询 service —— **桩函数**（阶段 3 任务 3-2）。

来源约定：流程文档阶段 3 §3.1「资源查询（模块 5）」｜负责人：杨睿坤。

本文件是为了让 Agent 链路不阻塞于模块 5 的进度而写的占位实现：**直接查库，
返回真实数据，但没有业务校验层**。数据是真的，规则是缺的。
"""
from __future__ import annotations

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.resource import SpaceResource

__all__ = ["query_spaces"]


def _to_dict(row: SpaceResource) -> dict:
    """ORM 行 → 传输结构。字段名用 camelCase，与主文档 6.2 及 TraceStep.observation 一致。"""
    return {
        "id": row.id,
        "spaceName": row.space_name,
        "spaceType": row.space_type,
        "capacity": row.capacity,
        "location": row.location,
        "budget": float(row.budget) if row.budget is not None else None,
        "openStartTime": row.open_start_time.strftime("%H:%M:%S") if row.open_start_time else None,
        "openEndTime": row.open_end_time.strftime("%H:%M:%S") if row.open_end_time else None,
        "status": row.status,
    }


async def query_spaces(capacity: int, space_type: int, start_time: str, end_time: str) -> dict:
    """[桩] 场地查询：按容量下限与类型检索可用场地。

    TODO(杨睿坤): 替换为模块 5 的真实资源查询 service，替换时只换函数体。
    签名未锁定,可能与真实 service 不一致,替换时需核对。

    参数：
        capacity:   容量下限（人）。取「容纳人数 ≥ 该值」。
        space_type: 场地类型，**INT 字典**（主文档 6.3）：1会议室 2展厅 3多功能厅 4户外场地。
                    自然语言到数字的映射由 Prompt 层给出对照表（阶段 4 §3.2），此处不猜。
        start_time: 需求开始时间，`YYYY-MM-DD HH:mm:ss`。
        end_time:   需求结束时间，同格式。

    返回：
        {"count": int, "spaces": [ {id, spaceName, spaceType, capacity,
                                   location, budget, openStartTime, openEndTime, status} ]}

    ⚠️ 桩的已知缺口（替换时必须补上）：
        1. `start_time` / `end_time` 当前**只收不用**——本桩不做「该时段是否已被占用」
           的重叠过滤。这正是「没有业务校验层」的含义：真实 service 必须按 5.5 的口径
           排除 `reserve_order` 中 `order_status IN (1,2)` 且时段重叠的场地。
           不加这一步，Agent 会把已订出去的场地排进方案。
        2. 未过滤 `open_start_time`/`open_end_time` 的开放时段边界。
    """
    stmt = (
        select(SpaceResource)
        .where(
            SpaceResource.status == 1,
            SpaceResource.space_type == space_type,
            SpaceResource.capacity >= capacity,
        )
        .order_by(SpaceResource.capacity)
    )
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(stmt)).scalars().all()
    return {"count": len(rows), "spaces": [_to_dict(r) for r in rows]}
