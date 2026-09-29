"""
模块 6：AI 智能巡检与维修工单 —— 服务层

对应 `docs/api.md` 的三条契约（形状由 `app/api/v1/mock_data.py` 冻结）：
    POST /inspect/submit              提交巡检照片 → AI 判定 → 落巡检记录 → 异常时建工单
    GET  /tickets/list                工单列表（分页）
    PUT  /tickets/{ticketId}/status   处理工单（状态流转）

为什么**不需要改表结构**
------------------------
契约要的 `deviceStatus` / `report` / `repairSuggestion` 三个字段，
`repair_ticket` 里没有；但 `inspect_record.ai_result` 是 JSON 列、
注释写着「AI识别结果」—— 这三个值正是 AI 的识别结果，放进去是它的本职。
工单列表要的 `report` 于是靠 `repair_ticket.inspect_id` **JOIN** 回巡检记录取。
好处：零 DDL。团队约定「DDL 一律走集成组」，零 DDL 就不需要过那道审批，
也不用动共享的开发库结构、不用写迁移。

为什么复用 `image_service._recognize`
-----------------------------------
它是「调模型 → 拿结构化结果」的统一入口，内置策略 A（`with_structured_output`）
与策略 B（普通 ainvoke + JSON 容错解析）两条路，并在模型彻底不可用时抛 41003。
这里**刻意不重写一份**：重写出来的解析只会与模块 2 的实现悄悄漂移，
而「同一件事两处实现」正是本仓库反复踩过的坑。跨模块引用私有名有先例 ——
`scripts/check_data.py` 就引用了 `dashboard_service._open_hours`，理由相同。

状态口径
--------
`repair_ticket.ticket_status`：1 待处理 / 2 处理中 / 3 已完成（模型注释即此口径）。
`deviceStatus` 只允许四个取值（见 `inspect_prompt`）；**只有 损坏 / 缺失配件 会建工单**，
完好 与 无法识别 都不建 —— 后者尤其重要：照片拍糊了就建工单，是制造垃圾数据。
"""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompts.inspect_prompt import build_inspect_messages
from app.core.exceptions import ParamInvalidError, SpaceNotFoundError, TicketNotFoundError
from app.core.utils import format_time
from app.models.inspection import InspectRecord, RepairTicket
from app.models.resource import SpaceResource
from app.schemas.inspect import (
    InspectAnalysis,
    InspectSubmitData,
    TicketItem,
    TicketListData,
    TicketUpdatedData,
)
from app.services.image_service import _recognize
from app.services.image_storage import read_and_validate_image, save_image, to_data_url

logger = logging.getLogger(__name__)

__all__ = [
    "DEVICE_STATUSES",
    "ABNORMAL_STATUSES",
    "TICKET_STATUS_TEXT",
    "submit_inspection",
    "list_tickets",
    "update_ticket_status",
]

#: 模型唯一允许输出的四个取值。Prompt 里已钉死，这里是**兜底白名单**：
#: 模型不听话时判为「无法识别」，而不是把自由文本写进库、再让下游去猜。
DEVICE_STATUSES: frozenset[str] = frozenset({"完好", "损坏", "缺失配件", "无法识别"})

#: 需要建维修工单的取值。**不含「无法识别」** —— 照片拍糊不是设备坏了。
ABNORMAL_STATUSES: frozenset[str] = frozenset({"损坏", "缺失配件"})

UNRECOGNIZED = "无法识别"

#: 工单状态 → 文案（ticket_status 的取值口径见 models/inspection.py）
TICKET_STATUS_TEXT: dict[int, str] = {1: "待处理", 2: "处理中", 3: "已完成"}

_PARSE_FAILED_REPORT = (
    "巡检照片未能得到有效分析结果（模型输出无法解析）。"
    "建议重新拍摄一张光线充足、设备主体清晰的正面照片后再次提交。"
)

#: 落进 `inspect_record.ai_result` 的原始回复最多留这么长，避免 JSON 列被撑爆
_RAW_TEXT_MAX = 500


# ===========================================================================
# 内部辅助
# ===========================================================================
def _normalize_status(raw: object) -> str:
    """把模型给的 deviceStatus 归一到白名单内；不在名单里一律判为「无法识别」。"""
    text = str(raw or "").strip()
    if text in DEVICE_STATUSES:
        return text
    # 容错：模型爱写「设备损坏」「轻微损坏」这类带修饰的说法，包含即算命中。
    # 顺序有讲究 —— 先判「缺失配件」，否则「配件缺失导致损坏」会被判成「损坏」，
    # 而两者的处理建议完全不同（补配件 vs 换设备）。
    if "缺失配件" in text or "缺少配件" in text or "配件缺失" in text:
        return "缺失配件"
    if "损坏" in text or "故障" in text:
        return "损坏"
    if "完好" in text or "正常" in text:
        return "完好"
    return UNRECOGNIZED


