"""
系统监控接口（模块 10）

`GET /api/v1/monitor/agent` 是文档 5.3 列出的契约接口，返回大模型调用的
统计指标。数据由 `app/middlewares/agent_metrics.py` 的中间件自动收集，
本文件只做「取数 → 包统一响应体」，不含任何统计逻辑。

本接口**不鉴权**
---------------
理由：它是给前端监控面板（模块 8）与答辩演示用的只读统计，内容不敏感
（调用次数、成功率、耗时）。前端面板常在登录态之外加载（比如登录页的
健康指示），加鉴权反而会让面板在未登录时整块报错。

代价与边界：它暴露了「本服务调用大模型的频率」。若将来指标里加入了业务
维度（按用户/按接口的细分统计），就必须改成 `Depends(require_permission(...))`
—— 那时的数据已经能反推出业务量。当前实现刻意**不**接受任何筛选参数，
就是为了不给这条演进留隐性口子。修改本文件时请一并复核这个决定。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.response import ApiResponse, ok
from app.schemas.monitor import AgentMonitorOut
from app.services import monitor_service

__all__ = ["router"]

router = APIRouter(prefix="/monitor", tags=["系统监控（模块 10）"])


@router.get(
    "/agent",
    response_model=ApiResponse[AgentMonitorOut],
    # 关键：detail=false 时把 None 字段从 JSON 里剔除，使响应回到文档 5.3
    # 约定的「三个字段」。不设它的话会返回一堆 null，前端要额外判空。
    response_model_exclude_none=True,
    summary="大模型调用统计",
    description=(
        "统计范围：`/api/v1/agent/*` 的全部 HTTP 请求（由中间件自动收集，"
        "业务代码无需埋点）。\n\n"
        "**单位约定**（务必与前端面板文案一致）：\n"
        "- `successRate`：百分比，0~100，1 位小数（`96.1` 表示 96.1%）；\n"
        "- `avgLatency`：**秒**，1 位小数（`3.2` 表示 3.2 秒）；\n"
        "- `totalCalls`：请求数，不是 token 数。\n\n"
        "成功仅按 HTTP 状态码判定（`< 400`）。大模型降级通常仍返回 200，"
        "因此单列为 `degradedCalls` / `degradedRate`，不并入 `successRate`。\n\n"
        "`?detail=true` 时额外返回 `successCalls` / `errorCalls` / "
        "`degradedCalls` / `degradedRate` / `source`；\n"
        "`source` 为 `redis` 表示跨重启累计，`memory` 表示 Redis 不可用、"
        "数据仅为本进程启动至今。"
    ),
)
async def agent_metrics(
    detail: bool = Query(
        default=False,
        description="是否返回详细字段（成功/失败/降级明细与数据来源）。",
    ),
) -> ApiResponse[AgentMonitorOut]:
    """
    读取 Agent 调用指标。

    单位换算（0~1 → 百分比、毫秒 → 秒）在 `monitor_service` 里完成，
    本函数只负责把 `detail` 透传下去。
    """
    return ok(await monitor_service.get_agent_metrics(detail=detail))
