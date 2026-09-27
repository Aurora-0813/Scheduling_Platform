"""Tool 5/5：`submit_plan` —— 让模型**通过调用工具**交出最终方案。

## 这个 Tool 是增补项，不是主文档 5.3 列的四个之一

阶段 4 §3.4 的判断：主文档 5.3 描述 Tool 清单时用的是「**包括**」而非「仅限」，
所以可以增补。**这是「建议」而非既定事项**，需在 M3 评审时同步团队，
避免被认为擅自扩大接口范围——已记入 `docs/spec/done/stage-04-completion.md`。

## 它解决什么问题

不让模型在自由文本里吐 JSON，而是把方案作为**工具调用的参数**提交。
差别在于校验发生在哪一层：

| | 自由文本吐 JSON | 调 `submit_plan` |
| --- | --- | --- |
| 结构校验 | 事后正则/容错解析，错在哪全靠猜 | Pydantic 当场校验，字段名与类型都管 |
| 失败表现 | 模型「看起来」给了方案，解析出来是空 | 参数不合法则工具调用失败，模型收到明确错误 |
| 落到 `plan` 字段 | 需从自然语言里抠 | 直接就是 Tool 的入参 |

注意这**没有取消**主文档 7.4 要求的「JSON 解析容错」——模型仍可能不调本工具、
直接在正文里写方案，那条降级路径在 `app/agent/chains/builder.py` 里照常实现。

## 它不写库

方案只随**返回值**走：调用方从 `ToolMessage.content` 里取。写库一律走 `lock_resources`
——「AI 中台只输出建议、方案、文案」（主文档 4.3）。

**为什么不做成 ContextVar 让 API 层直接读**：Tool 是由 LangGraph 的 `ToolNode` 通过
`asyncio.gather()` 跑的，子任务里的 `ContextVar.set()` 回不到父 context。详见
`app/agent/context.py` 的说明。
"""
from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field

__all__ = ["submit_plan", "PlanPayload", "SubmitPlanArgs"]


class PlanPayload(BaseModel):
    """一个可执行方案。字段与响应契约 `app/schemas/agent.py::Plan` **逐一对应**。

    两处必须同时改：改这里不改 `Plan`，模型交出的字段会在响应里静默消失。
    `tests/test_agent_tools.py::test_submit_plan_payload_matches_response_schema` 起护栏作用。
    """

    spaceId: int | None = Field(None, description="场地 ID；无方案时留空")
    spaceName: str | None = Field(None, description="场地名称")
    deviceIds: list[int] = Field(
        default_factory=list, description="设备 ID 数组；无设备传 []"
    )
    startTime: str | None = Field(None, description="开始时间，格式 YYYY-MM-DD HH:mm:ss")
    endTime: str | None = Field(None, description="结束时间，格式 YYYY-MM-DD HH:mm:ss")
    reason: str | None = Field(
        None,
        description="方案说明，**必须写清降级/替代的理由**（例如「预算内保场地，投影由两台降级为一台」）",
    )


class SubmitPlanArgs(BaseModel):
    """`submit_plan` 的入参 schema（阶段 4 §3.4 冻结签名的落地形状）。"""

    plan: PlanPayload = Field(..., description="主方案。无可行方案时不要调用本工具")
    backup_plan: PlanPayload | None = Field(
        None, description="备选方案；没有就省略，不要编一个"
    )
    reason: str = Field(
        ..., description="整体说明：为什么选这个方案、若做过降级/替代则说明理由"
    )


@tool("submit_plan", args_schema=SubmitPlanArgs)
async def submit_plan(plan: PlanPayload, backup_plan: PlanPayload | None = None, reason: str = "") -> dict:
    """交出最终调度方案。**方案确定后必须调用本工具**，这是交付方案的正规出口。

    什么时候用：已经查过场地与设备、权衡完毕、确定了主方案之后调用，每次运行**只调一次**。
    不要在还没查过场地设备时调用；也**不要**只在回复正文里写方案而不调用本工具。

    没有可行方案时（例如需求自相矛盾、或查询结果为空）**不要调用本工具**，
    改为直接在回复里说明原因并给出修改建议——系统会把你的说明原样返回给用户。

    Args:
        plan: 主方案，需给出 spaceId、spaceName、deviceIds、startTime、endTime，
            并在 reason 里写清为什么这么选；做过降级或替代的，理由必须写明。
        backup_plan: 备选方案，结构与 plan 相同。没有就不传。
        reason: 整体说明，概括本次决策（含冲突权衡的结论）。

    Returns:
        {"ok": true, "accepted": true, "message": "方案已提交，无需再次调用本工具。"}
    """
    payload = plan.model_dump()
    # 顶层 reason 与 plan.reason 是两处；plan.reason 缺省时用顶层的补上，
    # 避免「模型写了理由但写在另一个字段」导致响应里 reason 为空。
    if not payload.get("reason") and reason:
        payload["reason"] = reason

    # 返回值**回显方案**，这不是冗余：调用方（`chains/builder.py`）要拿这次提交的方案
    # 组装响应体，而它只能从 LangGraph 的 messages 流里取——Tool 内的 ContextVar 写入
    # 跨不过 `asyncio.gather` 的 context 拷贝（详见 `app/agent/context.py` 的说明）。
    # 回显后，`ToolMessage.content` 里就有完整方案，屏 3 的 observation 也顺带好读了。
    return {
        "ok": True,
        "accepted": True,
        "message": "方案已提交，无需再次调用本工具。",
        "plan": payload,
        "backupPlan": backup_plan.model_dump() if backup_plan is not None else None,
        "reason": reason or payload.get("reason"),
    }
