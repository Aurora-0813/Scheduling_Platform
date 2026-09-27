"""核心调度 Agent 模块的请求 / 响应契约（主文档 5.3 模块 4）。

本模块的返回结构会被前端与小程序渲染，字段一经冻结不得中途更改——
主线一屏 3 要按 TraceStep 逐字段渲染 40 秒思考过程，改一个字段演示就崩。

命名约定：传输字段一律 camelCase（主文档 6.2）。
这里**直接**用 camelCase 作 Python 字段名，不走 alias 方案。原因是 alias 方案
存在一个静默失败模式：序列化时漏掉 by_alias=True，线上字段会悄悄变回
snake_case，前端取值拿到 None 却不报错，排查成本极高。直接命名没有这个风险。
"""

from pydantic import BaseModel, Field

__all__ = ["ScheduleRequest", "TraceStep", "Plan", "ScheduleData"]


class ScheduleRequest(BaseModel):
    """POST /api/v1/agent/schedule 请求体（主文档 5.3 模块 4）。

    注意：**没有 userId 字段**。调用者身份一律从 JWT 解析（主文档 5.1、9.1），
    请求体夹带 userId 会被忽略——若从请求体取，任何人都能替别人预约。
    """

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

    | 情形                 | plan   | needConfirm | message              |
    |----------------------|--------|-------------|----------------------|
    | 正常                 | 方案   | True        | "操作成功"           |
    | 无可行方案           | None   | True        | 人工可读原因+修改建议 |
    | 大模型输出格式错乱   | None   | True        | 模型返回的自然语言文本 |

    第三种是主文档 10.2 要求必须测的契约内降级路径——当成异常抛 500 会让
    前端不知道该展示什么。
    """

    plan: Plan | None = Field(None, description="主方案；无可行方案时为 None")
    backupPlan: Plan | None = Field(None, description="备选方案")
    trace: list[TraceStep] = Field(
        default_factory=list, description="思考链，前端按 timestamp 时间轴回放"
    )
    needConfirm: bool = Field(True, description="是否需要人工确认")
