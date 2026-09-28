"""
周期扫描器（内置 asyncio 周期任务）

为什么不用 APScheduler：开发流程.md 的技术栈清单里没有它，
引入新依赖要同步改 requirements.txt / requirements.lock / 技术栈清单三处，
而本模块只需要「每 5 分钟跑一次任务」这一件事，标准库足够。

两个必须做对的细节：

1. **睡眠必须可中断**。`await asyncio.sleep(300)` 会让应用关闭干等 5 分钟，
   这是后台任务最常见的坑。这里用 asyncio.Event + asyncio.wait_for 实现，
   stop() 之后 1 秒内干净退出。
2. **单轮任务抛异常不得杀死循环**。只记日志，下一轮照常执行 ——
   否则一次数据库抖动就让后台推送永久停摆，而现场没人会注意到。
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

# 初次启动延迟的抖动比例：多 worker 同时启动时打散，避免同一秒一起扫库
DEFAULT_JITTER_RATIO = 0.1


class PeriodicScanner:
    """
    按固定间隔重复执行一个 async job。

    用法::

        scanner = PeriodicScanner(scan_and_notify_job, interval_seconds=300)
        scanner.start()          # 在 lifespan 里调用
        ...
        await scanner.stop()     # 关闭时调用
    """

    def __init__(
        self,
        job: Callable[[], Awaitable[Any]],
        *,
        interval_seconds: float,
        initial_delay_seconds: float = 0.0,
        name: str = "periodic-scanner",
        jitter_ratio: float = DEFAULT_JITTER_RATIO,
        run_immediately: bool = False,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds 必须大于 0")
        if not 0.0 <= jitter_ratio < 1.0:
            raise ValueError("jitter_ratio 必须落在 [0, 1) 区间")

        self._job = job
        self._interval = float(interval_seconds)
        self._initial_delay = float(initial_delay_seconds)
        self._name = name
        self._jitter_ratio = jitter_ratio
        self._run_immediately = run_immediately

        self._task: asyncio.Task | None = None
        # 先建好事件对象（不绑定循环），start() 时再重置
        self._stop_event = asyncio.Event()

    # ---------- 生命周期 ----------

    @property
    def name(self) -> str:
        return self._name

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> bool:
        """启动周期任务。已在运行则不做任何事，返回是否真的启动了"""
        if self.running:
            return False
        self._stop_event = asyncio.Event()
        self._task = asyncio.get_running_loop().create_task(
            self._run(), name=self._name
        )
        logger.info(
            "周期任务 %s 已启动：间隔 %.0fs，首次延迟 %.0fs",
            self._name,
            self._interval,
            self._initial_delay,
        )
        return True

    async def stop(self, timeout: float = 5.0) -> None:
        """
        停止并等待任务退出。

        停止信号会立即打断正在进行的睡眠，因此正常情况下 1 秒内即可返回。
        """
        task = self._task
        if task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("周期任务 %s 未在 %.1fs 内退出，强制取消", self._name, timeout)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
            logger.info("周期任务 %s 已停止", self._name)

    # ---------- 主循环 ----------

    async def _run(self) -> None:
        try:
            if not self._run_immediately:
                if not await self._sleep(self._initial_delay):
                    return
            while True:
                await self.run_once()
                if not await self._sleep(self._interval):
                    return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 —— 兜底：循环本身不允许因异常退出
            logger.exception("周期任务 %s 意外退出", self._name)

    async def run_once(self, *, raise_errors: bool = False) -> Any:
        """
        执行一轮任务。

        默认吞掉异常并记日志（保证循环不死）；测试或手动触发时可
        传 raise_errors=True 让异常浮上来。
        """
        started = time.monotonic()
        try:
            result = await self._job()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("周期任务 %s 单轮执行失败，将在下一轮重试", self._name)
            if raise_errors:
                raise
            return None
        logger.info(
            "周期任务 %s 单轮完成，耗时 %.2fs", self._name, time.monotonic() - started
        )
        return result

    async def _sleep(self, seconds: float) -> bool:
        """
        可被 stop() 立即打断的睡眠。

        返回 False 表示收到停止信号，调用方应结束循环。
        """
        delay = self._jittered(seconds)
        if delay <= 0:
            return not self._stop_event.is_set()
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            # 正常睡满，未收到停止信号
            return True
        return False

    def _jittered(self, seconds: float) -> float:
        """加 ±jitter_ratio 的抖动，打散多 worker 的启动时刻"""
        if seconds <= 0 or self._jitter_ratio <= 0:
            return max(seconds, 0.0)
        delta = seconds * self._jitter_ratio
        return max(seconds + random.uniform(-delta, delta), 0.0)


__all__ = ["PeriodicScanner", "DEFAULT_JITTER_RATIO"]
