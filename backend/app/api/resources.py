"""资源查询与维护（§5.3 模块5）：场地/设备台账，供表单下拉与日期联动。

⚠️ **2026-09-29 补两条写接口**
--------------------------------
本文件原先**只有 GET**。而 `frontend/src/views/Resources.vue` 有「新增场地」与
「修改设备状态」两个按钮，调的是 `POST /resources/spaces` 与
`PUT /resources/devices/{deviceId}` —— 实测分别是 **405（只有 GET）** 与 **404**，
也就是那两个按钮点了就报错。本轮把后端补齐，而不是把按钮摘掉：
界面上已经设计好的功能不该因为后端漏了就当不存在。

请求体字段名以**真实表结构**为准（`spaceName` / `spaceType` 整数 / `deviceStatus`），
前端同步改成规范名 —— 理由见 `app/schemas/resource.py` 的文件头。
"""

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.exceptions import DeviceNotFoundError, SpaceNotFoundError
from ..core.response import ok
from ..core.utils import format_clock, format_time
from ..models import DeviceResource, ReserveOrder, SpaceResource
from ..schemas.resource import DeviceUpdate, SpaceCreate
from ..services import space_service
from .deps import CurrentUser, get_current_user

router = APIRouter(prefix="/resources", tags=["resources"])


def _space_out(s: SpaceResource) -> dict:
    return {
        "spaceId": s.id,
        "spaceName": s.space_name,
        "spaceType": s.space_type,
        "capacity": s.capacity,
        "location": s.location or "",
        "budget": float(s.budget) if s.budget is not None else 0.0,
        "openStartTime": format_clock(s.open_start_time),
        "openEndTime": format_clock(s.open_end_time),
        "status": s.status,
    }


def _device_out(d: DeviceResource) -> dict:
    return {
        "deviceId": d.id,
        "deviceName": d.device_name,
        "deviceType": d.device_type or "",
        "deviceStatus": d.device_status,
        "totalCount": d.total_count,
        "availableCount": d.available_count,
    }


def _booking_out(o: ReserveOrder) -> dict:
    """占用明细。**不给状态文案** —— 状态字典在小程序 utils/dict.js 与
    Web 端各有一份，后端再塞一份中文只会多一处要同步的地方。"""
    return {
        "orderId": o.id,
        "userId": o.user_id,
        "startTime": format_time(o.start_time),
        "endTime": format_time(o.end_time),
        "orderStatus": o.order_status,
        "deviceIds": o.device_ids or [],
    }


@router.get("/spaces")
async def list_spaces(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SpaceResource))
    spaces = result.scalars().all()
    return ok([_space_out(s) for s in spaces])


@router.get("/spaces/{spaceId}/booked")
async def space_bookings(
    spaceId: int,
    days: int = Query(7, ge=1, le=90, description="查询未来多少天，默认 7 天"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """某场地未来 N 天内**已被占用**的时段（2026-09-30 新增）。

    为什么需要它：
        小程序要能「选一个场地，看它哪些时间段已经被人订走了」。
        原有接口都答不了这个问题 —— `/orders/my` 只看得到自己的预约，
        `/orders/user/{userId}` 是按人查而不是按场地查，
        `/image/analyze` 回的 `availableTime` 语义是「**剩余空档**」，
        拿不到「被谁、在哪一段」占掉的信息。

    语义边界（与下单判重严格同源）：
        · 占用口径取 `OCCUPYING_STATUS`（1 待确认 / 2 已确认），
          与 `create_order`、`query_spaces` 完全一致 ——
          不会出现「这个接口说占了、下单却说没占」的自相矛盾。
        · 只返回与查询区间**有重叠**的订单，跨天占用原样返回，由前端决定怎么裁剪。
        · `bookings` 为空 = 该场地这段时间确实没人订，不是「查不到」。

    鉴权：需要登录。占用数据会暴露**他人**的预约时段，
    与只读的 `GET /spaces`（纯台账）不是一回事，所以这里挂了 `get_current_user`。
    """
    space = await db.get(SpaceResource, spaceId)
    if space is None:
        # 40402，与 inspect_service 的场地不存在同码
        raise SpaceNotFoundError("场地不存在")

    rows = await space_service.list_space_bookings(db, spaceId, days)

    return ok(
        {
            # 场地信息一并返回，前端不必再单独查一次 /resources/spaces
            "spaceId": space.id,
            "spaceName": space.space_name,
            "spaceType": space.space_type,
            "location": space.location or "",
            "capacity": space.capacity,
            # 开放时段：前端要拿它把「已占用」画在正确的刻度上
            "openStartTime": format_clock(space.open_start_time),
            "openEndTime": format_clock(space.open_end_time),
            "days": days,
            "count": len(rows),
            "bookings": [_booking_out(o) for o in rows],
        }
    )


@router.post("/spaces")
async def create_space(
    payload: SpaceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """新增场地。返回**新建行本身**（形状与 GET 一致），前端刷新即可看到。

    ⚠️ 刻意**不做重名校验**：表上没有唯一约束，业务方也没给过「同名场地算不算冲突」的口径。
    凭空加一条规则出来，会让「到底能不能建同名房间」变成代码说了算而不是业务说了算。
    真需要时由业务方定口径、再补约束与迁移。
    """
    space = SpaceResource(
        space_name=payload.spaceName,
        space_type=payload.spaceType,
        capacity=payload.capacity,
        location=payload.location,
        budget=payload.budget,
        open_start_time=payload.openStartTime,
        open_end_time=payload.openEndTime,
        status=payload.status,
    )
    db.add(space)
    await db.commit()
    await db.refresh(space)
    return ok(_space_out(space), "新增场地成功")


@router.get("/devices")
async def list_devices(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DeviceResource))
    devices = result.scalars().all()
    return ok([_device_out(d) for d in devices])


@router.put("/devices/{deviceId}")
async def update_device(
    deviceId: int,
    payload: DeviceUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """修改设备状态（1 完好 / 2 损坏 / 3 缺失配件）。

    只改 `device_status` 一列。**不联动 `available_count`** —— 那是有意为之：
    按既定口径 `available_count` 是「静态上限」，剩余量由订单按时段推导，
    「设备报损后库存字段未同步」正是种子里 id=13 刻意保留的数据状态
    （见 `docs/seed.sql` 第 4 节 b 条）。在这里顺手改它，等于把口径又搅乱一次。
    """
    device = await db.get(DeviceResource, deviceId)
    if device is None:
        raise DeviceNotFoundError("设备不存在")

    device.device_status = payload.deviceStatus
    await db.commit()
    await db.refresh(device)
    return ok(_device_out(device), "设备状态已更新")

