"""
通知去重（幂等）

为什么必须去重：`space_idle` 每轮扫描都会对所有闲置场地命中 ——
没有去重就是每 5 分钟给全体管理员刷一遍同样的消息，演示现场会很难看。

为什么不给 notify_message 加唯一索引：该表结构由开发流程.md 6.3 锁定，
本模块全程零 DDL 变更，指纹状态因而放在 Redis（内存版仅供测试与无 Redis 环境），
数据库只作只读判重。

降级要求：Redis 不可用时必须自动切到数据库判重，而不是向上抛异常 ——
本地开发常常没起 Redis，定时任务不能因此崩掉。
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.notification import NotifyMessage

logger = logging.getLogger(__name__)

# 去重后端取值
BACKEND_AUTO = "auto"
BACKEND_REDIS = "redis"
BACKEND_DB = "db"
BACKEND_MEMORY = "memory"


@dataclass(frozen=True, slots=True)
class DedupKey:
    """
    一条通知的去重键。

    template_title 是**模板**渲染出的标题（计算成本为零、同一冲突恒定），
    不是 AI 生成的标题 —— 因为数据库兜底判重只能按标题近似匹配
    （notify_message 没有规则列，且不能加列），而 AI 标题每次都可能不同。
    """

    receiver_id: int
    notify_type: int
    rule_code: str
    template_title: str
    order_ids: tuple[int, ...] = ()
    space_id: int | None = None
    source: str = "scan"

    def fingerprint(self) -> str:
        """
        指纹 = sha1(source|rule_code|notify_type|order_ids|space_id|receiver_id)

        比方案初稿多加了两项：notify_type（同一冲突可能按不同语气各推一次）
        与 source（人工触发的生成不应被定时扫描的指纹遮蔽）。
        """
        raw = "|".join(
            (
                self.source,
                self.rule_code,
                str(self.notify_type),
                ",".join(str(i) for i in self.order_ids),
                str(self.space_id) if self.space_id is not None else "",
                str(self.receiver_id),
            )
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class Dedup(Protocol):
    """去重后端接口"""

    name: str

    async def claim(self, key: DedupKey) -> bool:
        """
        尝试占用该通知名额。

        返回 True 表示「首次，可以推送」；False 表示 TTL 内已推过，应跳过。
        实现必须是原子的：定时扫描与事件总线可能并发触发。
        """
        ...

    async def release(self, key: DedupKey) -> None:
        """写库失败时归还名额，避免一次瞬时故障让该通知被压 24 小时"""
        ...

    async def aclose(self) -> None:
        """释放后端资源（Redis 连接等）"""
        ...


class MemoryDedup:
    """
    进程内去重，供单元测试与无 Redis 环境使用。

    注意：多 worker 部署时会各留一份状态，因此仅作降级兜底，
    生产默认走 Redis（Uvicorn 默认单 worker，与开发流程.md 12.1 一致）。
    """

    name = BACKEND_MEMORY

    def __init__(self, ttl_seconds: int | None = None) -> None:
        # 注意不能用 `ttl_seconds or 默认值`：0 是合法 TTL（表示立即过期），
        # 而 `0 or x` 会把它悄悄换成一整天
        self._ttl = (
            ttl_seconds
            if ttl_seconds is not None
            else settings.CONFLICT_DEDUP_TTL_SECONDS
        )
        self._seen: dict[str, float] = {}

    def _purge_if_needed(self, now: float) -> None:
        # 键数量有界（每个冲突 × 每个收件人），顺手清理即可，无需后台任务
        if len(self._seen) < 512:
            return
        self._seen = {k: v for k, v in self._seen.items() if v > now}

    async def claim(self, key: DedupKey) -> bool:
        now = time.monotonic()
        self._purge_if_needed(now)
        fingerprint = key.fingerprint()
        expiry = self._seen.get(fingerprint)
        if expiry is not None and expiry > now:
            return False
        self._seen[fingerprint] = now + self._ttl
        return True

    async def release(self, key: DedupKey) -> None:
        self._seen.pop(key.fingerprint(), None)

    async def aclose(self) -> None:
        self._seen.clear()


class RedisDedup:
    """
    Redis SET NX EX 原子占位。

    连接失败时置位不可用并降级，而不是每个键都去重试一次 ——
    否则 Redis 挂掉时每轮扫描都要为每个收件人白等一次连接超时。
    """

    name = BACKEND_REDIS

    def __init__(self, client, ttl_seconds: int | None = None) -> None:
        self._client = client
        self._ttl = (
            ttl_seconds
            if ttl_seconds is not None
            else settings.CONFLICT_DEDUP_TTL_SECONDS
        )
        self._available = True
        self._prefix = "conflict:notify:"

    @property
    def available(self) -> bool:
        return self._available

    def _mark_unavailable(self, exc: Exception) -> None:
        if self._available:
            logger.warning("Redis 去重不可用，本次扫描降级为数据库判重：%s", exc)
        self._available = False

    async def claim(self, key: DedupKey) -> bool:
        if not self._available:
            raise ConnectionError("Redis 去重后端已标记为不可用")
        try:
            result = await self._client.set(
                self._prefix + key.fingerprint(), "1", nx=True, ex=self._ttl
            )
        except Exception as exc:  # noqa: BLE001 —— 网络层异常形态多样，一律降级
            self._mark_unavailable(exc)
            raise
        # SET NX 成功返回 True，键已存在返回 None
        return bool(result)

    async def release(self, key: DedupKey) -> None:
        if not self._available:
            return
        try:
            await self._client.delete(self._prefix + key.fingerprint())
        except Exception as exc:  # noqa: BLE001
            self._mark_unavailable(exc)

    async def aclose(self) -> None:
        close = getattr(self._client, "aclose", None) or getattr(
            self._client, "close", None
        )
        if close is not None:
            try:
                await close()
            except Exception:  # noqa: BLE001
                logger.debug("关闭 Redis 连接失败，忽略", exc_info=True)


class DbDedup:
    """
    数据库判重兜底。

    表内没有指纹列也不能加列，因此按 (接收人, 模板标题, TTL 内) 近似判重：
    模板标题里含规则名与场地/设备名，足以区分同一个收件人的不同冲突。
    """

    name = BACKEND_DB

    def __init__(self, session: AsyncSession, ttl_seconds: int | None = None) -> None:
        self._session = session
        self._ttl = (
            ttl_seconds
            if ttl_seconds is not None
            else settings.CONFLICT_DEDUP_TTL_SECONDS
        )

    async def claim(self, key: DedupKey) -> bool:
        cutoff = datetime.now() - timedelta(seconds=self._ttl)
        stmt = (
            select(NotifyMessage.id)
            .where(
                NotifyMessage.receiver_id == key.receiver_id,
                NotifyMessage.title == key.template_title,
                NotifyMessage.create_time >= cutoff,
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.first() is None

    async def release(self, key: DedupKey) -> None:
        """数据库后端无需归还：判重依据是真实写入的行，未写入自然不存在"""
        return None

    async def aclose(self) -> None:
        return None


class AutoDedup:
    """
    优先 Redis，不可用时自动落到兜底后端。

    状态粘滞：一旦 Redis 判定不可用，本轮后续所有键直接走兜底，
    不再逐个键去撞连接超时。
    """

    name = BACKEND_AUTO

    def __init__(self, primary: Dedup, fallback: Dedup) -> None:
        self._primary = primary
        self._fallback = fallback

    async def claim(self, key: DedupKey) -> bool:
        try:
            return await self._primary.claim(key)
        except Exception:  # noqa: BLE001 —— 去重后端故障不得中断通知链路
            return await self._fallback.claim(key)

    async def release(self, key: DedupKey) -> None:
        try:
            await self._primary.release(key)
        except Exception:  # noqa: BLE001
            pass
        await self._fallback.release(key)

    async def aclose(self) -> None:
        for backend in (self._primary, self._fallback):
            try:
                await backend.aclose()
            except Exception:  # noqa: BLE001
                logger.debug("关闭去重后端失败，忽略", exc_info=True)


def build_redis_client():
    """延迟创建 Redis 客户端，避免导入期就连网（测试与无 Redis 环境友好）"""
    from redis.asyncio import Redis

    return Redis.from_url(settings.redis_url, decode_responses=True)


def build_dedup(session: AsyncSession | None = None) -> Dedup:
    """
    按配置构造去重后端。

    :param session: 数据库会话。scan 任务在写库段调用本函数并传入会话，
        这样数据库兜底可用；不传时兜底退化为进程内去重。
    """
    backend = (settings.CONFLICT_DEDUP_BACKEND or BACKEND_AUTO).strip().lower()
    fallback: Dedup = DbDedup(session) if session is not None else MemoryDedup()

    if backend == BACKEND_MEMORY:
        return MemoryDedup()
    if backend == BACKEND_DB:
        return fallback
    if backend == BACKEND_REDIS:
        return RedisDedup(build_redis_client())
    return AutoDedup(RedisDedup(build_redis_client()), fallback)
