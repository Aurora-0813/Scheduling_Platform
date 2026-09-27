"""
摄像头空间感知模块 —— Pydantic 数据模型
====================================================================

命名约定（§6.2）：
    API 传输字段一律 camelCase，因此这里的字段名**直接使用 camelCase**，
    不做 snake_case ↔ camelCase 的 alias 转换。
    理由：字段数量固定且不多，直接对齐契约可以让「代码 = 文档」，减少一层认知负担，
    也避免 alias 在 FastAPI 自动生成的 Swagger 文档里显示错乱。

本文件包含三类模型：
    1. 识别结果模型（SpaceRecognition / SketchRecognition）
       —— **同时充当 with_structured_output 的 schema**，直接交给大模型填。
         因此每个字段的 Field(description=...) 极其重要：
         它会被翻译进 JSON Schema，是模型理解「这个字段该填什么」的**唯一依据**。
    2. 公共子结构（SpaceCandidate / AvailableSlot / DeviceHint）—— 组装响应用。
    3. 对外响应模型（SpaceAnalyzeData / SketchAnalyzeData）—— 接口 data 字段。
"""
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# ===========================================================================
# 模型输入端清洗工具
# ===========================================================================
# 大模型返回的 JSON 常常「结构对了但字段类型不对」：
#   - 该给数组的地方给了 null 或单值
#   - 数组里混进了数字、null
#   - confidence 给了字符串 "0.8" 甚至 "high"
#   - 该给整数 id 的地方给了 "101" 或 "unknown"
#
# 如果不做清洗，一个字段类型不对就会让**整个模型校验失败**，
# 连带把同一份响应里本来可用的其它字段一起丢掉，最后整单降级。
# 这是很亏的 —— 所以下面统一在 model_validator(mode="before") 里做一次归一化，
# 把「能救的」救回来，救不回的置空由业务层按降级策略处理。
#
# 注意：这些清洗**不影响 with_structured_output 生成的 JSON Schema**，
# 因为 Schema 是从字段定义推导的，不经过校验器。
# 也就是说：对模型来说字段类型依然是严格的（指导它好好输出），
# 对我们来说解析是宽容的（模型偶尔不听话也不至于全盘失败）。


def _coerce_str_list(value) -> list[str]:
    """
    把任意输入强制成字符串列表。

    参数：
        value : 任意

    返回：
        list[str]；非字符串元素被丢弃，非列表输入返回空列表

    示例：
        ["a", 123, None, "b"] → ["a", "b"]
        "a"                   → []          （单值不猜，直接空）
        None                  → []
    """
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _coerce_float(value) -> float:
    """
    把任意输入强制成 float（不可转换时返回 0.0）。

    参数：
        value : 任意

    返回：
        float；无法转换时返回 0.0

    说明：
        这里**不做 [0,1] 裁剪** —— 裁剪交给 service 层的 _clamp01，
        因为那里还要处理「85 表示 85%」这类百分数归一化。
        本函数只负责「别让类型错误炸掉整份响应」。
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_optional_int(value) -> int | None:
    """
    把任意输入强制成 int 或 None。

    参数：
        value : 任意

    返回：
        int 或 None

    说明：
        对于 spaceId 这类「防幻觉关键字段」，转不出来就一律置 None ——
        None 会被业务层判为「未匹配」，走人工确认。
        绝不能猜一个数字出来，那等于放行幻觉。
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_str(value, max_len: int = 512) -> str | None:
    """
    把任意输入强制成字符串或 None（并做长度截断）。

    参数：
        value   : 任意
        max_len : int 最大长度，超出即截断，防止异常输出撑爆字段

    返回：
        str 或 None
    """
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    text = text.strip()
    return text[:max_len] if text else None


# ===========================================================================
# 一、识别结果模型（同时是 with_structured_output 的 schema）
# ===========================================================================


