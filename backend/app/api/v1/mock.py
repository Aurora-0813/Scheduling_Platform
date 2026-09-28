"""
Mock 接口（模块 10）—— 仅 `DEBUG=true` 时注册

用途
----
让**前端（模块 8）与小程序（模块 3）不必等后端各模块做完就能开工**。
文档的 5.3 契约清单是一份共识，本文件把那份共识先变成可调用的接口：
前端照着 `docs/api.md` 写请求、照着这里的响应对字段，两边可并行。

设计原则
--------
1. **路径一律带 `/mock` 前缀**（`/api/v1/mock/...`），与真实接口（`/api/v1/...`）
   物理隔离。前端只需改一个 baseURL 常量即可切换，不需要改任何业务代码。
2. **响应结构与真实接口完全一致**：同样包 `{code, message, data}`，
   同样 camelCase，同样 `YYYY-MM-DD HH:mm:ss`。这是它唯一有价值的地方 ——
   结构不一致的 Mock 会让前端在联调时重写一遍解析逻辑。
3. **数据是常量**，不做增删改，不连数据库。因此**不能用于验收**。
4. **生产绝不注册**：注册开关在 `app/main.py` 的 `if settings.DEBUG:`。
   这一点有测试守着（`tests/api/test_mock_routes.py` 断言 DEBUG=false 时
   这些路径返回 404），避免有人为了调试把开关改成硬编码 True 后忘记改回来。

为什么自带 `/mock` 前缀却挂在 `/api/v1` 之下
--------------------------------------------
若挂到根路径（`/mock/...`），它会绕开 `/api/v1` 这层，导致 CORS、请求日志、
埋点三套中间件对它的作用范围与真实接口不一致 —— 前端在 Mock 上测通过的
跨域行为，切到真实接口可能不成立。走同一层前缀，中间件行为就完全一致。

`X-Agent-Degraded` 响应头的演示
--------------------------------
模块 4 的降级约定（见 `app/middlewares/agent_metrics.py`）是：
大模型降级时给响应加 `X-Agent-Degraded: 1`。本文件在
`POST /mock/agent/schedule?degraded=true` 时加上该头，
让模块 4 的成员能直接看到「约定长什么样」，也便于前端联调降级提示。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, File, Form, Path, Query, Request, Response, UploadFile

from app.api.v1 import mock_data
from app.core.response import ApiResponse, ok

__all__ = ["router"]

router = APIRouter(prefix="/mock", tags=["Mock 接口（仅 DEBUG，模块 10）"])


# ==========================================================================
# 模块 1：语音输入
# ==========================================================================
@router.post("/voice/asr", response_model=ApiResponse[dict], summary="语音转文字（Mock）")
async def mock_voice_asr(file: UploadFile = File(...)) -> ApiResponse[dict]:
    """FormData 上传音频文件 `file`。**不读取文件内容**，直接返回示例文本。"""
    return ok(mock_data.VOICE_ASR)


@router.post("/voice/format", response_model=ApiResponse[dict], summary="语音文本纠错（Mock）")
async def mock_voice_format(payload: dict = Body(...)) -> ApiResponse[dict]:
    return ok(mock_data.VOICE_FORMAT)


# ==========================================================================
# 模块 2：摄像头空间感知
# ==========================================================================
@router.post("/image/analyze", response_model=ApiResponse[dict], summary="空间识别（Mock）")
async def mock_image_analyze(file: UploadFile = File(...)) -> ApiResponse[dict]:
    return ok(mock_data.IMAGE_ANALYZE)


@router.post("/image/sketch", response_model=ApiResponse[dict], summary="草图分析（Mock）")
async def mock_image_sketch(file: UploadFile = File(...)) -> ApiResponse[dict]:
    return ok(mock_data.IMAGE_SKETCH)


# ==========================================================================
# 模块 3：移动端预约与通知
# ==========================================================================
@router.post("/orders/create", response_model=ApiResponse[dict], summary="创建预约（Mock）")
async def mock_order_create(payload: dict = Body(...)) -> ApiResponse[dict]:
    """
    注意：真实接口的 `userId` 来自 JWT（文档 5.1 明确禁止从请求体传入身份），
    本 Mock 不做鉴权，因此返回的 `orderId` 是常量，不区分用户。
    """
    return ok(mock_data.ORDER_CREATED)


@router.get("/orders/my", response_model=ApiResponse[dict], summary="我的预约（Mock）")
async def mock_orders_my() -> ApiResponse[dict]:
    return ok(mock_data.ORDERS_MY)


@router.put(
    "/orders/{orderId}/cancel", response_model=ApiResponse[dict], summary="取消预约（Mock）"
)
async def mock_order_cancel(orderId: int = Path(...)) -> ApiResponse[dict]:
    cancelled = dict(mock_data.ORDER_CREATED)
    cancelled["status"] = 3
    cancelled["statusText"] = "已取消"
    cancelled["orderId"] = orderId
    return ok(cancelled)


@router.get("/messages/unread", response_model=ApiResponse[dict], summary="未读消息（Mock）")
async def mock_messages_unread() -> ApiResponse[dict]:
    return ok(mock_data.MESSAGES_UNREAD)


# ==========================================================================
# 模块 4：核心调度 Agent
# ==========================================================================
@router.post("/agent/schedule", response_model=ApiResponse[dict], summary="智能调度（Mock）")
async def mock_agent_schedule(
    request: Request,
    response: Response,
    payload: dict = Body(default_factory=dict),
    degraded: bool = Query(
        default=False,
        description="演示用：为 true 时给响应加 `X-Agent-Degraded: 1` 头，模拟大模型降级。",
    ),
) -> ApiResponse[dict]:
    """
    模拟核心调度 Agent。

    `?degraded=true` 时会带上 `X-Agent-Degraded: 1` 响应头 —— 这是模块 4
    在**真实降级**（大模型输出无法解析、超时后走规则兜底）时应当设置的约定，
    由 `app/middlewares/agent_metrics.py` 读取并统计进 `degradedCalls`。
    """
    if degraded:
        response.headers["X-Agent-Degraded"] = "1"
    return ok(mock_data.AGENT_SCHEDULE)


# ==========================================================================
# 模块 5：资源与设备管理
# ==========================================================================
@router.get("/resources/spaces", response_model=ApiResponse[dict], summary="场地列表（Mock）")
async def mock_spaces() -> ApiResponse[dict]:
    return ok(mock_data.SPACES)


@router.post("/resources/spaces", response_model=ApiResponse[dict], summary="新增场地（Mock）")
async def mock_space_create(payload: dict = Body(...)) -> ApiResponse[dict]:
    return ok(mock_data.SPACE_CREATED)


@router.get("/resources/devices", response_model=ApiResponse[dict], summary="设备列表（Mock）")
async def mock_devices() -> ApiResponse[dict]:
    return ok(mock_data.DEVICES)


@router.put(
    "/resources/devices/{deviceId}", response_model=ApiResponse[dict], summary="修改设备（Mock）"
)
async def mock_device_update(
    payload: dict = Body(...), deviceId: int = Path(...)
) -> ApiResponse[dict]:
    updated = dict(mock_data.DEVICE_UPDATED)
    updated["id"] = deviceId
    return ok(updated)


# ==========================================================================
# 模块 6：AI 智能巡检
# ==========================================================================
@router.post("/inspect/submit", response_model=ApiResponse[dict], summary="提交巡检（Mock）")
async def mock_inspect_submit(
    file: UploadFile = File(...), spaceId: int = Form(...)
) -> ApiResponse[dict]:
    """FormData：图片 `file` + `spaceId`。**不读取文件内容**。"""
    return ok(mock_data.INSPECT_SUBMIT)


@router.get("/tickets/list", response_model=ApiResponse[dict], summary="工单列表（Mock）")
async def mock_tickets() -> ApiResponse[dict]:
    return ok(mock_data.TICKETS)


@router.put(
    "/tickets/{ticketId}/status", response_model=ApiResponse[dict], summary="处理工单（Mock）"
)
async def mock_ticket_status(
    payload: dict = Body(...), ticketId: int = Path(...)
) -> ApiResponse[dict]:
    updated = dict(mock_data.TICKET_UPDATED)
    updated["id"] = ticketId
    return ok(updated)


# ==========================================================================
# 模块 7：AI 冲突预警与智能通知
# ==========================================================================
@router.get("/conflicts/scan", response_model=ApiResponse[list], summary="冲突扫描（Mock）")
async def mock_conflicts() -> ApiResponse[list]:
    # 注意 data 是**数组**（文档 5.3 的契约如此），不是分页对象
    return ok(mock_data.CONFLICTS)


@router.post("/notify/generate", response_model=ApiResponse[dict], summary="生成通知文案（Mock）")
async def mock_notify(payload: dict = Body(...)) -> ApiResponse[dict]:
    return ok(mock_data.NOTIFY)


# ==========================================================================
# 模块 8：AI 数据洞察面板
# ==========================================================================
@router.get("/dashboard/stats", response_model=ApiResponse[dict], summary="面板统计（Mock）")
async def mock_dashboard_stats() -> ApiResponse[dict]:
    return ok(mock_data.DASHBOARD_STATS)


@router.get("/dashboard/report", response_model=ApiResponse[dict], summary="洞察报告（Mock）")
async def mock_dashboard_report() -> ApiResponse[dict]:
    return ok(mock_data.DASHBOARD_REPORT)


# ==========================================================================
# 监控埋点的演示工具
# ==========================================================================
@router.post(
    "/monitor/simulate", response_model=ApiResponse[dict], summary="模拟 Agent 调用（Mock）"
)
async def mock_monitor_simulate(
    # 查询参数用 camelCase 命名（与 path / form 参数一致，也符合文档 6.2）：
    # 参数名就是 URL 里的键，写成 error_ratio 会在 URL 里留下 snake_case，
    # 与全项目的 camelCase 契约不一致 —— 联调时最容易被误当成 bug 报告。
    count: int = Query(default=10, ge=1, le=500, description="模拟的调用次数"),
    errorRatio: float = Query(default=0.1, ge=0.0, le=1.0, description="失败占比"),
    degradedRatio: float = Query(default=0.2, ge=0.0, le=1.0, description="降级占比"),
    latencyMs: int = Query(default=3200, ge=0, le=60000, description="每次调用的模拟耗时（毫秒）"),
) -> ApiResponse[dict]:
    """
    往埋点里写 `count` 条模拟数据，供演示 `GET /api/v1/monitor/agent` 用。

    **为什么需要这个接口**：`/monitor/agent` 的数据来自 `/api/v1/agent/*` 的
    真实请求，而模块 4 尚未完成时这个接口恒为 `0 / 100.0 / 0.0`，面板做不出
    效果。用这个工具灌入数据后，前端面板与文档 5.3 的示例
    （`totalCalls: 128, successRate: 96.1, avgLatency: 3.2`）形态一致。

    **为什么不用「让 Mock 路由也被统计」这个更省事的办法**：那会让
    `/monitor/agent` 的数字里混进 Mock 流量，演示时无法区分「真实调用」
    与「造出来的调用」。埋点数据一旦失真，这个面板就失去意义了。

    它只在 `DEBUG=true` 时存在（本模块整体由 `app/main.py` 条件注册）。
    """
    from app.core.metrics import get_metric_store

    store = get_metric_store()

    # count >= 1 且两个 ratio >= 0，因此截断与向下取整等价
    error_count = int(count * errorRatio)
    degraded_count = int(count * degradedRatio)

    for index in range(count):
        await store.record_agent_call(
            latency_ms=float(latencyMs),
            # 前 error_count 条记为失败，模拟「状态码 >= 400」
            success=index >= error_count,
            degraded=index < degraded_count,
        )

    snapshot = await store.snapshot()
    return ok(
        {
            "written": count,
            "totalCalls": snapshot.total_calls,
            "degradedCalls": snapshot.degraded_calls,
            "source": snapshot.source,
        }
    )
