"""
模型包初始化
把所有模型导入这里，Alembic 才能发现它们

文件与团队公用 `backend/app/models/` 一一对应（system / resource / reservation /
inspection / notification）。本模块原先把预约、通知拆在 `order.py`、`message.py`，
现已按团队命名合并到 `reservation.py`、`notification.py`。

`system` 与 `inspection` 由本模块一并注册：`reserve_order.user_id`、
`notify_message.receiver_id` 指向 `sys_user.id` 的真外键要求被引用表在 metadata 中，
且这样团队的 Alembic autogenerate 不会漏表。
"""
from app.models.system import SysUser, SysRole, SysPermission
from app.models.resource import SpaceResource, DeviceResource
from app.models.reservation import ReserveOrder
from app.models.inspection import InspectRecord, RepairTicket
from app.models.notification import NotifyMessage

__all__ = [
    "SysUser", "SysRole", "SysPermission",
    "SpaceResource", "DeviceResource",
    "ReserveOrder",
    "InspectRecord", "RepairTicket",
    "NotifyMessage",
]
