"""
Agent 调用指标汇总服务（模块 10）

本模块是**唯一**做单位换算的地方
------------------------------
`MetricStore` 内部记的是「0~1 的比值」与「毫秒」，而接口契约
（`app/schemas/monitor.py` 的表）要求「百分比」与「秒」。

换算只在这一层做。router 不再换算，`schemas/monitor.py` 也不做 ——
散在两处必然出现「某天改了换算、另一处忘了改」，前端会看到形如
`successRate: 0.961` 或 `avgLatency: 3200` 的错值。

为什么不用 `round()` 之后直接拼
------------------------------
`round()` 返回的是浮点数，`round(96.05, 1)` 这类边界会有二进制表示问题
（得到 96.0 而非 96.1）。展示型指标 1 位小数足够，这个误差可接受，
但**不能**把 round 后的值再拿去做判定（本模块不做任何判定，只做展示）。
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.core.metrics import MetricsSnapshot, get_metric_store
from app.schemas.monitor import AgentMonitorOut

__all__ = [
    "get_agent_metrics",
    "reset_agent_metrics",
    "SOURCE_REDIS",
    "SOURCE_MEMORY",
]

logger = get_logger(__name__)

SOURCE_REDIS = "redis"
SOURCE_MEMORY = "memory"

# 0~1 比值 → 百分比
_PERCENT = 100.0
# 毫秒 → 秒
_MS_PER_SECOND = 1000.0

# 展示精度：1 位小数（契约见 app/schemas/monitor.py）
_DIGITS = 1


async def _snapshot() -> MetricsSnapshot:
    """
    读快照。**任何异常都降级为全 0 快照**，不让监控接口 500。

    各个 `MetricStore` 实现本身已经吞掉 Redis 异常，这里再包一层是防御
    `get_metric_store()` 这一侧（惰性创建 Redis 客户端时也可能抛）。
    监控接口是给人看的诊断面板，它自己挂掉就失去意义了。
    """
    try:
        return await get_metric_store().snapshot()
    except Exception as exc:  # noqa: BLE001 - 监控接口不能因埋点故障而失败
        logger.warning("读取 Agent 指标失败，返回空快照: %s: %s", type(exc).__name__, exc)
        return MetricsSnapshot()


async def get_agent_metrics(*, detail: bool = False) -> AgentMonitorOut:
    """
    汇总 `/api/v1/agent/*` 的调用指标。

    :param detail: 为 True 时额外返回 `successCalls` / `errorCalls` /
        `degradedCalls` / `degradedRate` / `source`；为 False 时这些字段
        保持 None，由路由的 `response_model_exclude_none=True` 从 JSON 里剔除。

    契约的三个字段（`totalCalls` / `successRate` / `avgLatency`）
    **任何情况下都会返回**，无调用时是 `0 / 100.0 / 0.0`。
    """
    snapshot = await _snapshot()

    out = AgentMonitorOut(
        total_calls=snapshot.total_calls,
        # success_rate 返回 0~1；无调用时为 1.0 → 展示 100%。
        # 前端显示「暂无调用，成功率 100%」比「0%」合理：0% 像是全部失败。
        success_rate=round(snapshot.success_rate * _PERCENT, _DIGITS),
        avg_latency=round(snapshot.avg_latency_ms / _MS_PER_SECOND, _DIGITS),
    )

    if not detail:
        return out

    out.success_calls = snapshot.success_calls
    out.error_calls = snapshot.error_calls
    out.degraded_calls = snapshot.degraded_calls
    out.degraded_rate = round(snapshot.degraded_rate * _PERCENT, _DIGITS)
    out.source = snapshot.source
    return out


async def reset_agent_metrics() -> None:
    """
    清空指标。仅供演示前重置与测试使用。

    对外没有暴露成接口：一个匿名可调用的「清零埋点」接口本身就是个洞
    （任何人都能把统计结果抹掉）。需要重置时按 docs/deploy.md 里的
    `redis-cli` 命令手工执行。
    """
    try:
        await get_metric_store().reset()
    except Exception as exc:  # noqa: BLE001 - 重置失败不应让调用方失败
        logger.warning("重置 Agent 指标失败: %s: %s", type(exc).__name__, exc)
