"""
模型包初始化
把所有模型导入这里，Alembic 才能发现它们
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