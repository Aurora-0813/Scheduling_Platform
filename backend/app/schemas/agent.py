"""核心调度 Agent 模块的请求 / 响应契约（主文档 5.3 模块 4）。

本模块的返回结构会被前端与小程序渲染，字段一经冻结不得中途更改——
主线一屏 3 要按 TraceStep 逐字段渲染 40 秒思考过程，改一个字段演示就崩。

命名约定：传输字段一律 camelCase（主文档 6.2）。
这里**直接**用 camelCase 作 Python 字段名，不走 alias 方案。原因是 alias 方案
存在一个静默失败模式：序列化时漏掉 by_alias=True，线上字段会悄悄变回
snake_case，前端取值拿到 None 却不报错，排查成本极高。直接命名没有这个风险。
"""

from pydantic import BaseModel, ConfigDict, Field

from app.core.camel import CamelModel

__all__ = ["ScheduleRequest", "TraceStep", "Plan", "ScheduleData", "AgentModeRequest"]


class AgentModeRequest(CamelModel):
    """`PUT /api/v1/agent/mode` 请求体（2026-10-13 修）。

    ## 为什么需要这个模型（原来没有，于是接口是坏的）

    原签名是 `async def set_mode(deepMode: bool | None = None, aiRecommend: bool | None = None)`。
    在 FastAPI 里，**标量类型的默认参数会被当成 query 参数**，只有 Pydantic 模型
    才会从 JSON body 取。于是：

        PUT /agent/mode   body = {"deepMode": true}

    `deepMode` 取到的是 `None`（query 里没有），两个 `if` 都不进，
    接口返回 200 + `未做改动`，**开关纹丝不动**。前端发的是 body，
    所以 Web 管理端那对按钮点了没有任何效果，而且不报错 —— 最坏的一种故障。

    2026-10-13 实测（启真后端 + 真 JWT，见本轮验证记录）：
        · body 传参 → `data` 永远停在默认值，`runtime_flags.json` 不生成
        · query 传参 `?deepMode=true` → 立刻生效
    修法就是这里：**收一个模型**，两个字段都可缺省 —— 只传自己关心的那一个，
    不传的保持原样。`CamelModel` 让线上字段名保持 camelCase（`deepMode`），
    与前端、与 `GET /agent/mode` 的返回、与小程序端全都对得上。
    """

    deepMode: bool | None = Field(
        None,
        description="深度模式：true 走多轮 Agent（40~80 秒，思考链完整）；不传则保持原样",
    )
    aiRecommend: bool | None = Field(
        None,
        description="AI 推荐：true 由大模型给推荐与理由（解析约 32 秒）；不传则保持原样",
    )


class ScheduleRequest(BaseModel):
    """POST /api/v1/agent/schedule 请求体（主文档 5.3 模块 4）。

    注意：**没有 userId 字段**。调用者身份一律从 JWT 解析（主文档 5.1、9.1），
    请求体夹带 userId 会被忽略——若从请求体取，任何人都能替别人预约。
    """

    # `extra="ignore"` 是**显式**写出来的，虽然它就是 Pydantic v2 的默认值。
    # 理由：`AGENT-I-04`（请求体夹带 `userId` 时被忽略）依赖这个行为，
    # 而它离「默认值」只有一步之遥——将来若有人为了「及早发现前端传错字段」
    # 改成 `extra="forbid"`，夹带 `userId` 会变成参数校验失败（HTTP 200 + code=400），
    # 越权防线从「忽略」变成「拒绝」，
    # 用例红得莫名其妙。写在这里，改的人至少会看到这行注释。
    # 注意：**忽略**不等于安全——真正不越权是因为身份只从 JWT 解析（见 api/deps.py），
    # 而不是因为这里丢掉了一个字段。
    model_config = ConfigDict(extra="ignore")

    text: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        description="用户原始自然语言需求",
    )
    imageContext: dict = Field(
        default_factory=dict,
        description="模块 2 传入的图像解析上下文",
    )
    # ⚠️ 2026-10-13 由 `bool = False` 改成**三态** `bool | None = None`。
    # 改动理由是一次真实的静默失败：两端客户端都在客户端就把 fast 定成了 True
    # （前端默认 { ...data, fast: data.fast !== false }、小程序默认 fast: true），
    # 于是后端那个「🧠 深度思考 / ⚡ 快速决策」全局开关**从来没被读过** ——
    # 按钮高亮会换、runtime_flags.json 也会写，但调度永远走快速模式。
    #
    # 现在的口径（见 app/core/flags.py::resolve_fast）：
    #   None  → 跟随全局开关 deepMode（服务端说了算，**推荐调用方什么都不传**）
    #   True  → 强制快速模式
    #   False → 强制多轮 Agent
    #
    # 注意这里**不能**给 False 以外的默认值：给 True 就等于替所有调用方做了决定，
    # 全局开关又会退回「摆设」；给 False 则与「快速模式是默认」的既有口径冲突。
    # 只有 None 能让「不传 = 听服务端」这条语义成立。
    fast: bool | None = Field(
        None,
        description=(
            "是否走快速模式（全量候选 + 单次模型调用，约 5~10 秒，trace 只有 3 步）。\n"
            "不传（推荐）则跟随后端全局开关 deepMode：开则多轮 Agent（40~80 秒，思考链完整），\n"
            "关则快速模式。显式传 true / false 可强制指定，用于脚本化调用与联调。"
        ),
    )


