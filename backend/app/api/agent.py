"""核心调度 Agent 联动入口（§5.3 模块4）：提交需求 → 方案；语音/图像占位上传。"""
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.deps import get_current_user
from ..core.response import ok
from ..models import ReserveOrder, SpaceResource
from ..schemas.agent import ScheduleRequest
from ..services.agent_client import (
    MOCK_SPACE_ID,
    recognize_image,
    schedule,
    transcribe_audio,
)
from ..state_machine import OrderStatus

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/schedule")
async def schedule_plan(
    data: ScheduleRequest,
    user_id: int = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """提交需求文本 → 调度 Agent（真实或 mock）→ 返回主/备方案 + 思考步骤。"""
    # 查询真实占用时段，供 mock 调度器避让（真实 Agent 则自行调 Tool 查询）
    result = await db.execute(
        select(ReserveOrder.start_time, ReserveOrder.end_time).where(
            ReserveOrder.order_status.in_(
                [OrderStatus.PENDING.value, OrderStatus.CONFIRMED.value]
            )
        )
    )
    occupied = result.all()  # [(start, end), ...] 只取时段两列，避免加载整行
    # mock 需要场地真实名称来填契约里的 spaceName，避免编造；真实 Agent 自行经 Tool 获取
    space = await db.get(SpaceResource, MOCK_SPACE_ID)
    data_out = schedule(
        data.text, occupied, space_name=space.space_name if space else None
    )  # {plan, backupPlan, trace, needConfirm}
    return ok(data_out)


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """语音转写占位：真实 ASR 由队友语音模块接入。"""
    text = transcribe_audio(await file.read())
    return ok({"text": text})


@router.post("/recognize")
async def recognize(file: UploadFile = File(...)):
    """图像多模态识别占位：真实识别由队友视觉模块接入。"""
    text = recognize_image(await file.read())
    return ok({"text": text})
