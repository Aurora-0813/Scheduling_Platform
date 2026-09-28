"""预约订单：创建 / 列表 / 详情 / 确认 / 取消（§5.3 模块3）。

- POST /api/v1/orders/create、GET /api/v1/orders/my、PUT /api/v1/orders/{orderId}/cancel
  为契约接口；GET /{orderId}、PUT /{orderId}/confirm 为模块内补充（状态机走「已确认」必需）。
- 身份一律从 JWT 解析（§5.1），请求体不再携带 userId。
  依赖 `app.api.deps.get_current_user`（团队基础支撑的正式实现，返回 `CurrentUser`）；
  本模块曾用过一版读 `X-User-Id` 请求头的 mock，已随本轮重组删除 —— 那个头
  不在契约里，任何人改一个头就能变成别人。
- **归属校验逐条做**：详情/确认/取消三条都必须取「本人的单」（`_get_owned_order`），
  兼容路径 `GET /user/{userId}` 同样比对路径参数与当前身份。
  认证层只回答「你是谁」，回答不了「这单是不是你的」——只注入身份而不比对，
  等于任何人拿到别人的 orderId 就能读、能确认、能取消。越权一律 404，不泄露存在性。
"""
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.exceptions import (
    BizError,
    DeviceNotFoundError,
    OrderNotFoundError,
    OrderStatusConflictError,
    ParamInvalidError,
    ResourceConflictError,
    SpaceNotFoundError,
    UserNotFoundError,
)
from ..core.response import ok
from ..core.utils import format_time
from ..models import ReserveOrder
from ..schemas.order import OrderCreate
from ..services import order_service
from ..services.message_service import create_message
from ..state_machine import (
    OrderStatus,
    can_transition,
    release_occupancy,
    transition,
)
from .deps import CurrentUser, get_current_user

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


#: `services` 层返回的 `conflictType` -> 业务异常类。翻译只属于路由层：
#: services 层不认识 HTTP（§7.3），它只回结构化原因。
#:
#: 用异常类而不是裸 HTTP 状态码，是团队基线的口径（见 `docs/api.md` §1.4）：
#: HTTP 状态码与 5 位业务码都挂在异常类上，抛出去由统一异常处理器收口。
#: 直接 `raise HTTPException(404, ...)` 走的是另一条分支 —— 那条分支会用
#: `_STATUS_MESSAGES` 把 detail 覆盖成通用文案（`预约不存在` -> `接口或资源不存在`），
#: 前端拿不到具体原因。
_CONFLICT_ERRORS: dict[str, type[BizError]] = {
    "invalid_param": ParamInvalidError,        # 400 / 40001
    "time_conflict": ResourceConflictError,    # 409 / 40901
    "device_conflict": ResourceConflictError,  # 409 / 40901
}

#: `not_found` 的具体归属靠 `conflictDetail["target"]` 再细分 —— 同是 404，
#: 业务码不同（40401 用户 / 40402 场地 / 40403 设备 / 40404 订单），
#: 前端据此决定提示语与跳转，所以不能在路由层拍平成同一个 404。
_NOT_FOUND_ERRORS: dict[str, type[BizError]] = {
    "user": UserNotFoundError,      # 404 / 40401
    "space": SpaceNotFoundError,    # 404 / 40402
    "device": DeviceNotFoundError,  # 404 / 40403
}


def _error_for(result: dict) -> BizError:
    """把服务层的结构化失败翻译成业务异常（`§5.3` 模块3）。

    `reason` 原样作为 `message` 透传 —— 服务层写的都是面向用户的中文原因
    （「该时段已被占用」「设备 999 不存在」），是前端唯一能拿来提示用户的文本，
    不能在路由层被通用文案替换掉。
    """
    detail = result.get("conflictDetail") or {}
    if result["conflictType"] == "not_found":
        error_cls = _NOT_FOUND_ERRORS.get(detail.get("target"), OrderNotFoundError)
    else:
        # 未登记的 conflictType 一律按「调用方参数有问题」处理（400 / 40001）：
        # 这类失败只可能来自本模块自己的服务层，真出现说明是代码缺陷，
        # 但也没必要因此给用户一个 500。
        error_cls = _CONFLICT_ERRORS.get(result["conflictType"], ParamInvalidError)
    return error_cls(result["reason"])


