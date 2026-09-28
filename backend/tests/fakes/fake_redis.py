"""
假 Redis（仅测试用）

目的
----
让 **`RedisTokenStore` 本体的命令序列** 可以在没有真实 Redis 的情况下被测试，
而不是只测内存实现。这很重要：`RedisTokenStore.rotate_refresh` 的原子性
依赖 `pipeline(transaction=True)` 里 `GET` 与 `DEL` 的相对顺序，只有让真实
实现跑起来才能验证这个顺序没写错。

实现范围
--------
只实现本项目实际用到的命令：
`get` / `set(ex=)` / `delete` / `exists` / `incr` / `incrbyfloat` /
`sadd` / `srem` / `smembers` / `expire` / `ping` / `getdel`，
以及 `pipeline(transaction=...)`。

行为对齐真实 Redis 的几点：
- 默认 `decode_responses=True`，字符串命令返回 `str`，不存在的键返回 `None`。
- `pipeline.execute()` 在**执行时**才运行命令体（与 Redis 一致：命令入队时
  不执行），因此事务内的 `GET` 能看到同一事务里前一条 `DEL` 的效果。
- 过期用 `time.monotonic()` 判断，`ttl` 可被测试直接覆写成极小值。
- Redis 单线程语义 → 用一把 `asyncio.Lock` 保护事务执行，模拟「事务之间不交错」。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from redis.exceptions import RedisError

__all__ = ["FakeRedis", "FakeRedisUnavailable"]


class FakeRedisUnavailable(RedisError):
    """
    模拟连接失败。测试里通过 `fake.fail_next()` 触发，用于验证降级路径。

    必须继承 `redis.exceptions.RedisError`，否则不会被
    `app.core.redis.REDIS_ERRORS` 捕获，降级逻辑就走不到。
    """


class _FakePipeline:
    """命令队列。`execute()` 时才真正执行。"""

    def __init__(self, redis: FakeRedis, transaction: bool) -> None:
        self._redis = redis
        self._transaction = transaction
        self._queue: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _enqueue(self, name: str, *args: Any, **kwargs: Any) -> _FakePipeline:
        self._queue.append((name, args, kwargs))
        return self

    def get(self, key: str) -> _FakePipeline:
        return self._enqueue("get", key)

    def set(self, key: str, value: Any, **kwargs: Any) -> _FakePipeline:
        return self._enqueue("set", key, value, **kwargs)

    def delete(self, *keys: str) -> _FakePipeline:
        return self._enqueue("delete", *keys)

    def exists(self, key: str) -> _FakePipeline:
        return self._enqueue("exists", key)

    def incr(self, key: str) -> _FakePipeline:
        return self._enqueue("incr", key)

    def incrbyfloat(self, key: str, amount: float) -> _FakePipeline:
        return self._enqueue("incrbyfloat", key, amount)

    def sadd(self, key: str, *members: str) -> _FakePipeline:
        return self._enqueue("sadd", key, *members)

    def srem(self, key: str, *members: str) -> _FakePipeline:
        return self._enqueue("srem", key, *members)

    def smembers(self, key: str) -> _FakePipeline:
        return self._enqueue("smembers", key)

    def expire(self, key: str, seconds: int) -> _FakePipeline:
        return self._enqueue("expire", key, seconds)

    def getdel(self, key: str) -> _FakePipeline:
        return self._enqueue("getdel", key)

    async def execute(self) -> list[Any]:
        # transaction=True 时持有锁，模拟 MULTI/EXEC 期间不插入其他客户端命令
        if self._transaction:
            async with self._redis._lock:
                return self._run()
        return self._run()

    def _run(self) -> list[Any]:
        results = []
        for name, args, kwargs in self._queue:
            results.append(self._redis._execute(name, args, kwargs))
        self._queue.clear()
        return results

    # 支持 `async with redis.pipeline() as pipe:` 的写法
    async def __aenter__(self) -> _FakePipeline:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None


class FakeRedis:
    """最小的异步 Redis 替身。"""

    def __init__(self) -> None:
        self._strings: dict[str, str] = {}
        self._sets: dict[str, set[str]] = {}
        self._expiry: dict[str, float] = {}
        self._lock = asyncio.Lock()
        # 故障注入：>0 时接下来的这么多次操作抛 FakeRedisUnavailable
        self._fail_remaining = 0

    # ---------- 测试辅助 ----------
    def fail_next(self, times: int = 1) -> None:
        """让接下来 `times` 次操作失败，用于验证降级路径。`fail_next(0)` 等于恢复。"""
        self._fail_remaining = times

    def recover(self) -> None:
        """
        清除故障注入，恢复正常。

        典型用法是「让登录链路上的 Redis 操作全失败，再让后续请求恢复正常」：
        不恢复的话，注入的失败次数会一直影响同一个用例里后面的请求，
        断言就会指向一个与被测行为无关的原因（例如期望 401 却得到 503）。
        """
        self._fail_remaining = 0

    def keys(self) -> list[str]:
        self._purge_all()
        return sorted(set(self._strings) | set(self._sets))

    def ttl(self, key: str) -> float | None:
        """剩余秒数；键不存在或永久返回 None。"""
        expires_at = self._expiry.get(key)
        if expires_at is None:
            return None
        return max(0.0, expires_at - time.monotonic())

    async def aclose(self) -> None:
        return None

    # ---------- 内部 ----------
    def _check_failure(self) -> None:
        if self._fail_remaining > 0:
            self._fail_remaining -= 1
            raise FakeRedisUnavailable("注入的连接故障")

    def _expired(self, key: str) -> bool:
        expires_at = self._expiry.get(key)
        if expires_at is not None and expires_at <= time.monotonic():
            self._strings.pop(key, None)
            self._sets.pop(key, None)
            self._expiry.pop(key, None)
            return True
        return False

    def _purge_all(self) -> None:
        for key in list(set(self._strings) | set(self._sets) | set(self._expiry)):
            self._expired(key)

    def _execute(self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        self._check_failure()
        method = getattr(self, f"_cmd_{name}")
        return method(*args, **kwargs)

    # ---------- 命令实现 ----------
    def _cmd_get(self, key: str) -> str | None:
        if self._expired(key):
            return None
        return self._strings.get(key)

    def _cmd_set(self, key: str, value: Any, ex: int | None = None, **_ignored: Any) -> bool:
        self._strings[key] = str(value)
        self._sets.pop(key, None)
        if ex is not None:
            self._expiry[key] = time.monotonic() + int(ex)
        else:
            self._expiry.pop(key, None)
        return True

    def _cmd_delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            for store in (self._strings, self._sets):
                if key in store:
                    store.pop(key, None)
                    removed += 1
                    break
            self._expiry.pop(key, None)
        return removed

    def _cmd_exists(self, key: str) -> int:
        if self._expired(key):
            return 0
        return int(key in self._strings or key in self._sets)

    def _cmd_incr(self, key: str) -> int:
        self._expired(key)
        current = int(self._strings.get(key, "0"))
        current += 1
        self._strings[key] = str(current)
        return current

    def _cmd_incrbyfloat(self, key: str, amount: float) -> str:
        self._expired(key)
        current = float(self._strings.get(key, "0"))
        current += float(amount)
        self._strings[key] = repr(current)
        return repr(current)

    def _cmd_sadd(self, key: str, *members: str) -> int:
        self._expired(key)
        target = self._sets.setdefault(key, set())
        before = len(target)
        target.update(str(m) for m in members)
        return len(target) - before

    def _cmd_srem(self, key: str, *members: str) -> int:
        if self._expired(key):
            return 0
        target = self._sets.get(key)
        if target is None:
            return 0
        removed = 0
        for member in members:
            if str(member) in target:
                target.discard(str(member))
                removed += 1
        return removed

    def _cmd_smembers(self, key: str) -> set[str]:
        if self._expired(key):
            return set()
        return set(self._sets.get(key, set()))

    def _cmd_expire(self, key: str, seconds: int) -> bool:
        if self._expired(key):
            return False
        if key not in self._strings and key not in self._sets:
            return False
        self._expiry[key] = time.monotonic() + int(seconds)
        return True

    def _cmd_getdel(self, key: str) -> str | None:
        value = self._cmd_get(key)
        self._cmd_delete(key)
        return value

    def _cmd_ping(self) -> bool:
        return True

    # ---------- 公开异步接口 ----------
    async def get(self, key: str) -> str | None:
        async with self._lock:
            return self._execute("get", (key,), {})

    async def set(self, key: str, value: Any, **kwargs: Any) -> bool:
        async with self._lock:
            return self._execute("set", (key, value), kwargs)

    async def delete(self, *keys: str) -> int:
        async with self._lock:
            return self._execute("delete", keys, {})

    async def incr(self, key: str) -> int:
        async with self._lock:
            return self._execute("incr", (key,), {})

    async def smembers(self, key: str) -> set[str]:
        async with self._lock:
            return self._execute("smembers", (key,), {})

    async def ping(self) -> bool:
        async with self._lock:
            return self._execute("ping", (), {})

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        return _FakePipeline(self, transaction)
