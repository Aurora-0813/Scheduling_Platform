"""
周期扫描器：可中断睡眠、异常不杀循环、抖动边界

第 2 条（异常不杀循环）与第 1 条（stop 后秒级退出）都是后台任务的经典坑：
前者会让推送在无人察觉的情况下永久停摆，后者会让应用关闭卡满一个扫描周期。
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.core.scheduler import PeriodicScanner


async def _noop() -> None:
    return None


# ---------- 构造校验 ----------


def test_interval_must_be_positive():
    with pytest.raises(ValueError):
        PeriodicScanner(_noop, interval_seconds=0)
    with pytest.raises(ValueError):
        PeriodicScanner(_noop, interval_seconds=-5)


def test_jitter_ratio_must_be_a_fraction():
    with pytest.raises(ValueError):
        PeriodicScanner(_noop, interval_seconds=1, jitter_ratio=1.0)
    with pytest.raises(ValueError):
        PeriodicScanner(_noop, interval_seconds=1, jitter_ratio=-0.1)


# ---------- 启动与停止 ----------


async def test_scanner_runs_the_job_repeatedly():
    calls: list[int] = []

    async def job():
        calls.append(1)
        return len(calls)

    scanner = PeriodicScanner(
        job, interval_seconds=0.01, initial_delay_seconds=0, name="t"
    )
    assert scanner.start() is True
    await asyncio.sleep(0.15)
    await scanner.stop()

    assert len(calls) >= 3
    assert scanner.running is False


async def test_stop_interrupts_a_long_sleep_within_a_second():
    """★ 用 asyncio.sleep(interval) 的写法会让关闭干等一整个扫描周期"""
    calls: list[int] = []

    async def job():
        calls.append(1)

    scanner = PeriodicScanner(
        job, interval_seconds=300, initial_delay_seconds=0, name="t"
    )
    scanner.start()
    await asyncio.sleep(0.05)  # 让它至少跑完第一轮，停在长睡眠上

    started = time.monotonic()
    await scanner.stop()
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, f"停止耗时 {elapsed:.2f}s，说明睡眠不可中断"
    assert calls, "首轮任务应先执行过"


async def test_stop_interrupts_the_initial_delay():
    """启动后立刻关闭（例如测试、或进程被 CI 拉起又马上杀掉）也不该卡住"""
    calls: list[int] = []

    async def job():
        calls.append(1)

    scanner = PeriodicScanner(
        job, interval_seconds=300, initial_delay_seconds=300, name="t"
    )
    scanner.start()

    started = time.monotonic()
    await scanner.stop()
    assert time.monotonic() - started < 1.0
    assert calls == [], "初次延迟未到，不应执行任务"


async def test_run_immediately_skips_the_initial_delay():
    calls: list[int] = []

    async def job():
        calls.append(1)

    scanner = PeriodicScanner(
        job,
        interval_seconds=300,
        initial_delay_seconds=300,
        run_immediately=True,
        name="t",
    )
    scanner.start()
    await asyncio.sleep(0.05)

    assert calls == [1]
    await scanner.stop()


async def test_start_is_idempotent():
    scanner = PeriodicScanner(_noop, interval_seconds=1, initial_delay_seconds=1)
    assert scanner.start() is True
    assert scanner.start() is False, "重复 start 不应起第二个循环"
    await scanner.stop()


async def test_stop_without_start_is_a_noop():
    scanner = PeriodicScanner(_noop, interval_seconds=1)
    await scanner.stop()
    assert scanner.running is False


async def test_scanner_can_be_restarted():
    calls: list[int] = []

    async def job():
        calls.append(1)

    scanner = PeriodicScanner(
        job, interval_seconds=0.01, initial_delay_seconds=0, name="t"
    )
    scanner.start()
    await asyncio.sleep(0.05)
    await scanner.stop()
    first_round = len(calls)

    scanner.start()
    await asyncio.sleep(0.05)
    await scanner.stop()

    assert len(calls) > first_round


# ---------- 异常隔离 ----------


async def test_job_exception_does_not_kill_the_loop():
    """★ 一次数据库抖动不应让后台推送永久停摆"""
    calls: list[int] = []

    async def job():
        calls.append(1)
        if len(calls) <= 2:
            raise RuntimeError("模拟单轮扫描失败")
        return "ok"

    scanner = PeriodicScanner(
        job, interval_seconds=0.01, initial_delay_seconds=0, name="t"
    )
    scanner.start()
    await asyncio.sleep(0.15)

    assert scanner.running is True, "循环不应因任务异常而退出"
    assert len(calls) >= 4, "异常轮次之后仍应继续执行"
    await scanner.stop()


async def test_run_once_swallows_errors_by_default():
    async def job():
        raise RuntimeError("模拟失败")

    scanner = PeriodicScanner(job, interval_seconds=1)
    assert await scanner.run_once() is None


async def test_run_once_can_reraise_for_manual_triggers():
    async def job():
        raise RuntimeError("模拟失败")

    scanner = PeriodicScanner(job, interval_seconds=1)
    with pytest.raises(RuntimeError):
        await scanner.run_once(raise_errors=True)


async def test_run_once_returns_the_job_result():
    scanner = PeriodicScanner(lambda: _async_value(42), interval_seconds=1)
    assert await scanner.run_once() == 42


async def _async_value(value: int) -> int:
    return value


async def test_stop_cancels_a_job_that_hangs():
    """任务卡死时 stop 必须强制取消，不能无限期等下去"""

    async def job():
        await asyncio.sleep(60)

    scanner = PeriodicScanner(
        job, interval_seconds=60, initial_delay_seconds=0, name="t"
    )
    scanner.start()
    await asyncio.sleep(0.05)

    started = time.monotonic()
    await scanner.stop(timeout=0.1)
    assert time.monotonic() - started < 1.0
    assert scanner.running is False


# ---------- 抖动 ----------


def test_jitter_stays_within_the_configured_ratio():
    scanner = PeriodicScanner(_noop, interval_seconds=100, jitter_ratio=0.1)
    for _ in range(200):
        delay = scanner._jittered(100)
        assert 90.0 <= delay <= 110.0


def test_jitter_is_disabled_when_ratio_is_zero():
    scanner = PeriodicScanner(_noop, interval_seconds=100, jitter_ratio=0.0)
    assert scanner._jittered(100) == 100


def test_zero_interval_never_produces_a_negative_delay():
    scanner = PeriodicScanner(_noop, interval_seconds=1, jitter_ratio=0.5)
    assert scanner._jittered(0) == 0


async def test_jitter_spreads_the_start_times():
    """多 worker 同时启动时应落在不同时刻，避免同一秒一起扫库"""
    scanner = PeriodicScanner(_noop, interval_seconds=100, jitter_ratio=0.1)
    samples = {round(scanner._jittered(100), 6) for _ in range(50)}
    assert len(samples) > 1