def _status_text(status: int) -> str:
    """工单状态码 → 文案。未知状态不抛异常，回一句可读的兜底。"""
    return TICKET_STATUS_TEXT.get(status, f"未知状态({status})")


def _ticket_item(ticket: RepairTicket, ai_result: dict | None) -> TicketItem:
    """把 (工单行, 关联巡检记录的 ai_result) 组装成列表项。"""
    ai = ai_result or {}
    return TicketItem(
        id=ticket.id,
        spaceId=ticket.space_id,
        deviceId=ticket.device_id,
        deviceStatus=ai.get("deviceStatus"),
        deviceName=ai.get("deviceName"),
        status=ticket.ticket_status,
        statusText=_status_text(ticket.ticket_status),
        report=ai.get("report"),
        createTime=format_time(ticket.create_time),
    )


# ===========================================================================
# 对外入口 1：提交巡检
# ===========================================================================
async def submit_inspection(
    db: AsyncSession,
    *,
    file,
    space_id: int,
    inspector_id: int,
    llm: BaseChatModel,
) -> InspectSubmitData:
    """
    提交一张巡检照片：AI 判定 → 落巡检记录 → 异常时建维修工单。

    参数：
        db           : AsyncSession    请求级会话（由 get_db 注入）
        file         : UploadFile      照片，JPG/PNG/WEBP，≤ IMAGE_MAX_SIZE_MB
        space_id     : int             拍摄所在场地
        inspector_id : int             巡检人，**必须来自 JWT**（§5.1，禁止从 FormData 传）
        llm          : BaseChatModel   视觉模型（由 get_vision_llm 注入；测试用假模型替换）

    返回：
        InspectSubmitData(datasetStatus, report, repairSuggestion, ticketId)

    抛出：
        ImageValidationError(41001/41002)  图片格式 / 大小不合法（由 image_storage 抛）
        SpaceNotFoundError(40402)          场地不存在
        ImageRecognitionError(41003)       视觉模型不可用（未配置 / 超时 / 服务端错误）

    执行流程：
        ┌─ ① 校验图片（格式 / 大小 / 魔数）
        ├─ ② 场地必须存在 —— 云库上 inspect_record.space_id 是**真外键**，
        │     不先查会以 MySQL 1452 炸成 500（这个坑 order_service 注释里记过）
        ├─ ③ 落盘（失败不阻断，与模块 2 的 D6 口径一致）
        ├─ ④ 调视觉模型（复用 image_service._recognize，含两级策略与容错解析）
        ├─ ⑤ 解析失败 → 降级：记录仍落库，deviceStatus=无法识别，**不建工单**
        ├─ ⑥ 落 inspect_record（ai_result 装四个业务字段）
        ├─ ⑦ 判定异常 → 落 repair_ticket（status=1 待处理）
        └─ ⑧ 一次 commit 收口

    ⚠️ 为什么⑥⑦在一个 commit 里：工单挂着 inspect_id 外键。
    若先提交巡检记录再单独提交工单，中间失败会留下「有巡检、没工单」的孤儿，
    而那条巡检记录的 ai_result 明明白白写着「损坏」—— 对不上账。
    """
    # ---- ① 校验图片 ----
    raw, mime = await read_and_validate_image(file)

    # ---- ② 场地必须存在 ----
    space = await db.get(SpaceResource, space_id)
    if space is None:
        raise SpaceNotFoundError("场地不存在")

    # ---- ③ 落盘 ----
    # save_image 失败返回 None（故意不阻断主流程）。但 inspect_record.image_url 是
    # NOT NULL，所以这里退化成空串 —— 宁可丢图片地址，也不要整个巡检提交失败。
    image_url = await save_image(raw, mime) or ""

    # ---- ④ 调视觉模型 ----
    messages = build_inspect_messages(
        image_data_url=to_data_url(raw, mime),
        space_name=space.space_name,
    )
    parsed, raw_reply = await _recognize(llm, messages, InspectAnalysis)

    # ---- ⑤ 解析失败 → 降级，但仍然留一条记录（否则用户无从知道这次提交发生了什么）----
    parse_failed = parsed is None
    if parse_failed:
        logger.info("巡检照片解析失败，已降级为「无法识别」（场地 %s）", space_id)
        status = UNRECOGNIZED
        report = _PARSE_FAILED_REPORT
        suggestion = ""
        device_name = None
        device_type = None
    else:
        status = _normalize_status(parsed.deviceStatus)
        report = (parsed.report or "").strip() or _PARSE_FAILED_REPORT
        suggestion = (parsed.repairSuggestion or "").strip()
        device_name = (parsed.deviceName or None)
        device_type = (parsed.deviceType or None)
        # 完好 / 无法识别 时不留维修建议 —— 模型偶尔会「顺便」写一条，那是噪音
        if status not in ABNORMAL_STATUSES:
            suggestion = ""

    ai_result: dict = {
        "deviceStatus": status,
        "report": report,
        "repairSuggestion": suggestion,
        "deviceName": device_name,
        "deviceType": device_type,
        "parseFallback": parse_failed,
    }
    if parse_failed and raw_reply:
        ai_result["rawText"] = raw_reply[:_RAW_TEXT_MAX]

    # ---- ⑥ 落巡检记录 ----
    record = InspectRecord(
        space_id=space_id,
        image_url=image_url,
        ai_result=ai_result,
        inspector_id=inspector_id,
    )
    db.add(record)
    await db.flush()  # 取库侧自增 id，工单要拿它当 inspect_id

    # ---- ⑦ 判定异常 → 建工单 ----
    ticket: RepairTicket | None = None
    if status in ABNORMAL_STATUSES:
        ticket = RepairTicket(
            inspect_id=record.id,
            device_id=None,  # 契约里前端只传 spaceId，认出的设备名映射不回 device_resource.id
            space_id=space_id,
            ticket_status=1,  # 待处理
            handler_id=None,  # 处理时才由 PUT 接口写入
        )
        db.add(ticket)
        await db.flush()

    # ---- ⑧ 提交 ----
    await db.commit()

    return InspectSubmitData(
        deviceStatus=status,
        report=report,
        repairSuggestion=suggestion,
        ticketId=ticket.id if ticket is not None else None,
    )