class SpaceRecognition(BaseModel):
    """
    现场拍照识别空间的**模型输出结构**。

    用法：
        structured = llm.with_structured_output(SpaceRecognition, include_raw=True)
        out = await structured.ainvoke(messages)

    设计要点：
        - 所有字段都有默认值，保证模型漏填时能降级而不是直接报错
        - description 是写给模型看的，必须明确「填什么」和「什么情况填 null」
        - 字段名用 camelCase，与 API 契约一致
    """

    spaceId: int | None = Field(
        default=None,
        description=(
            "从候选场地列表里选出的场地 id。"
            "必须严格使用候选列表中给出的 id，禁止编造。"
            "若没有任何一个候选场地与照片吻合，填 null。"
        ),
    )
    spaceName: str | None = Field(
        default=None,
        description=(
            "所选候选场地的名称，必须与候选列表中的写法**逐字一致**。"
            "选不出场地时填 null。"
        ),
    )
    rawText: str | None = Field(
        default=None,
        description="照片中识别到的门牌号、房间编号或标识牌文字原文；照片里没有文字则填 null。",
    )
    deviceHints: list[str] = Field(
        default_factory=list,
        description=(
            "照片中**肉眼可见**的设备类型名称列表，例如 ['投影仪', '音响']。"
            "只填能明确看出来的，看不出来就填空数组 []。"
        ),
    )
    confidence: float = Field(
        default=0.0,
        description=(
            "你对 spaceId 判断的置信度，取 0 到 1 之间的小数（不要填百分数）。"
            "拿不准就如实填低分，宁可低也不要猜。"
        ),
    )
    question: str | None = Field(
        default=None,
        description=(
            "当 confidence 低于阈值时，生成的一句向用户确认的中文追问，"
            "格式参考：'识别到可能是 XXX，置信度 XX%，是否正确？'。"
            "confidence 达到阈值时填 null。"
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _sanitize(cls, data):
        """
        校验前对原始 JSON 做一次类型归一化（详见文件顶部「模型输入端清洗工具」）。

        为什么用 mode="before"：
            它拿到的还是**未经校验的原始 dict**，因此可以在 Pydantic 报错之前
            把脏类型清理掉。用 mode="after" 就晚了 —— 那时校验已经失败。

        参数：
            data : 任意  模型返回的原始 JSON 解析结果

        返回：
            清洗后的 dict（原样透传非 dict 输入，交给 Pydantic 正常报错）
        """
        if not isinstance(data, dict):
            return data

        data = dict(data)      # 不原地修改调用方的数据

        # spaceId 是防幻觉关键字段：转不出整数就置 None，绝不猜
        data["spaceId"] = _coerce_optional_int(data.get("spaceId"))
        data["spaceName"] = _coerce_optional_str(data.get("spaceName"), max_len=128)
        data["rawText"] = _coerce_optional_str(data.get("rawText"))
        data["deviceHints"] = _coerce_str_list(data.get("deviceHints"))
        data["confidence"] = _coerce_float(data.get("confidence"))
        data["question"] = _coerce_optional_str(data.get("question"), max_len=512)
        return data


class SketchRecognition(BaseModel):
    """
    手绘草图识别的**模型输出结构**（同时是 with_structured_output 的 schema）。
    """

    capacity: int | None = Field(
        default=None,
        description=(
            "根据图中座位、椅子、分区数量预估的容纳人数（正整数）。"
            "图中没有可数的座位信息时填 null。"
        ),
    )
    layout: str | None = Field(
        default=None,
        description=(
            "用一句中文描述布局形式，例如 '圆桌围坐，中间留空作展示区'、"
            "'剧院式排布，前方设讲台'。看不出来填 null。"
        ),
    )
    requirements: list[str] = Field(
        default_factory=list,
        description=(
            "从草图能推断出的场地约束关键词，例如 ['需要投影', '需要围坐讨论']。"
            "图中出现的文字标注（如'投影''白板''入口'）应直接采纳进来。推断不出填空数组 []。"
        ),
    )
    confidence: float = Field(
        default=0.0,
        description="整体解读置信度，0 到 1 之间的小数（不要填百分数），诚实自评。",
    )
    question: str | None = Field(
        default=None,
        description=(
            "当 confidence 低于阈值时生成的一句中文追问；达到阈值时填 null。"
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _sanitize(cls, data):
        """
        校验前做类型归一化（说明同 SpaceRecognition._sanitize）。

        特别注意 requirements：
            声明成 list[str] 是为了让 with_structured_output 给模型一个明确的
            「字符串数组」信号；但模型实际返回的数组里常常混入数字或 null。
            若不做清洗，一个 123 就会让整份响应校验失败、连带丢掉 layout 与 capacity。
            这里先把非字符串剔掉，后面 service 层再做去重与限长。
        """
        if not isinstance(data, dict):
            return data

        data = dict(data)

        # capacity 转不出整数就置 None（业务层还会再做 1~10000 的合理性校验）
        raw_capacity = data.get("capacity")
        try:
            data["capacity"] = None if raw_capacity is None else int(raw_capacity)
        except (TypeError, ValueError):
            data["capacity"] = None

        data["layout"] = _coerce_optional_str(data.get("layout"), max_len=512)
        data["requirements"] = _coerce_str_list(data.get("requirements"))
        data["confidence"] = _coerce_float(data.get("confidence"))
        data["question"] = _coerce_optional_str(data.get("question"), max_len=512)
        return data


# ===========================================================================
# 二、公共子结构
# ===========================================================================


class SpaceCandidate(BaseModel):
    """候选场地（供前端在识别错误时让用户手动改选）"""
    spaceId: int = Field(..., description="场地ID")
    spaceName: str = Field(..., description="场地名称")
    spaceType: int = Field(..., description="空间类型：1会议室 2展厅 3多功能厅 4户外场地")
    location: str | None = Field(None, description="位置")
    capacity: int | None = Field(None, description="容纳人数")


class AvailableSlot(BaseModel):
    """场地空档时段（在开放时间内扣除已被占用的区间）"""
    date: str = Field(..., description="日期，YYYY-MM-DD")
    startTime: str = Field(..., description="空档开始，HH:mm:ss")
    endTime: str = Field(..., description="空档结束，HH:mm:ss")


class DeviceHint(BaseModel):
    """
    照片中识别到的设备。

    ⚠️ 语义说明（见设计文档 §13 待确认问题 1）：
        这是「照片里**看到**的设备」，**不是**「该场地数据库里登记的配套设备」。
        原因是当前数据库没有 space_resource ↔ device_resource 的关联表，
        无法对它做权威校验，因此本字段仅作展示参考，**不参与任何业务决策**。
    """
    deviceType: str = Field(..., description="设备类型，如 投影仪 / 音响 / 显示屏")
    count: int = Field(1, description="可见数量估计")
    confidence: float = Field(0.0, description="该设备识别的置信度")


# ===========================================================================
# 三、对外响应模型（接口 data 字段）
# ===========================================================================


class SpaceAnalyzeData(BaseModel):
    """
    POST /api/v1/image/analyze 的 data 字段。

    字段来源标注：
        [契约] = 开发流程.md §5.3 模块 2 原有字段
        [新增] = 本模块扩展字段，见设计文档 §4.4，**需按 §2.5 通知相关方**
    """
    type: Literal["space"] = Field("space", description="固定 space [契约]")
    spaceId: int | None = Field(None, description="匹配到的场地ID；未匹配到为 null [契约]")
    spaceName: str | None = Field(None, description="场地名称，**取自数据库**而非模型输出 [契约]")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="识别置信度 0~1 [契约]")
    availableTime: list[AvailableSlot] = Field(
        default_factory=list, description="场地未来可用空档时段 [契约]"
    )
    devices: list[DeviceHint] = Field(
        default_factory=list, description="照片中识别到的设备 [契约]"
    )

    needConfirm: bool = Field(True, description="是否需要用户确认后才能送往 Agent [新增]")
    question: str | None = Field(None, description="追问文案，needConfirm=true 时必有值 [新增]")
    rawText: str | None = Field(None, description="照片中识别到的门牌/标识文字 [新增]")
    candidates: list[SpaceCandidate] = Field(
        default_factory=list, description="候选场地，供用户在识别错误时改选 [新增]"
    )
    imageUrl: str | None = Field(None, description="图片访问地址；落盘失败为 null [新增]")


class SketchAnalyzeData(BaseModel):
    """POST /api/v1/image/sketch 的 data 字段"""
    type: Literal["sketch"] = Field("sketch", description="固定 sketch [契约]")
    capacity: int | None = Field(None, description="预估容纳人数 [契约]")
    layout: str | None = Field(None, description="布局文字描述 [契约]")
    requirements: list[str] = Field(
        default_factory=list, description="草图隐含的约束关键词 [契约]"
    )
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="解读置信度 0~1 [契约]")

    needConfirm: bool = Field(True, description="是否需要用户确认 [新增]")
    question: str | None = Field(None, description="追问文案 [新增]")
    imageUrl: str | None = Field(None, description="图片访问地址 [新增]")
