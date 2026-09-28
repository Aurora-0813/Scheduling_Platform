"""
Redis 异步客户端

用途
----
1. refreshToken 白名单（登出即失效、轮换、强制下线）
2. 登录失败计数（模块 9 的可选风控）
3. Agent 调用埋点指标（模块 10 的 /monitor/agent）

设计要点
--------
- **短超时**（`REDIS_SOCKET_TIMEOUT`，默认 0.5s）：Redis 挂掉时业务接口必须在
  半秒内拿到失败结果，而不是卡住等 TCP 超时。这是文档 13「外部依赖失败时
  友好降级」的前提。
- **客户端惰性创建**：import 本模块不产生网络连接，测试可以自由替换。
- **`REDIS_ENABLED=false` 时不创建客户端**，上层自动退化为内存实现。
- 连接池 `max_connections=20`：uvicorn 单进程 + 少量并发足够；
  Redis 不可用时的连接失败也会被池快速拒绝。

错误处理策略由调用方决定，本模块只提供 `REDIS_ERRORS` 这一组
「可视为 Redis 不可用」的异常类型，以及 `check_health()` 探针。
"""

from __future__ import annotations

import asyncio
from typing import Any

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.logging import get_logger

__all__ = [
    "REDIS_ERRORS",
    "get_client",
    "is_enabled",
    "check_health",
    "close",
    "reset_client",
]

logger = get_logger(__name__)

# 「Redis 不可用」的异常类型。
#
# - RedisError：redis-py 自身抛出的连接/超时/协议错误
# - OSError：连接被拒绝时连接池直接抛出的系统级错误（ConnectionRefusedError 等）
# - asyncio.TimeoutError：部分路径下超时以原样抛出
#
# 注意 py3.11 起 asyncio.TimeoutError 即内置 TimeoutError（OSError 的子类），
# 这里显式列出是为了让 py3.10 及以下也正确覆盖。
REDIS_ERRORS: tuple[type[BaseException], ...] = (RedisError, OSError, asyncio.TimeoutError)

_client: Redis | None = None


def is_enabled() -> bool:
    """配置层面是否启用 Redis。"""
    return bool(settings.REDIS_ENABLED)


def get_client() -> Redis | None:
    """
    获取全局 Redis 客户端（惰性创建，幂等）。

    未启用 Redis 时返回 None，调用方应据此走内存实现。
    """
    global _client
    if not is_enabled():
        return None
    if _client is None:
        pool = ConnectionPool.from_url(
            settings.redis_url,
            max_connections=20,
            decode_responses=True,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout=settings.REDIS_SOCKET_TIMEOUT,
            # 不做失败重试：重试会把 0.5s 的超时放大成数秒，
            # 与「短超时快降级」的目标冲突
            retry_on_timeout=False,
        )
        _client = Redis(connection_pool=pool)
        logger.info(
            "Redis 客户端已创建: %s:%s db=%s timeout=%ss",
            settings.REDIS_HOST,
            settings.REDIS_PORT,
            settings.REDIS_DB,
            settings.REDIS_SOCKET_TIMEOUT,
        )
    return _client


async def check_health() -> str:
    """
    探活。返回 `"ok"` / `"degraded"` / `"disabled"`。

    供 `/api/v1/ready` 展示。这里**刻意吞掉所有异常**并转成状态字符串 ——
    探针接口本身不应该因为依赖挂了而抛 500，那样反而看不出究竟是哪一环有问题。
    """
    client = get_client()
    if client is None:
        return "disabled"
    try:
        await client.ping()
        return "ok"
    except Exception as exc:  # noqa: BLE001 - 探针刻意吞异常
        logger.warning("Redis 探活失败: %s: %s", type(exc).__name__, exc)
        return "degraded"


async def close() -> None:
    """关闭客户端与连接池。由 main.py 的 lifespan 在退出时调用。"""
    global _client
    if _client is None:
        return
    try:
        # redis>=5.0 提供 aclose；旧版本是 close
        aclose: Any = getattr(_client, "aclose", None) or getattr(_client, "close", None)
        if aclose is not None:
            await aclose()
    except Exception as exc:  # noqa: BLE001 - 退出路径不能抛异常
        logger.warning("关闭 Redis 客户端时出错: %s: %s", type(exc).__name__, exc)
    finally:
        _client = None


def reset_client() -> None:
    """丢弃当前客户端引用（不关闭连接）。仅供测试使用。"""
    global _client
    _client = None
