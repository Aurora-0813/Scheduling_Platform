"""模块 4 的 HTTP 入口：`POST /api/v1/agent/schedule`（阶段 6 任务 6-1/6-2/6-3）。

## 本文件只做四件事

1. 从 JWT 解析身份（`Depends(get_current_user)`）
2. 调 `run_schedule()` 跑一次 Agent
3. 埋点（`record_call`）与思考链补写（`persist_agent_trace`）
4. 把结果包成主文档 5.2 的统一响应体

**不含任何业务逻辑**。方案怎么选、冲突怎么让，全在 `app/agent/` 里；
本文件若开始出现「如果预算不够就……」这类判断，说明分层写穿了。

## 为什么是 `async def`

主文档 3.3 与十三风险表明文禁止同步 `invoke()`：同步调用会占住事件循环，
`uvicorn` 单 worker 下并发能力直接归零——第二个请求要等第一个跑完 30 秒才被受理。
`run_schedule` 内部走 `astream()`，本文件 `await` 它，不阻塞任何人。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.agent.chains.builder import AgentUnavailableError, run_schedule
from app.core.response import ApiError, ok
from app.core.security import CurrentUser, get_current_user
from app.schemas.agent import ScheduleRequest
from app.services.agent_service import persist_agent_trace, record_call

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Agent"])


@router.post(
    "/agent/schedule",
    summary="提交自然语言调度需求，返回方案与思考链",
    response_description="统一响应体；降级路径同样是 HTTP 200",
)
async def schedule(
    req: ScheduleRequest,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """跑一次核心调度 Agent。

    **身份只来自 JWT。** 请求体里若夹带 `userId`，Pydantic 按 `extra="ignore"`
    丢掉（`AGENT-I-04` 验的就是这条）——不丢的话，任何人都能替别人预约。

    三条降级路径（超时 / 模型没交方案 / 工具异常）**都返回 HTTP 200**，
    `data.plan` 为 `null`、`message` 承载可读原因。这不是异常，是阶段 2 冻结的
    契约内路径；当成 500 会让前端不知道该渲染什么。
    详见 `app/agent/chains/builder.py::run_schedule` 的表格。

    唯一的非 200 是 `.env` 里 LLM 配置缺失（`AgentUnavailableError`）：
    那是服务端配置问题，不是用户输入问题，必须显式暴露，不能伪装成「AI 没想出方案」。
    """
    try:
        outcome = await run_schedule(
            text=req.text,
            user_id=user.id,
            image_context=req.imageContext,
        )
    except AgentUnavailableError as exc:
        # 503 而不是 500：这是「本服务暂时不具备该能力」，不是「服务器崩了」。
        # 同时把配置项的**名字**告诉运维，但绝不回显值（主文档 9.2）。
        raise ApiError(str(exc), http_status=503) from exc

    # 埋点**必须**在返回之前，且不能因为埋点失败而改变响应。
    record_call(outcome)

    await _persist_trace(req.text, user.id, outcome)

    return ok(outcome.data.model_dump(), message=outcome.message)


async def _persist_trace(request_text: str, user_id: int, outcome) -> None:  # noqa: ANN001
    """把完整思考链补写进 `reserve_order.agent_trace`（时序方案 (a)）。

    **失败只记日志，绝不影响响应。** trace 是答辩溯源用的附加值；
    写不进去不该让用户拿不到已经生成的方案——那属于「用附加值拖垮主流程」。
    """
    if not outcome.locked_order_id:
        # 本次没落库（没调 lock_resources、或调了但冲突、或桩期 orderId 恒为 None）。
        # 跳过而不是报错：没有订单就没有要更新的行。
        return

    try:
        written = await persist_agent_trace(
            order_id=outcome.locked_order_id,
            user_id=user_id,
            request_text=request_text,
            outcome=outcome,
        )
    except Exception:  # noqa: BLE001 - 补写失败不许穿透成 500
        logger.exception("agent_trace 补写异常 order_id=%s", outcome.locked_order_id)
        return

    if not written:
        logger.warning("agent_trace 补写未成功 order_id=%s", outcome.locked_order_id)
