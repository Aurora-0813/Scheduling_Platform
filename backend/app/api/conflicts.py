"""AI 冲突预警扫描（§5.3 模块7）：GET /api/v1/conflicts/scan。

说明：冲突预警属「AI 冲突预警与智能通知」模块（业务中台组），此处提供扫描接口
作为联调对接点；创建接口已硬编码拦截冲突，本接口兜住其它路径写入的重叠数据。
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.response import ok
from ..models import ReserveOrder
from ..state_machine import OrderStatus

router = APIRouter(prefix="/conflicts", tags=["conflicts"])


@router.get("/scan")
async def conflict_scan(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ReserveOrder).where(
            ReserveOrder.order_status.in_(
                [OrderStatus.PENDING.value, OrderStatus.CONFIRMED.value]
            )
        )
    )
    active = result.scalars().all()
    results = []
    n = len(active)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = active[i], active[j]
            if (
                a.space_id == b.space_id
                and a.end_time > b.start_time
                and a.start_time < b.end_time
            ):
                results.append(
                    {
                        "conflictType": "时段重叠",
                        "orderIds": [a.id, b.id],
                        "suggestion": f"建议将预约 #{b.id} 调整至其他时段或更换场地",
                    }
                )
    return ok(results)
