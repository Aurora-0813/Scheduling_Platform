"""
Agent 调用指标存储（模块 10 的 /monitor/agent 数据源）

指标口径（已在 docs/api.md 与前端约定）
--------------------------------------
| 字段           | 口径                                                     |
| -------------- | -------------------------------------------------------- |
| `totalCalls`   | `/api/v1/agent/*` 的 HTTP 请求数（**按请求计，非按 token 计**）|
| `successRate`  | 仅按 HTTP 状态码判定：status < 400 记为成功               |
| `avgLatency`   | 单位**秒**，保留 1 位小数（前端面板直接展示，不要再换算） |
| `degradedCount`| 大模型降级次数。降级通常仍返回 HTTP 200，因此单列，        |
| `degradedRate` | 不并入 successRate —— 否则模块 4 大量降级会把主指标压到    |
|                | 80% 以下，看起来像系统故障，实际是设计好的降级            |

「埋点绝不影响业务」的三条保证
------------------------------
1. 所有写入异常全吞，只记日志。
2. Redis 用短超时（`REDIS_SOCKET_TIMEOUT`，0.5s）。
3. **内存镜像始终同步更新**，Redis 不可用时快照自动回落到内存，
   接口仍能返回有意义的数据，只多一个 `source` 字段标明来源。

内存镜像为什么能保证不低估
--------------------------
本进程是唯一写入方（uvicorn 单进程部署），因此内存镜像记录了
「进程启动至今」的完整数据。Redis 正常时读 Redis（跨重启、跨多 worker 的
累计值）；Redis 异常时读内存（本进程启动至今）。两种情况都不会漏计。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger
from app.core.redis import REDIS_ERRORS

__all__ = [
    "MetricsSnapshot",
    "MetricStore",
    "RedisMetricStore",
    "InMemoryMetricStore",
    "get_metric_store",
    "configure_metric_store",
    "reset_metric_store",
]

logger = get_logger(__name__)

# Redis 键
_KEY_TOTAL = "metrics:agent:total"
_KEY_SUCCESS = "metrics:agent:success"
_KEY_DEGRADED = "metrics:agent:degraded"
_KEY_LATENCY_MS = "metrics:agent:latency_ms"

# 键不设 TTL：累计值不应该自己消失。重置方式（写进 docs/deploy.md）：
#   redis-cli --scan --pattern 'metrics:agent:*' | xargs redis-cli DEL
# 或直接删除这四个键。
_AGENT_KEYS = (_KEY_TOTAL, _KEY_SUCCESS, _KEY_DEGRADED, _KEY_LATENCY_MS)


@dataclass(frozen=True)
class MetricsSnapshot:
    """某一时刻的指标快照。"""

    total_calls: int = 0
    success_calls: int = 0
    degraded_calls: int = 0
    latency_sum_ms: float = 0.0
    source: str = "memory"
    """数据来源：`redis`（跨重启累计）或 `memory`（本进程启动至今）。"""

    @property
    def error_calls(self) -> int:
        return max(0, self.total_calls - self.success_calls)

    @property
    def avg_latency_ms(self) -> float:
        if self.total_calls <= 0:
            return 0.0
        return self.latency_sum_ms / self.total_calls

    @property
    def success_rate(self) -> float:
        """成功率，0~1。无调用时返回 1.0（前端显示 100% 比 0% 合理）。"""
        if self.total_calls <= 0:
            return 1.0
        return self.success_calls / self.total_calls

    @property
    def degraded_rate(self) -> float:
        """降级率，0~1。"""
        if self.total_calls <= 0:
            return 0.0
        return self.degraded_calls / self.total_calls


class MetricStore(ABC):
    """指标存储接口。所有实现都**不得向上抛异常**。"""

    @abstractmethod
    async def record_agent_call(
        self, *, latency_ms: float, success: bool, degraded: bool = False
    ) -> None:
        """记录一次 Agent 调用。"""

    @abstractmethod
    async def snapshot(self) -> MetricsSnapshot:
        """读取当前快照。"""

    @abstractmethod
    async def reset(self) -> None:
        """清空指标。仅供测试与演示前重置使用。"""


class InMemoryMetricStore(MetricStore):
    """进程内计数器。生产降级实现 + 离线测试默认实现。"""

    def __init__(self) -> None:
        self.total_calls = 0
        self.success_calls = 0
        self.degraded_calls = 0
        self.latency_sum_ms = 0.0

    async def record_agent_call(
        self, *, latency_ms: float, success: bool, degraded: bool = False
    ) -> None:
        self.total_calls += 1
        if success:
            self.success_calls += 1
        if degraded:
            self.degraded_calls += 1
        self.latency_sum_ms += max(0.0, float(latency_ms))

    async def snapshot(self) -> MetricsSnapshot:
        return MetricsSnapshot(
            total_calls=self.total_calls,
            success_calls=self.success_calls,
            degraded_calls=self.degraded_calls,
            latency_sum_ms=self.latency_sum_ms,
            source="memory",
        )

    async def reset(self) -> None:
        self.total_calls = 0
        self.success_calls = 0
        self.degraded_calls = 0
        self.latency_sum_ms = 0.0


class RedisMetricStore(MetricStore):
    """
    Redis 累计指标 + 进程内镜像。

    - 写入：先更新内存镜像（必定成功），再尽力写 Redis。
    - 读取：优先 Redis；Redis 异常时回落到内存镜像。
    """

    def __init__(self, client: Any, *, local: InMemoryMetricStore | None = None) -> None:
        self._client = client
        self._local = local or InMemoryMetricStore()
        # 连续写失败次数，仅用于把重复的告警降噪成首条 WARN
        self._write_failures = 0
        self._warned = False

    async def record_agent_call(
        self, *, latency_ms: float, success: bool, degraded: bool = False
    ) -> None:
        # 内存镜像永远先更新，保证 Redis 挂掉时快照仍有数据
        await self._local.record_agent_call(
            latency_ms=latency_ms, success=success, degraded=degraded
        )

        try:
            pipe = self._client.pipeline(transaction=False)
            pipe.incr(_KEY_TOTAL)
            if success:
                pipe.incr(_KEY_SUCCESS)
            if degraded:
                pipe.incr(_KEY_DEGRADED)
            pipe.incrbyfloat(_KEY_LATENCY_MS, round(max(0.0, float(latency_ms)), 3))
            await pipe.execute()
            if self._warned:
                logger.info(
                    "Agent 埋点已恢复写入 Redis",
                    extra={"extra_fields": {"之前连续失败次数": self._write_failures}},
                )
            self._write_failures = 0
            self._warned = False
        except REDIS_ERRORS as exc:
            # 埋点绝不能影响业务：吞掉异常，只记日志。
            # 首次失败打 WARN，之后降为 DEBUG，避免 Redis 长时间不可用时刷爆日志。
            self._write_failures += 1
            if not self._warned:
                self._warned = True
                logger.warning(
                    "Agent 埋点写入 Redis 失败，已退化为进程内计数: %s: %s",
                    type(exc).__name__,
                    exc,
                )
            else:
                logger.debug("Agent 埋点写入 Redis 仍失败: %s", type(exc).__name__)

    async def snapshot(self) -> MetricsSnapshot:
        try:
            pipe = self._client.pipeline(transaction=False)
            for key in _AGENT_KEYS:
                pipe.get(key)
            total, success, degraded, latency = await pipe.execute()
            return MetricsSnapshot(
                total_calls=_to_int(total),
                success_calls=_to_int(success),
                degraded_calls=_to_int(degraded),
                latency_sum_ms=_to_float(latency),
                source="redis",
            )
        except REDIS_ERRORS as exc:
            logger.warning("读取 Agent 指标失败，回落到进程内镜像: %s: %s", type(exc).__name__, exc)
            return await self._local.snapshot()

    async def reset(self) -> None:
        await self._local.reset()
        try:
            await self._client.delete(*_AGENT_KEYS)
        except REDIS_ERRORS as exc:
            logger.warning("重置 Agent 指标失败: %s: %s", type(exc).__name__, exc)


def _to_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ==========================================================================
# 全局单例
# ==========================================================================
_store: MetricStore | None = None


def get_metric_store() -> MetricStore:
    """
    获取全局指标存储（惰性创建）。

    埋点中间件与 monitor 服务共用同一个实例，因此测试里
    `configure_metric_store(...)` 替换后两边同时生效。
    """
    global _store
    if _store is None:
        from app.core.redis import get_client

        client = get_client()
        _store = InMemoryMetricStore() if client is None else RedisMetricStore(client)
    return _store


def configure_metric_store(store: MetricStore) -> None:
    """替换全局指标存储。供测试与降级切换使用。"""
    global _store
    _store = store


def reset_metric_store() -> None:
    """丢弃全局实例，下次 `get_metric_store()` 重新按配置创建。"""
    global _store
    _store = None
