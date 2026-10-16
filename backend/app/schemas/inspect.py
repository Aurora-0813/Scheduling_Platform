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
    "HandleVerifyAnalysis",
    "TicketHandleData",
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
        description=(
            "画面中**设备或设施**的名称。台账里的设备写编号（如 投影仪01）；"
            "不在台账里的固定设施（电路/插座/门把手等）写通用名，**优先从这份清单里选**："
            "配电箱、电路、插座、开关、照明灯具、空调、出风口、水管、水龙头、消防栓、"
            "灭火器、门、门把手、门锁、窗、玻璃、墙面、地面、天花板、楼梯、扶手、"
            "标识牌、垃圾桶、窗帘。认不出填 null，不要编造。"
        ),
    )
    deviceType: str | None = Field(
        None,
        description="画面中设备或设施的类型（如 投影仪 / 音响 / 显示屏 / 插座）。认不出填 null。",
    )
    locationHint: str | None = Field(
        None,
        description=(
            "画面里能看出的**具体位置**（如「3楼走廊东侧」「会议室门口」）。"
            "看不出填 null，不要编造。用户在现场填的位置会覆盖这里。"
        ),
    )


# ===========================================================================
# 1b. 大模型对「处理后照片」的结构化输出
# ===========================================================================
class HandleVerifyAnalysis(BaseModel):
    """
    大模型对一张**维修完成后**照片的结构化判断。

    字段刻意与 `InspectAnalysis` 同名同义，**不新造一套口径**：
    「设备是否修好」与「设备是否完好」是同一件事的两种问法，
    另立一套「处理成功 / 处理失败」的二值口径等于把同一判断标准写两遍，
    而本仓库反复踩过的坑正是「同一件事两处实现、改一处漏一处」。

    与 `InspectAnalysis` 的差异只有一处：**没有 repairSuggestion** ——
    核验环节不需要再给维修建议：通过了就没得修，没通过则该重做，
    而不是再写一条建议。
    """

    deviceStatus: str = Field(
        ...,
        description=(
            "维修后设备状况判定，只能取这四个值之一："
            "完好 / 损坏 / 缺失配件 / 无法识别。"
            "照片空白、严重模糊或完全遮挡时填 无法识别。"
        ),
    )
    report: str = Field(
        ...,
        description=(
            "核验说明：先客观描述画面中设备现在的状况，再说明是否已恢复正常。"
            "200 字以内，不要分点编号。"
        ),
    )
    deviceName: str | None = Field(
        None,
        description="画面中设备的名称（如 投影仪01）。认不出填 null，不要编造。",
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
    #: 设备台账**部分成功**时的提示，目前只有一种情形：
    #: 该设备可借数已经是 0（可借台数用光 / 已有人报修），本次只记录故障、未再减。
    #: 不回传的话，用户会看到「工单建了但可借数没变」，以为是 bug。
    deviceWarning: str | None = None
    #: 本次落库的**具体位置**（用户填的优先，没填才是 AI 从画面推断的）。
    #: 固定设施（插座/门把手）不在设备台账里，位置是它们唯一的精度来源。
    locationHint: str | None = None
    #: 本次巡检照片的访问路径（如 /uploads/20261013/xxx.jpg），落盘失败时为 None。
    #: 工单列表里同名字段可直接用于回看照片。
    imageUrl: str | None = None


class TicketItem(BaseModel):
    """工单列表里的一条 —— 对应 mock_data.TICKETS["list"][*]。"""

    id: int
    spaceId: int | None = None
    deviceId: int | None = None
    #: 来自关联的巡检记录（`inspect_record.ai_result`），见 inspect_service 的说明
    deviceStatus: str | None = None
    deviceName: str | None = None
    #: **具体位置**（如「3楼走廊东侧」）：固定设施不在设备台账里，
    #: 位置是它们唯一的精度来源。用户填的优先，没填才是 AI 从画面推断的。
    locationHint: str | None = None
    status: int
    statusText: str
    report: str | None = None
    createTime: str | None = None

    #: **原始巡检照片**的访问路径（来自关联巡检记录的 `image_url`）。
    #: 工单表本身不存这一列，靠 `inspect_id` JOIN 回巡检记录取 ——
    #: 照片在巡检时就已落盘，这里只是把它透出给前端回看。
    inspectImageUrl: str | None = None

    # ---------- 处理结果与 AI 核验（模块 6 追加，均可空）----------
    #: 处理结果照片地址；没走过 /handle 的工单为 None
    handleImageUrl: str | None = None
    #: AI 核验结论（四值，同 deviceStatus）；未核验为 None
    verifyStatus: str | None = None
    verifyReport: str | None = None


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
    #: 推进到「已完成」且成功恢复设备时，回传恢复的设备与它的新可借数；
    #: 未推进到已完成 / 未匹配到设备时为 None。前端可据此提示「设备已恢复可借」。
    deviceId: int | None = None
    availableCount: int | None = None


class TicketHandleData(BaseModel):
    """
    `POST /tickets/{ticketId}/handle` 的 data —— 处理结果照片 + AI 核验。

    比 `TicketUpdatedData` 多出核验相关的四项，其中 **`passed` 是给前端直接用
    的布尔判定**，不要让它自己拿 `verifyStatus` 去和字符串比 ——
    「哪个取值算通过」是业务口径，只能有一处定义（后端 `ABNORMAL_STATUSES`
    的补集），前端再判一次就是第二处。
    """

    id: int
    status: int
    statusText: str
    handlerId: int | None = None
    handleTime: str | None = None

    #: AI 核验是否通过。`verifyStatus == "完好"` 即 True。
    passed: bool
    #: 核验结论（四值）。模型彻底不可用时为 None，此时 passed=False 且 verifyReport 给出原因。
    verifyStatus: str | None = None
    verifyReport: str | None = None
    #: 处理结果照片地址；落盘失败时为 None（不阻断核验，见 image_storage.save_image）
    handleImageUrl: str | None = None
    #: 核验通过并恢复设备时回传：恢复的设备 id 与它的新可借数。
    #: 未通过 / 未匹配到设备时为 None。
    deviceId: int | None = None
    availableCount: int | None = None