async def _get_owned_order(db: AsyncSession, order_id: int, user_id: int) -> ReserveOrder:
    """取「当前用户自己的」订单；不存在、或不属于本人，一律 404。

    归属校验必须逐条做，不能靠认证层兜：`get_current_user` 只回答「你是谁」，
    回答不了「这单是不是你的」。拿着别人的 orderId 就能读、能确认、能取消 ——
    归属这一层只有本函数在守。

    用 404 而不是 403：403 等于承认「这单存在，只是不是你的」，攻击者可以据此
    枚举出全库有哪些订单。`messages.py::read_message` 对越权消息也是 404，两处
    口径必须一致（§5.1 身份一律从 JWT 解析）。
    """
    order = await db.get(ReserveOrder, order_id)
    if order is None or order.user_id != user_id:
        raise OrderNotFoundError("预约不存在")
    return order


@router.post("/create")
async def create_order(
    data: OrderCreate,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建预约（§5.3 模块3）——薄壳，校验与落单全在 `order_service.create_order`。

    这是本模块**唯一**的写入口：Agent 的 `lock_resources` Tool 调的是同一个函数
    （§4.3 / §9.3），所以手动预约与 Agent 自动预约共用同一套 §5.5 六步事务，
    不存在两份真值。路由只做两件事：把 JWT 里的身份传下去、把结构化结果翻译成
    HTTP 状态码。
    """
    result = await order_service.create_order(
        user_id=current.id,
        space_id=data.spaceId,
        device_ids=data.deviceIds,
        start_time=data.startTime,
        end_time=data.endTime,
        agent_request=data.agentRequest,
        agent_trace=data.agentTrace,
    )
    if not result["ok"]:
        raise _error_for(result)

    order = await db.get(ReserveOrder, result["orderId"])
    return ok(_order_out(order), "预约创建成功")


@router.get("/my")
async def list_my_orders(
    status: int | None = Query(default=None, description="状态筛选 1/2/3/4"),
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """当前用户预约列表（§5.3 模块3：GET /orders/my，身份从 JWT 解析）。"""
    q = select(ReserveOrder).where(ReserveOrder.user_id == current.id)
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
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """兼容旧路径的用户预约列表（保留以兼容历史客户端，契约以 `/my` 为准）。

    **路径参数只是历史包袱，身份仍然只认 JWT**（`§5.1`）：`userId` 与当前身份不符时
    返回 404，与详情 / 确认 / 取消三条同口径。

    这条原先**完全匿名** —— 连 `get_current_user` 都没有，任何人
    `GET /api/v1/orders/user/1` 就能读到 1 号用户的全部订单（含 `agent_request`
    原始需求文本）。比"少一层归属校验"更严重：它连"你是谁"都没问。
    `userId` 不在 `§5.3` 的契约清单里（契约只有 `/orders/my`），本模块内也没有
    任何客户端再走它，所以收紧不会破坏合法调用 —— 唯一被挡掉的用法就是跨用户读取。
    """
    if userId != current.id:
        raise OrderNotFoundError("预约不存在")
    q = select(ReserveOrder).where(ReserveOrder.user_id == userId)
    if status is not None:
        q = q.where(ReserveOrder.order_status == status)
    q = q.order_by(ReserveOrder.create_time.desc())
    result = await db.execute(q)
    orders = result.scalars().all()
    return ok([_order_out(o) for o in orders])


@router.get("/{orderId}")
async def get_order(
    orderId: int,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """订单详情（扩展）。仅限本人的单；他人单与不存在的单同样是 404。"""
    order = await _get_owned_order(db, orderId, current.id)
    return ok(_order_out(order))


@router.put("/{orderId}/confirm")
async def confirm_order(
    orderId: int,
    background_tasks: BackgroundTasks,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """确认预约（扩展，状态机 1→2）。仅限本人的单；触发「预约已确认」通知。"""
    order = await _get_owned_order(db, orderId, current.id)
    if not can_transition(order.order_status, OrderStatus.CONFIRMED):
        raise OrderStatusConflictError("当前状态不允许确认")

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
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """取消预约（契约）。仅限本人的单；取消「已确认」单时释放占用（§5.3 模块3）。"""
    order = await _get_owned_order(db, orderId, current.id)

    was_confirmed = order.order_status == OrderStatus.CONFIRMED.value
    if not can_transition(order.order_status, OrderStatus.CANCELLED):
        raise OrderStatusConflictError("当前状态不允许取消")

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
