"""预约状态机（核心亮点）。

业务写入必须经状态机，防止非法流转。状态为 INT 编码（§6.3）：
1待确认 / 2已确认 / 3已取消 / 4已完成。

    1待确认 ──确认──▶ 2已确认 ──完成──▶ 4已完成
        │                │
        └──取消──▶ 3已取消 ◀──取消──┘
"""
from enum import IntEnum
from typing import Dict, Set

from .core.exceptions import OrderStatusConflictError


class OrderStatus(IntEnum):
    PENDING = 1      # 待确认
    CONFIRMED = 2    # 已确认
    CANCELLED = 3    # 已取消
    COMPLETED = 4    # 已完成


# 合法流转表：from -> {to ...}
TRANSITIONS: Dict[int, Set[int]] = {
    OrderStatus.PENDING: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.COMPLETED, OrderStatus.CANCELLED},
    OrderStatus.COMPLETED: set(),   # 终态
    OrderStatus.CANCELLED: set(),   # 终态
}


class IllegalTransitionError(OrderStatusConflictError):
    """非法状态流转（`409` / `40903`，见 `docs/api.md` §1.4）。

    继承团队的业务异常基类，是为了让「万一绕过了 `can_transition` 前置校验」
    这条兜底路径也走统一响应体：抛裸 `Exception` 会被兜底处理器接成 `500`，
    而它本质是「当前状态不允许该操作」——是调用方可理解的冲突，不是服务端故障。
    `api/orders.py` 的三条写路径都先 `can_transition` 再 `transition`，故线上
    正常不会走到这里；这条继承关系保护的是将来新增调用方时忘写前置校验的情况。
    """

    pass


def can_transition(from_status: int, to_status: OrderStatus) -> bool:
    """校验 from -> to 是否合法。"""
    return int(to_status) in TRANSITIONS.get(int(from_status), set())


def transition(order, to_status: OrderStatus) -> None:
    """执行状态流转（只改 order_status 字段，由调用方 commit）。"""
    if not can_transition(order.order_status, to_status):
        raise IllegalTransitionError(f"非法状态流转: {order.order_status} -> {int(to_status)}")
    order.order_status = int(to_status)


def release_occupancy(order) -> None:
    """释放场地/设备占用（预留 hook）。

    取消「已确认」预约时触发；真实占用管理接入后在此实现通知/释放逻辑。
    """
    # TODO: 通知资源模块释放场地/设备占用
    pass  # pragma: no cover - 预留 hook，当前为空实现
