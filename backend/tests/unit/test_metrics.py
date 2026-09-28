"""
Agent 埋点指标测试

重点验证三件事：
1. 口径正确：totalCalls 按请求计、avgLatency 单位毫秒求和后再平均、
   successRate 只看 HTTP 状态码、降级单列不并入成功率。
2. Redis 不可用时埋点不抛异常，且快照回落到内存镜像后**不低估**。
3. 中间件层的「埋点打死也不影响业务」由 test_agent_metrics_middleware 覆盖（P6）。
"""

from __future__ import annotations

import pytest

from app.core.metrics import (
    InMemoryMetricStore,
    MetricsSnapshot,
    RedisMetricStore,
    configure_metric_store,
    get_metric_store,
    reset_metric_store,
)
from tests.fakes.fake_redis import FakeRedis

pytestmark = pytest.mark.unit


# ==========================================================================
# 口径
# ==========================================================================
def test_snapshot_rates_with_no_calls() -> None:
    """无调用时成功率为 1.0（面板显示 100% 比 0% 合理），降级率为 0。"""
    snapshot = MetricsSnapshot()
    assert snapshot.success_rate == 1.0
    assert snapshot.degraded_rate == 0.0
    assert snapshot.avg_latency_ms == 0.0
    assert snapshot.error_calls == 0


def test_snapshot_computes_rates_and_average() -> None:
    snapshot = MetricsSnapshot(
        total_calls=4,
        success_calls=3,
        degraded_calls=1,
        latency_sum_ms=800.0,
    )
    assert snapshot.error_calls == 1
    assert snapshot.avg_latency_ms == 200.0
    assert snapshot.success_rate == 0.75
    assert snapshot.degraded_rate == 0.25


async def test_in_memory_records_and_snapshots() -> None:
    store = InMemoryMetricStore()
    await store.record_agent_call(latency_ms=100.0, success=True)
    await store.record_agent_call(latency_ms=200.0, success=True)
    await store.record_agent_call(latency_ms=300.0, success=False, degraded=True)

    snapshot = await store.snapshot()
    assert snapshot.total_calls == 3
    assert snapshot.success_calls == 2
    assert snapshot.error_calls == 1
    assert snapshot.degraded_calls == 1
    # avgLatency 单位是秒，内部按毫秒累加后再平均，避免逐次平均带来的精度损失
    assert snapshot.avg_latency_ms == pytest.approx(200.0)
    assert snapshot.success_rate == pytest.approx(2 / 3)
    assert snapshot.degraded_rate == pytest.approx(1 / 3)
    assert snapshot.source == "memory"


async def test_degraded_call_counts_as_success_when_http_ok() -> None:
    """
    降级的大模型调用通常仍返回 HTTP 200，因此计入 successCalls，
    只在 degradedCount 里单独体现 —— 否则模块 4 大量降级会把 successRate
    压到 80% 以下，看起来像系统故障。
    """
    store = InMemoryMetricStore()
    await store.record_agent_call(latency_ms=50.0, success=True, degraded=True)
    snapshot = await store.snapshot()
    assert snapshot.success_calls == 1
    assert snapshot.success_rate == 1.0
    assert snapshot.degraded_calls == 1
    assert snapshot.degraded_rate == 1.0


async def test_reset_clears_counters() -> None:
    store = InMemoryMetricStore()
    await store.record_agent_call(latency_ms=10.0, success=True)
    await store.reset()
    snapshot = await store.snapshot()
    assert snapshot.total_calls == 0
    assert snapshot.latency_sum_ms == 0.0


# ==========================================================================
# Redis 实现
# ==========================================================================
async def test_redis_store_accumulates_in_redis() -> None:
    fake = FakeRedis()
    store = RedisMetricStore(fake)
    await store.record_agent_call(latency_ms=0.0, success=True)
    await store.record_agent_call(latency_ms=1500.0, success=True)
    await store.record_agent_call(latency_ms=3000.0, success=False)

    snapshot = await store.snapshot()
    assert snapshot.source == "redis"
    assert snapshot.total_calls == 3
    assert snapshot.success_calls == 2
    assert snapshot.avg_latency_ms == pytest.approx(1500.0)


async def test_redis_store_reads_are_shared_across_instances() -> None:
    """两个实例读同一个 Redis，验证指标是跨进程累计的（与内存实现的关键差异）。"""
    fake = FakeRedis()
    writer = RedisMetricStore(fake)
    reader = RedisMetricStore(fake)
    await writer.record_agent_call(latency_ms=100.0, success=True)

    snapshot = await reader.snapshot()
    assert snapshot.source == "redis"
    assert snapshot.total_calls == 1


async def test_redis_store_degrades_without_raising() -> None:
    fake = FakeRedis()
    store = RedisMetricStore(fake)
    await store.record_agent_call(latency_ms=120.0, success=True)

    fake.fail_next(100)
    # 写入失败不抛异常（埋点绝不能影响业务）
    await store.record_agent_call(latency_ms=80.0, success=True)
    # 读取失败回落到内存镜像：本进程启动至今的 2 次调用都在，不低估
    snapshot = await store.snapshot()
    assert snapshot.source == "memory"
    assert snapshot.total_calls == 2
    assert snapshot.avg_latency_ms == pytest.approx(100.0)


async def test_redis_store_recovers_after_outage() -> None:
    """Redis 恢复后应重新写回 Redis，且计数器告警状态复位。"""
    fake = FakeRedis()
    store = RedisMetricStore(fake)
    fake.fail_next(1)
    await store.record_agent_call(latency_ms=10.0, success=True)
    assert (await store.snapshot()).source == "redis"

    await store.record_agent_call(latency_ms=10.0, success=True)
    await store.record_agent_call(latency_ms=10.0, success=True)
    snapshot = await store.snapshot()
    assert snapshot.source == "redis"
    # 第 1 次写失败丢了，后 2 次成功
    assert snapshot.total_calls == 2


async def test_redis_store_reset_clears_both_layers() -> None:
    fake = FakeRedis()
    store = RedisMetricStore(fake)
    await store.record_agent_call(latency_ms=10.0, success=True)
    await store.reset()
    assert (await store.snapshot()).total_calls == 0


# ==========================================================================
# 全局单例
# ==========================================================================
def test_global_store_can_be_replaced() -> None:
    """中间件与 monitor 服务必须拿到同一个实例，否则埋点写了但读不到。"""
    reset_metric_store()
    memory = InMemoryMetricStore()
    configure_metric_store(memory)
    assert get_metric_store() is memory
    reset_metric_store()
