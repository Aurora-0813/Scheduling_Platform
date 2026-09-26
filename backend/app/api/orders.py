"""预约订单：创建 / 列表 / 详情 / 确认 / 取消（§5.3 模块3）。

- POST /api/v1/orders/create、GET /api/v1/orders/my、PUT /api/v1/orders/{orderId}/cancel
  为契约接口；GET /{orderId}、PUT /{orderId}/confirm 为模块内补充（状态机走「已确认」必需）。
- 身份一律从 JWT 解析（§5.1），请求体不再携带 userId。
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.deps import get_current_user
from ..core.response import ok
from ..core.utils import format_time, parse_time
from ..models import DeviceResource, ReserveOrder, SpaceResource
from ..schemas.order import OrderCreate
from ..services.message_service import create_message
from ..state_machine import (
    OrderStatus,
    can_transition,
    release_occupancy,
    transition,
)

router = APIRouter(prefix="/orders", tags=["orders"])


def _order_out(o: ReserveOrder) -> dict:
    """ORM -> camelCase 响应（§6.2）。"""
    return {
        "orderId": o.id,
        "userId": o.user_id,
        "spaceId": o.space_id,
        "deviceIds": o.device_ids or [],
        "startTime": format_time(o.start_time),
        "endTime": format_time(o.end_time),
        "orderStatus": o.order_status,
        "agentRequest": o.agent_request or "",
        "agentTrace": o.agent_trace or [],
        "createTime": format_time(o.create_time),
        "updateTime": format_time(o.update_time),
    }


async def _create_order(db: AsyncSession, user_id: int, data: OrderCreate) -> ReserveOrder:
    """创建预约核心逻辑（手动创建与 Agent 确认复用同一套校验）。"""
    # 场地/设备存在性校验（§9.3：后端二次校验，拒绝非法参数入库）
    if not await db.get(SpaceResource, data.spaceId):
        raise HTTPException(status_code=404, detail="场地不存在")
    for did in data.deviceIds:
        if not await db.get(DeviceResource, did):
            raise HTTPException(status_code=404, detail=f"设备 {did} 不存在")

    start = parse_time(data.startTime)
    end = parse_time(data.endTime)

    # 时间段冲突检测（硬编码兜底，防 Agent 幻觉）
    result = await db.execute(
        select(ReserveOrder)
        .where(
            ReserveOrder.space_id == data.spaceId,
            ReserveOrder.order_status.in_(
                [OrderStatus.PENDING.value, OrderStatus.CONFIRMED.value]
            ),
            ReserveOrder.end_time > start,
            ReserveOrder.start_time < end,
        )
        .limit(1)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="该时段已被占用")

    order = ReserveOrder(
        user_id=user_id,
        space_id=data.spaceId,
        device_ids=data.deviceIds,
        start_time=start,
        end_time=end,
        order_status=OrderStatus.PENDING.value,
        agent_request=data.agentRequest,
        agent_trace=data.agentTrace,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order


@router.post("/create")
async def create_order(
    data: OrderCreate,
    user_id: int = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order = await _create_order(db, user_id, data)
    return ok(_order_out(order), "预约创建成功")


@router.get("/my")
async def list_my_orders(
    status: int | None = Query(default=None, description="状态筛选 1/2/3/4"),
    user_id: int = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """当前用户预约列表（§5.3 模块3：GET /orders/my，身份从 JWT 解析）。"""
    q = select(ReserveOrder).where(ReserveOrder.user_id == user_id)
    if status is not None:
        q = q.where(ReserveOrder.order_status == status)
    q = q.order_by(ReserveOrder.create_time.desc())
    result = await db.execute(q)
    orders = result.scalars().all()
    return ok([_order_out(o) for o in orders])


@router.get("/user/{userId}")
async def list_orders(
    userId: int,
    status: int | None = Query(default=None, description="状态筛选 1/2/3/4"),
    db: AsyncSession = Depends(get_db),
):
    """兼容旧路径的用户预约列表（保留以兼容历史客户端，契约以 /my 为准）。"""
    q = select(ReserveOrder).where(ReserveOrder.user_id == userId)
    if status is not None:
        q = q.where(ReserveOrder.order_status == status)
    q = q.order_by(ReserveOrder.create_time.desc())
    result = await db.execute(q)
    orders = result.scalars().all()
    return ok([_order_out(o) for o in orders])


@router.get("/{orderId}")
async def get_order(orderId: int, db: AsyncSession = Depends(get_db)):
    order = await db.get(ReserveOrder, orderId)
    if not order:
        raise HTTPException(status_code=404, detail="预约不存在")
    return ok(_order_out(order))


@router.put("/{orderId}/confirm")
async def confirm_order(
    orderId: int,
    background_tasks: BackgroundTasks,
    user_id: int = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order = await db.get(ReserveOrder, orderId)
    if not order:
        raise HTTPException(status_code=404, detail="预约不存在")
    if not can_transition(order.order_status, OrderStatus.CONFIRMED):
        raise HTTPException(status_code=409, detail="当前状态不允许确认")

    transition(order, OrderStatus.CONFIRMED)
    await db.commit()
    await db.refresh(order)

    await create_message(
        db,
        order.user_id,
        "预约已确认",
        f"您的预约 #{order.id} 已确认",
        notify_type=1,
        order_id=order.id,
        background_tasks=background_tasks,
    )
    return ok(_order_out(order), "预约已确认")


@router.put("/{orderId}/cancel")
async def cancel_order(
    orderId: int,
    background_tasks: BackgroundTasks,
    user_id: int = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order = await db.get(ReserveOrder, orderId)
    if not order:
        raise HTTPException(status_code=404, detail="预约不存在")

    was_confirmed = order.order_status == OrderStatus.CONFIRMED.value
    if not can_transition(order.order_status, OrderStatus.CANCELLED):
        raise HTTPException(status_code=409, detail="当前状态不允许取消")

    transition(order, OrderStatus.CANCELLED)
    if was_confirmed:
        release_occupancy(order)  # 释放场地/设备占用（预留 hook）
    await db.commit()
    await db.refresh(order)

    await create_message(
        db,
        order.user_id,
        "预约已取消",
        f"您的预约 #{order.id} 已取消",
        notify_type=2,  # 变更致歉（§6.3）
        order_id=order.id,
        background_tasks=background_tasks,
    )
    return ok(_order_out(order), "预约已取消")
