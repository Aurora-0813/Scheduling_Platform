"""资源查询（§5.3 模块5）：场地/设备，供表单下拉与日期联动。"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.response import ok
from ..core.utils import format_clock
from ..models import DeviceResource, SpaceResource

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


@router.get("/spaces")
async def list_spaces(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SpaceResource))
    spaces = result.scalars().all()
    return ok([_space_out(s) for s in spaces])


@router.get("/devices")
async def list_devices(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DeviceResource))
    devices = result.scalars().all()
    return ok([_device_out(d) for d in devices])
