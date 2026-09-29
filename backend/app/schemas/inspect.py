"""
模块 6：AI 智能巡检与维修工单 —— Pydantic 数据模型

命名约定（§6.2）：API 传输字段一律 camelCase，因此这里**直接用 camelCase** 作字段名，
不做 snake_case ↔ camelCase 的 alias 转换（理由同 `schemas/image.py`）。

三类模型：
    1. `InspectAnalysis` —— 大模型的结构化输出，**同时充当 with_structured_output 的 schema**。
       每个字段的 `Field(description=...)` 会进 JSON Schema，是模型理解「该填什么」的唯一依据。
    2. 对外响应模型：`InspectSubmitData` / `TicketListData` / `TicketUpdatedData`。
    3. 工单列表项：`TicketItem`。

⚠️ **契约来源，字段名不要改**：这三个响应的形状由 `app/api/v1/mock_data.py` 的
`INSPECT_SUBMIT` / `TICKETS` / `TICKET_UPDATED` 冻结，
`frontend/src/views/Inspect.vue`（路由 `/inspect`）已按它渲染。
模块 6 从 mock 升级为真实实现时，形状必须一字不差 —— 否则前端要跟着重写一遍。
"""

from pydantic import BaseModel, Field

__all__ = [
    "InspectAnalysis",
    "InspectSubmitData",
    "TicketItem",
    "TicketListData",
    "TicketStatusUpdate",
    "TicketUpdatedData",
]


# ===========================================================================
# 1. 大模型的结构化输出
# ===========================================================================
class InspectAnalysis(BaseModel):
    """大模型对一张巡检照片的结构化判断。"""

    deviceStatus: str = Field(
        ...,
        description=(
            "设备状况判定，只能取这四个值之一："
            "完好 / 损坏 / 缺失配件 / 无法识别。"
            "照片空白、严重模糊或完全遮挡时填 无法识别。"
        ),
    )
    report: str = Field(
        ...,
        description=(
            "巡检报告：先客观描述画面中设备的实际状况（外观、部件、铭牌、指示灯等），"
            "再给巡检结论与发现的问题。300 字以内，不要分点编号。"
        ),
    )
    repairSuggestion: str = Field(
        "",
        description="维修建议。deviceStatus 为 完好 或 无法识别 时留空字符串。",
    )
    deviceName: str | None = Field(
        None,
        description="画面中设备的名称（如 投影仪01）。认不出填 null，不要编造。",
    )
    deviceType: str | None = Field(
        None,
        description="画面中设备的类型（如 投影仪 / 音响 / 显示屏）。认不出填 null。",
    )


# ===========================================================================
# 2. 对外响应模型
# ===========================================================================
class InspectSubmitData(BaseModel):
    """`POST /inspect/submit` 的 data —— 对应 mock_data.INSPECT_SUBMIT。"""

    deviceStatus: str
    report: str
    repairSuggestion: str = ""
    #: 只有判定为异常时才建工单；完好 / 无法识别时为 None
    ticketId: int | None = None


class TicketItem(BaseModel):
    """工单列表里的一条 —— 对应 mock_data.TICKETS["list"][*]。"""

    id: int
    spaceId: int | None = None
    deviceId: int | None = None
    #: 来自关联的巡检记录（`inspect_record.ai_result`），见 inspect_service 的说明
    deviceStatus: str | None = None
    deviceName: str | None = None
    status: int
    statusText: str
    report: str | None = None
    createTime: str | None = None


class TicketListData(BaseModel):
    """`GET /tickets/list` 的 data —— 对应 mock_data.TICKETS。"""

    page: int
    pageSize: int
    total: int
    list: list[TicketItem]


class TicketStatusUpdate(BaseModel):
    """`PUT /tickets/{ticketId}/status` 的请求体。

    用 Pydantic 模型而不是裸 `dict = Body(...)`：前者能把取值约束写进 Swagger，
    且类型不对时由统一的校验处理器给出 400 / 40001 + 字段级原因；
    裸 dict 得在路由里手写一遍判断，那份判断不会出现在文档里。
    """

    status: int = Field(..., description="目标状态：1 待处理 / 2 处理中 / 3 已完成")


class TicketUpdatedData(BaseModel):
    """`PUT /tickets/{ticketId}/status` 的 data —— 对应 mock_data.TICKET_UPDATED。"""

    id: int
    status: int
    statusText: str
    handlerId: int | None = None
    handleTime: str | None = None

