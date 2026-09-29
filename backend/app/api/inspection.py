"""
模块 6：AI 智能巡检与维修工单 —— API 路由层

职责（§7.3）：路由层**只做三件事** —— 参数注入、调用服务、包装统一响应体。
任何业务逻辑、任何 SQL、任何 Prompt 都不允许出现在这里（都放在 inspect_service）。

三条契约（形状由 `app/api/v1/mock_data.py` 冻结，前端 `views/Inspect.vue` 已按它渲染）：
    POST /api/v1/inspect/submit              提交巡检照片
    GET  /api/v1/tickets/list                工单列表
    PUT  /api/v1/tickets/{ticketId}/status   处理工单

为什么没有统一的 router 前缀
--------------------------
本模块的路径跨两个前缀（`/inspect` 与 `/tickets`）。
写 `prefix="/inspect"` 就只能覆盖第一条；拆成两个 router 又会让"同一模块两边注册"。
因此这里**不设 prefix**、逐条写全路径 —— 与 `mock.py` 的做法一致。

安全（§5.1 / §9.1）：
    三条都挂 `get_current_user`，身份只从 JWT 解析。
    `inspectorId` / `handlerId` **一律不接受客户端传入** —— 若从 FormData 或 body 取，
    任何人都能伪造巡检人 / 处理人。
"""

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from langchain_core.language_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user
from app.core.database import get_db
from app.core.llm import get_vision_llm
from app.core.response import ApiResponse, success
from app.schemas.inspect import (
    InspectSubmitData,
    TicketListData,
    TicketStatusUpdate,
    TicketUpdatedData,
)
from app.services.inspect_service import list_tickets, submit_inspection, update_ticket_status

router = APIRouter(tags=["AI 智能巡检与维修工单（模块 6）"])


@router.post(
    "/inspect/submit",
    response_model=ApiResponse[InspectSubmitData],
    summary="提交巡检",
    response_description="AI 判定结果；判定异常时会同时生成维修工单",
)
async def submit_inspect(
    file: UploadFile = File(..., description="巡检照片，JPG/PNG/WEBP，≤5MB"),
    spaceId: int = Form(..., description="拍摄所在场地 ID"),
    db: AsyncSession = Depends(get_db),
    # 鉴权闸门：巡检人只从 JWT 取（§5.1）
    current_user: CurrentUser = Depends(get_current_user),
    # 模型以依赖形式注入 → 测试可用 app.dependency_overrides 整体换假模型
    llm: BaseChatModel = Depends(get_vision_llm),
):
    """
    上传一张巡检照片，AI 判定设备状况并落库。

    请求：multipart/form-data，字段 `file`（图片）+ `spaceId`（场地 ID）
    响应：`{deviceStatus, report, repairSuggestion, ticketId}`

    `ticketId` 为 `null` 表示**判定为完好或无法识别、没有建工单**，
    不是「接口失败」—— 与 `mock_data.INSPECT_SUBMIT` 的形状保持一致。
    """
    data = await submit_inspection(
        db,
        file=file,
        space_id=spaceId,
        inspector_id=current_user.id,
        llm=llm,
    )
    # 用不同的 message 区分「建了工单」与「没建」，前端可直接按 message 做提示分级
    message = "巡检完成，已生成维修工单" if data.ticketId else "巡检完成，未发现需处理的异常"
    return success(data, message=message)


@router.get(
    "/tickets/list",
    response_model=ApiResponse[TicketListData],
    summary="工单列表",
)
async def tickets_list(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    pageSize: int = Query(10, ge=1, le=100, description="每页条数"),
    status: int | None = Query(
        None, ge=1, le=3, description="按状态筛选：1 待处理 / 2 处理中 / 3 已完成；不传=全部"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """工单列表，倒序分页。`report` / `deviceStatus` 来自关联的巡检记录。"""
    return success(await list_tickets(db, page=page, page_size=pageSize, status=status))


@router.put(
    "/tickets/{ticketId}/status",
    response_model=ApiResponse[TicketUpdatedData],
    summary="处理工单",
)
async def ticket_status(
    ticketId: int,
    payload: TicketStatusUpdate,
    db: AsyncSession = Depends(get_db),
    # 处理人只从 JWT 取（§5.1）
    current_user: CurrentUser = Depends(get_current_user),
):
    """流转工单状态。处理人记为当前登录用户。"""
    data = await update_ticket_status(
        db,
        ticket_id=ticketId,
        status=payload.status,
        handler_id=current_user.id,
    )
    return success(data, message="工单已更新")

