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

from ..core.config import settings
from ..core.database import get_db
from ..core.exceptions import DeviceNotFoundError, SpaceNotFoundError
from ..core.response import ok
from ..core.utils import format_clock, format_time
from ..models import DeviceResource, ReserveOrder, SpaceResource
from ..schemas.resource import DeviceUpdate, SpaceCreate
from ..services import order_service, space_service
from .deps import CurrentUser, get_current_user

router = APIRouter(prefix="/resources", tags=["resources"])


def _space_out(s: SpaceResource, *, occupancy: str | None = None) -> dict:
    """
    场地 → 传输结构。

    `occupancyText` 是**推导值**（按活跃单的时段与当前时间算），说明见
    `app/services/space_service.py::space_occupancy`：
        "使用中"  有一条活跃单正在用
        "已被预约" 今天还有一条没开始的活跃单
        "空闲"    两者都不是

    ⚠️ 它与 `status`（1 可用 / 0 停用）**是两回事**：`status` 是「能不能借」
    的台账开关，由管理员维护，预约绝不改写它；`occupancyText` 只是显示层
    对「此刻有没有人在用」的推导。混为一谈会让被预约的场地从可用列表里消失。
    """
    status = s.status
    return {
        "spaceId": s.id,
        "spaceName": s.space_name,
        "spaceType": s.space_type,
        "capacity": s.capacity,
        "location": s.location or "",
        "budget": float(s.budget) if s.budget is not None else 0.0,
        "openStartTime": format_clock(s.open_start_time),
        "openEndTime": format_clock(s.open_end_time),
        "status": status,
        "statusText": "可用" if status == 1 else "停用",
        "occupancyText": occupancy or "空闲",
    }


def _device_out(d: DeviceResource, *, occupied: int = 0) -> dict:
    """
    设备 → 传输结构。

    `availableCount` 是**静态上限**；`remainingCount` 是推导出的实时剩余
    （上限 − 窗口内峰值占用，下限 0）。两者的分工见 `list_devices` 的 docstring。

    `occupied` 默认为 0：`PUT /devices/{id}` 改完状态后就地返回这一台，
    不为它单独再跑一次占用统计（那是一次全表范围查询，而单台设备的剩余量
    在改状态这个动作里不是关键信息）。
    """
    cap = d.available_count or 0
    return {
        "deviceId": d.id,
        "deviceName": d.device_name,
        "deviceType": d.device_type or "",
        "deviceStatus": d.device_status,
        "totalCount": d.total_count,
        "availableCount": cap,
        # max(0, ...) 是兜底：理论上峰值不会超过上限（下单会拒），
        # 但活跃单被人工改成上限以上的极端情况下，剩余量不该显示成负数。
        "remainingCount": max(0, cap - occupied),
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
    """
    场地台账。每行除「可用 / 停用」外，还带一个**推导出来的占用状态**。

    `status` / `statusText` 是台账开关（管理员维护，预约**不改写**它）；
    `occupancyText` 是「此刻有没有人在用」的推导（空闲 / 已被预约 / 使用中）。
    两个字段都有，是因为它们回答的是不同问题 —— 把占用写进 `status`
    会让被预约的场地从「可用场地」查询里消失（那 5 处查询都依赖它）。
    """
    spaces = (await db.execute(select(SpaceResource))).scalars().all()
    occupancy = await space_service.space_occupancy(db)
    return ok([_space_out(s, occupancy=occupancy.get(s.id)) for s in spaces])


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
    """
    设备台账。每台设备除静态字段外，还带一个**推导出来的实时剩余量**。

    `availableCount` 是**静态上限**（`device_resource.available_count`，按口径
    只读不写，见 `docs/available_count口径判据.md`）；`remainingCount` 才是
    「现在还能借几台」，由 `available_count − 窗口内峰值占用` 算出来。

    为什么两个都给：管理员维护的是上限，使用者关心的是剩余。只给上限会让人
    以为「建了单却不减」（这是真实反馈过的问题）；只给剩余又会让管理员
    无法在界面上看到、也无法维护那个上限。
    """
    devices = (await db.execute(select(DeviceResource))).scalars().all()
    occupied = await order_service.peak_device_occupancy(
        db, horizon_days=settings.DEVICE_REMAINING_HORIZON_DAYS
    )
    return ok([_device_out(d, occupied=occupied.get(d.id, 0)) for d in devices])


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
