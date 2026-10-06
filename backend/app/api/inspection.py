"""
模块 6：AI 智能巡检与维修工单 —— API 路由层

职责（§7.3）：路由层**只做三件事** —— 参数注入、调用服务、包装统一响应体。
任何业务逻辑、任何 SQL、任何 Prompt 都不允许出现在这里（都放在 inspect_service）。

三条契约（形状由 `app/api/v1/mock_data.py` 冻结，前端 `views/Inspect.vue` 已按它渲染）：
    POST /api/v1/inspect/submit              提交巡检照片
    GET  /api/v1/tickets/list                工单列表
    PUT  /api/v1/tickets/{ticketId}/status   处理工单

第四条是本轮追加的（前端「处理」按钮改为先传处理结果照片、由 AI 核验）：
    POST /api/v1/tickets/{ticketId}/handle   提交处理结果照片 + AI 核验

为什么核验是**独立一条**而不是给 /status 加个可选图片字段
------------------------------------------------------
`PUT /status` 是**人工决定**（到场发现是误报，直接标记完成），
`POST /handle` 是**机器判定**（照片经 AI 核验通过才置完成）。
把两者塞进一个接口，就会在同一个 handler 里出现「这次要不要调模型」的分支，
还会让「传了图但模型没配」这种组合语义不清。拆开后各有各的失败口径：
/status 永远成功（只要状态合法），/handle 可能因图片或模型失败。
两条都保留，人工通道不被机器判定堵死。

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
from app.core.llm import get_optional_vision_llm, get_vision_llm
from app.core.response import ApiResponse, success
from app.schemas.inspect import (
    InspectSubmitData,
    TicketHandleData,
    TicketListData,
    TicketStatusUpdate,
    TicketUpdatedData,
)
from app.services.inspect_service import (
    handle_ticket,
    list_tickets,
    submit_inspection,
    update_ticket_status,
)

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


@router.post(
    "/tickets/{ticketId}/handle",
    response_model=ApiResponse[TicketHandleData],
    summary="提交处理结果并核验",
    response_description="AI 核验结论；核验通过才会把工单置为已完成",
)
async def ticket_handle(
    ticketId: int,
    file: UploadFile = File(..., description="维修后的照片，JPG/PNG/WEBP，≤5MB"),
    db: AsyncSession = Depends(get_db),
    # 处理人只从 JWT 取（§5.1）
    current_user: CurrentUser = Depends(get_current_user),
    # ⚠️ 与 /inspect/submit 的差别：这里**不注入 get_vision_llm**。
    #    那个依赖在模型没配时直接抛 41003，会把「没配 key 的机器」上的
    #    整个处理流程变成 500/41003 —— 而提交处理照片这件事本身不依赖模型，
    #    核验只是它的一个增值步骤。所以这里手工取一个「可能为 None」的模型，
    #    由 service 决定降级（passed=False + 说明原因），接口仍返回 200。
    llm: BaseChatModel | None = Depends(get_optional_vision_llm),
):
    """
    上传维修后的照片，AI 核验是否已修好。

    响应：`{id, status, statusText, passed, verifyStatus, verifyReport, handleImageUrl, …}`

    `passed=true` ⇔ 核验结论为「完好」，此时工单已置为 3 已完成；
    `passed=false` 时工单状态**保持不变**，`verifyReport` 说明原因。
    """
    data = await handle_ticket(
        db,
        ticket_id=ticketId,
        file=file,
        handler_id=current_user.id,
        llm=llm,
    )
    if data.passed:
        message = "AI 核验通过，工单已完成"
    elif data.verifyStatus:
        message = f"AI 核验未通过（判定：{data.verifyStatus}），工单状态未变更"
    else:
        message = "AI 核验未能完成，工单状态未变更"
    return success(data, message=message)
