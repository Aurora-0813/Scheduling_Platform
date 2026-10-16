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

import asyncio
import logging

from fastapi import APIRouter, Depends, Query

from app.agent.chains import parse as parse_chain
from app.agent.chains.builder import AgentUnavailableError, run_schedule
from app.core import flags as runtime_flags
from app.agent.chains.fast import run_schedule_fast
from app.api.deps import require_permission
from app.core.permissions import Permission
from app.services import agent_stream_service
from app.api.deps import CurrentUser, get_current_user
from app.core.error_codes import ErrorCode
from app.core.exceptions import BusinessError
from app.core.response import ApiResponse, ok
from app.schemas.agent import AgentModeRequest, ScheduleData, ScheduleRequest
from app.services.agent_service import persist_agent_trace, record_call

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Agent"])


@router.post(
    "/agent/schedule",
    summary="提交自然语言调度需求，返回方案与思考链",
    response_description="统一响应体；降级路径同样是 HTTP 200",
    response_model=ApiResponse[ScheduleData],
)
async def schedule(
    req: ScheduleRequest,
    user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[ScheduleData]:
    """跑一次核心调度 Agent。

    **身份只来自 JWT。** 请求体里若夹带 `userId`，Pydantic 按 `extra="ignore"`
    丢掉（`AGENT-I-04` 验的就是这条）——不丢的话，任何人都能替别人预约。

    三条降级路径（超时 / 模型没交方案 / 工具异常）**都返回 HTTP 200**，
    `data.plan` 为 `null`、`message` 承载可读原因。这不是异常，是阶段 2 冻结的
    契约内路径；当成 500 会让前端不知道该渲染什么。
    详见 `app/agent/chains/builder.py::run_schedule` 的表格。

    唯一的非 200 是 `.env` 里 LLM 配置缺失（`AgentUnavailableError`）：
    那是服务端配置问题，不是用户输入问题，必须显式暴露，不能伪装成「AI 没想出方案」。

    **走多轮 Agent 还是快速模式**（两条路都返回同一个 `ScheduleData`）：

    | 请求体 `fast` | 实际走哪条 |
    | --- | --- |
    | 不传（推荐） | 跟随后端全局开关 `deepMode`（`PUT /agent/mode` 切） |
    | `true` | 强制快速模式：全量候选 + 单次调用，约 5~10 秒，trace 只有 3 步 |
    | `false` | 强制多轮 Agent：6~8 轮，约 40~80 秒，思考链完整 |
    """
    # 走哪条路由**服务端定**（2026-10-13 修）：req.fast 不传时按全局 deepMode 开关，
    # 传了就按传的（三态，见 flags.resolve_fast 与 ScheduleRequest.fast 的说明）。
    # 此前这里只看 req.fast，而两端客户端都默认发 true —— 于是管理端那对
    # 「🧠 深度思考 / ⚡ 快速决策」按钮点了也换不了路，回 200 但行为不变。
    # 两个模式返回同一个 AgentOutcome，因此下面的埋点/trace 补写/响应组装全部复用。
    fast = runtime_flags.resolve_fast(req.fast)
    run = run_schedule_fast if fast else run_schedule
    # 落一条日志：这一屏最常被问的就是「怎么这么快就出结果了」，
    # 有这行可以直接回答「因为这轮走的是快速模式」。
    logger.info("agent/schedule 走 %s by user=%s", "快速模式" if fast else "深度模式", user.id)
    try:
        outcome = await run(
            text=req.text,
            user_id=user.id,
            image_context=req.imageContext,
        )
    except AgentUnavailableError as exc:
        # 503 而不是 500：这是「本服务暂时不具备该能力」，不是「服务器崩了」。
        # 同时把配置项的**名字**告诉运维，但绝不回显值（主文档 9.2）。
        #
        # 用 `BusinessError(code=41003)` 而不是自建异常类：41003
        # （`ErrorCode.AI_MODEL_UNAVAILABLE`）在正式版的 `_BUSINESS_ERROR_HTTP_STATUS`
        # 里已映射到 503，码表与 HTTP 语义都是现成的，不必再造一份。
        # 2026-09-28 合并前这里用的是模块 4 自建的 `core.response.ApiError`，
        # 正式版把异常体系收敛到了 `core/exceptions.py`，该名字已不存在。
        raise BusinessError(code=ErrorCode.AI_MODEL_UNAVAILABLE, message=str(exc)) from exc

    # 埋点**必须**在返回之前，且不能因为埋点失败而改变响应。
    record_call(outcome)

    await _persist_trace(req.text, user.id, outcome)

    return ok(outcome.data, message=outcome.message)


@router.post("/agent/parse", summary="把自然语言需求解析成可编辑条件 + 推荐（2026-10-13 新增）")
async def parse_schedule(
    req: ScheduleRequest,
    user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[dict]:
    """**一次模型调用**（5~10 秒）把需求解析成条件清单 + 推荐，供前端渲染成可编辑卡片。

    与深度模式的分工见 `agent/chains/parse.py` 的模块文档：
    AI 负责理解，规则负责判重 —— 本接口**不建单**，也不做可用性判断，
    那些交给前端的可用场地查询与 `/orders/create` 的事务。
    """
    result, elapsed_ms = await parse_chain.parse_request(
        text=req.text, image_context=req.imageContext
    )
    payload = result.model_dump()
    payload["latencyMs"] = elapsed_ms
    return ok(payload, message="解析完成")


@router.get("/agent/mode", summary="当前调度模式开关（2026-10-13 新增）")
async def get_mode(
    user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[dict]:
    """前端进页面读一次，据此决定要不要显示「🧠 深度思考」入口。

    **读接口对所有登录用户开放** —— 它只是个 UI 开关，不含任何敏感信息。
    """
    return ok({"deepMode": runtime_flags.deep_mode_enabled(), "flags": runtime_flags.all_flags()})


@router.put("/agent/mode", summary="切换调度模式开关（2026-10-13 新增）")
async def set_mode(
    req: AgentModeRequest,
    user: CurrentUser = Depends(require_permission(Permission.USER_UPDATE)),
) -> ApiResponse[dict]:
    """**随时**切换深度模式，不需要重启后端、更不需要重新打包 APK。

    鉴权用 `user:update`：它是**系统级**开关（影响所有用户的调度路径），
    不该由普通用户或资源管理员改 —— 云库里只有「系统管理员」的 `*` 命中它。

    ⚠️ **入参必须走请求体模型（2026-10-13 修）**。原先直接写
    `deepMode: bool | None = None` 这类标量参数，FastAPI 会把它们当成
    **query 参数** —— 前端发的是 JSON body，于是永远取到 None，
    接口回 200 + `未做改动`、开关却纹丝不动，还不报错。
    详见 `app/schemas/agent.py::AgentModeRequest` 的说明与实测记录。

    两个开关都可单独切；不传的那个保持原样（所以前端/curl 只传自己关心的那一个）。
    """
    # 两个开关都可单独切；不传的那个保持原样（所以前端/curl 只传自己关心的那一个）
    if req.deepMode is not None:
        runtime_flags.set_flag("deepMode", req.deepMode)
    if req.aiRecommend is not None:
        runtime_flags.set_flag("aiRecommend", req.aiRecommend)
    state = runtime_flags.all_flags()
    logger.info("调度模式已切换 %s by user=%s", state, user.id)
    bits = []
    if req.deepMode is not None:
        bits.append("深度模式已" + ("开启" if state["deepMode"] else "关闭"))
    if req.aiRecommend is not None:
        bits.append("AI 推荐已" + ("开启" if state["aiRecommend"] else "关闭"))
    return ok(state, message="；".join(bits) or "未做改动")


@router.post("/agent/schedule/task", summary="发起一次流式调度，返回 taskId（2026-10-13 新增）")
async def schedule_task(
    req: ScheduleRequest,
    # 与既有的 POST /agent/schedule 同口径：只校验登录。
    # 不挂 agent:schedule 权限 —— 云库里「普通用户」没有这个码，挂了会让小程序端 403，
    # 而老接口不挂，两个接口的准入就会不一致。
    user: CurrentUser = Depends(get_current_user),
):
    """发起调度但**不等结果**，立即返回 `{taskId}`；前端轮询 `/agent/schedule/progress` 取过程。

    为什么不是 SSE：APK 的 `uni.request` 收不到分块响应。既然后端要把事件缓存起来
    给小程序拉，Web 也走同一条路 —— 一套事件流，两种端共用，前端不必手写流解析。
    """
    task = agent_stream_service.create_task(user.id)
    # 后台跑，不阻塞响应 —— 这正是「不再用加载动画干等」的前提：
    # 前端先是立刻拿到 taskId，随后每 400ms 就能看到新内容冒出来。
    asyncio.create_task(
        agent_stream_service.run_task(
            task,
            text=req.text,
            user_id=user.id,
            image_context=req.imageContext,
            # 与 POST /agent/schedule **同一条口径**（2026-10-13）：不传 fast
            # 就跟全局 deepMode 开关。两个入口若各判各的，会出现「同一个开关、
            # 流式和非流式跑出不一样的模式」——比开关完全不生效更难查。
            fast=runtime_flags.resolve_fast(req.fast),
        )
    )
    return ok({"taskId": task.id})


@router.get("/agent/schedule/progress", summary="拉取流式调度的增量事件（2026-10-13 新增）")
async def schedule_progress(
    taskId: str,
    from_: int = Query(0, alias="from", ge=0, description="已经拿到的第几条，首次传 0"),
    # 与既有的 POST /agent/schedule 同口径：只校验登录。
    # 不挂 agent:schedule 权限 —— 云库里「普通用户」没有这个码，挂了会让小程序端 403，
    # 而老接口不挂，两个接口的准入就会不一致。
    user: CurrentUser = Depends(get_current_user),
):
    """返回 `from` 之后的新事件。**幂等**：重复拉同一段不会重复渲染。"""
    task = agent_stream_service.get_task(taskId, user.id)
    if task is None:
        raise BusinessError(code=ErrorCode.PARAM_INVALID, message="任务不存在或已过期，请重新发起")
    return ok(task.public(from_))


async def _persist_trace(request_text: str, user_id: int, outcome) -> None:
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
    except Exception:
        logger.exception("agent_trace 补写异常 order_id=%s", outcome.locked_order_id)
        return

    if not written:
        logger.warning("agent_trace 补写未成功 order_id=%s", outcome.locked_order_id)