# ===========================================================================
# 对外入口 2：工单列表
# ===========================================================================
async def list_tickets(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 10,
    status: int | None = None,
) -> TicketListData:
    """
    工单列表（分页，倒序）。

    参数：
        status : int | None  按工单状态筛选（1/2/3）；None 表示全部

    `report` / `deviceStatus` 不在 repair_ticket 上，靠 `inspect_id` **LEFT JOIN** 回
    `inspect_record` 取 `ai_result` —— 用 LEFT 而不是 INNER：
    工单关联的巡检记录若被清理掉，工单本身仍应出现在列表里（宁可少几个字段，
    也不要整条工单凭空消失）。
    """
    if page < 1 or page_size < 1:
        raise ParamInvalidError("page / pageSize 必须为正整数")
    if status is not None and status not in TICKET_STATUS_TEXT:
        raise ParamInvalidError("status 只能为 1(待处理) / 2(处理中) / 3(已完成)")

    where = [] if status is None else [RepairTicket.ticket_status == status]

    total = (await db.execute(
        select(func.count()).select_from(RepairTicket).where(*where)
    )).scalar_one()

    rows = (await db.execute(
        select(RepairTicket, InspectRecord.ai_result)
        .outerjoin(InspectRecord, InspectRecord.id == RepairTicket.inspect_id)
        .where(*where)
        .order_by(RepairTicket.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).all()

    return TicketListData(
        page=page,
        pageSize=page_size,
        total=int(total),
        list=[_ticket_item(ticket, ai) for ticket, ai in rows],
    )


# ===========================================================================
# 对外入口 3：处理工单
# ===========================================================================
async def update_ticket_status(
    db: AsyncSession,
    *,
    ticket_id: int,
    status: int,
    handler_id: int,
) -> TicketUpdatedData:
    """
    流转工单状态（1 待处理 → 2 处理中 → 3 已完成）。

    参数：
        handler_id : int  处理人，**必须来自 JWT**（§5.1）

    抛出：
        TicketNotFoundError(40405)  工单不存在
        ParamInvalidError(40001)    status 不在 1/2/3 内

    为什么不做「必须按 1→2→3 顺序流转」的硬约束：
        实际维修中存在「直接标记完成」的场景（到场发现是误报）。真正的状态机约束
        应先由业务方确认口径再定；这里只校验取值合法，避免凭空发明一条规则。
    """
    if status not in TICKET_STATUS_TEXT:
        raise ParamInvalidError("status 只能为 1(待处理) / 2(处理中) / 3(已完成)")

    ticket = await db.get(RepairTicket, ticket_id)
    if ticket is None:
        raise TicketNotFoundError("维修工单不存在")

    ticket.ticket_status = status
    ticket.handler_id = handler_id
    await db.commit()
    await db.refresh(ticket)

    return TicketUpdatedData(
        id=ticket.id,
        status=ticket.ticket_status,
        statusText=_status_text(ticket.ticket_status),
        handlerId=ticket.handler_id,
        handleTime=format_time(ticket.update_time),
    )