class TraceStep(BaseModel):
    """思考链的一步（主文档 5.3 + 3.3/7.4 的合成结构）。

    step / result / timestamp 三个字段是主文档 5.3 明文要求的必需项；
    thought / action / actionInput / observation 是 3.3 与 7.4 要求的
    Thought-Action-Observation 映射，主文档未给字段名，此处定稿。

    timestamp 注意：LangGraph 的 messages 里**没有墙钟时间**。用提取时刻统一
    打点会让所有步骤时间戳相同，前端时间轴回放会退化成同时出现。必须用
    astream() 边收边打点，记录每一步的真实时间。
    """

    step: int = Field(..., ge=1, description="步骤序号，从 1 递增")
    result: str = Field(..., description="本步骤的中文结论")
    timestamp: str = Field(..., description="该步骤发生时刻，YYYY-MM-DD HH:mm:ss")

    # ---- 思考链明细（可空：不是每一步都有全部要素）----
    thought: str | None = Field(None, description="Thought：模型本步的推理文本")
    action: str | None = Field(None, description="Action：被调用的 Tool 名")
    actionInput: dict | None = Field(None, description="Action 的入参")
    observation: dict | None = Field(None, description="Observation：Tool 的返回")


class Plan(BaseModel):
    """一个可执行的调度方案。"""

    spaceId: int | None = Field(None, description="场地 ID")
    spaceName: str | None = Field(None, description="场地名称")
    deviceIds: list[int] = Field(default_factory=list, description="设备 ID 列表")
    startTime: str | None = Field(None, description="开始时间")
    endTime: str | None = Field(None, description="结束时间")
    reason: str | None = Field(None, description="方案说明，含降级/替代理由")


class ScheduleData(BaseModel):
    """统一响应体的 data 部分（主文档 5.2 外层为 {code, message, data}）。

    三条降级口径，均返回 HTTP 200，**不是异常**：

    | 情形 | plan | orderId | needConfirm | message |
    | --- | --- | --- | --- | --- |
    | 正常 | 方案 | 订单 ID，未落库时 None | True | "操作成功" |
    | 无可行方案 | None | **同上**（已锁单就照报） | True | 人工可读原因+修改建议 |
    | 大模型输出格式错乱 | None | **同上**（已锁单就照报） | True | 模型返回的自然语言文本 |

    第三种是主文档 10.2 要求必须测的契约内降级路径——当成异常抛 500 会让
    前端不知道该展示什么。
    """

    plan: Plan | None = Field(None, description="主方案；无可行方案时为 None")
    backupPlan: Plan | None = Field(None, description="备选方案")

    # 前端拿它去调 `PUT /api/v1/orders/{orderId}/confirm` 完成 1→2 的确认流转。
    # 不透出的话，`needConfirm=true` 在前端就是个死胡同：知道要确认，却没有单号可传。
    #
    # ⚠️ **降级路径不能一刀切成 None**。`plan` 为 None 与「没落库」是两件事：
    #    模型完全可能先调 `lock_resources` 锁上了单，再在交方案前超时。
    #    此时库里有单、响应里却没有单号，那单就成了孤儿——锁着、没人确认、也没人知道。
    #    取值一律用 `AgentOutcome.locked_order_id`（它已经把「桩期没落库」「失败调用」滤干净），
    #    不要在这里另做判断。None 的含义是**确实没建单**，不是「没方案」。
    orderId: int | None = Field(
        None, description="本轮成功锁定的预约单 ID；未落库时为 None（与 plan 是否为空无关）"
    )
    trace: list[TraceStep] = Field(
        default_factory=list, description="思考链，前端按 timestamp 时间轴回放"
    )
    needConfirm: bool = Field(True, description="是否需要人工确认")
