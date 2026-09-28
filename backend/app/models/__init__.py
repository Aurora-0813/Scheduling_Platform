"""
模型包初始化
把所有模型导入这里，Alembic 才能发现它们
"""

from app.models.inspection import InspectRecord, RepairTicket
from app.models.notification import NotifyMessage
from app.models.reservation import ReserveOrder
from app.models.resource import DeviceResource, SpaceResource
from app.models.system import SysPermission, SysRole, SysUser

__all__ = [
    "SysUser",
    "SysRole",
    "SysPermission",
    "SpaceResource",
    "DeviceResource",
    "ReserveOrder",
    "InspectRecord",
    "RepairTicket",
    "NotifyMessage",
]
