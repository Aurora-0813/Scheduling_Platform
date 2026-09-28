"""
refreshToken 白名单存储（Redis 实现 + 进程内内存实现）

为什么 refreshToken 要落白名单
------------------------------
JWT 是无状态的，签出去就没法收回。accessToken 只有 30 分钟，代价可以接受；
但 refreshToken 有 7 天，若不落白名单，「登出」就只是前端删掉本地存储 ——
token 本身仍然能换出新的 accessToken，等于登出无效。

因此本模块维护 refreshToken 的白名单：**不在白名单里的 refreshToken 一律拒绝**。
accessToken 仍然保持纯粹的无状态校验（只验签名与过期），不查 Redis ——
这样 Redis 挂掉时，已登录用户手里的 accessToken 仍能正常访问业务接口，
只有「续期」与「登出」会明确失败。这是决策 7 的降级取舍，写在
docs/开发流程说明文档.md 的「Redis 不可用时的降级策略」一节。

Redis 键设计
------------
| 键                            | 类型 | 含义                                    | TTL        |
| ----------------------------- | ---- | --------------------------------------- | ---------- |
| `auth:rt:{userId}:{jti}`      | str  | refreshToken 白名单条目                 | 7 天       |
| `auth:urt:{userId}`           | set  | 该用户全部有效 jti，用于强制下线时清理  | 7 天       |
| `auth:ver:{userId}`           | int  | 令牌版本号，强制下线时 INCR             | 无         |
| `auth:grace:{userId}:{jti}`   | str  | 轮换宽限标记，消费即失效                | 60 秒      |
| `auth:fail:{username}`        | int  | 连续登录失败次数（风控）                | 15 分钟    |

`auth:ver` **刻意不设 TTL**：版本号一旦递增就必须永久有效。若它提前过期，
`get_version()` 会回落成 0，而那些带着 ver=1 的有效 refreshToken 会被
误判为「版本不符」—— 表现为用户被莫名登出。代价是每个被强制下线过的用户
留下一个整数键，数量有界（≤ 用户数），可以接受。

轮换的原子性
------------
轮换分两个 MULTI/EXEC 事务：

1. **消费阶段**：`GET` + `DEL` 旧白名单条目，`GET` + `DEL` 宽限标记。
   关键是在同一个事务里把旧条目**删掉** —— 并发的第二个刷新请求随后读到
   `nil`，被判定为「不在白名单」，于是同一个 refreshToken 只有一次能真正
   轮换成功。若只 GET 不 DEL，两个并发刷新会各自换出一个新 token，
   白名单里同时存在两个新 jti，旧 jti 却已丢失。
2. **写入阶段**：写新条目、更新集合成员、给旧 jti 打 60 秒宽限标记。

宽限期为什么存在
----------------
前端在 accessToken 过期时会并发发出多个 401 请求，每个都想刷新。若没有
宽限期，第一个刷新成功后其余请求拿旧 token 再刷就会全部失败，用户被莫名
踢下线。

宽限标记**只在真正轮换时补发，且消费即失效**，所以一个旧 jti 的生命周期是：

    第 1 次：命中白名单 → 轮换成功，补发宽限标记
    第 2 次：命中宽限标记 → 放行一次，标记被消费且**不再补发**
    第 3 次起：一律拒绝

即「最多额外放行一次」，而不是「60 秒内随便放行」。若在放行时重新武装标记，
旧 jti 就能无限重放 —— 白名单形同虚设，被窃取的 refreshToken 可以永久续命。
这条边界由 `test_grace_allows_exactly_one_replay` 守住。

真正的根治办法是前端用**单例 Promise 去重刷新**（同一时刻只发一个刷新请求），
宽限期只是兜底。已写入 docs/api.md 要求前端实现。

为什么不实现「检测到重放就吊销整个 token 家族」
----------------------------------------------
那需要区分「token 被窃取后重放」与「用户自己登出后旧 token 又被用了一次」。
两者在只有白名单的情况下形态完全相同：都不在白名单、都没有宽限标记。
若一律吊销家族，用户在设备 A 登出后，任何一次来自设备 A 的旧 token 重放
都会把设备 B 也踢下线 —— 副作用大于收益。当前做法是**拒绝并记 WARN 日志**
（含 userId 与 jti），保留事后审计能力。这个取舍写在开发流程说明文档里。
"""

from __future__ import annotations

import functools
import json
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeVar

from app.core.exceptions import RedisUnavailableError
from app.core.logging import get_logger
from app.core.redis import REDIS_ERRORS

__all__ = [
    "RotationOutcome",
    "RotationResult",
    "TokenStore",
    "RedisTokenStore",
    "InMemoryTokenStore",
    "build_token_store",
]

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# ==========================================================================
# 键构造
# ==========================================================================
def _rt_key(user_id: int, jti: str) -> str:
    return f"auth:rt:{user_id}:{jti}"


def _urt_key(user_id: int) -> str:
    return f"auth:urt:{user_id}"


def _ver_key(user_id: int) -> str:
    return f"auth:ver:{user_id}"


def _grace_key(user_id: int, jti: str) -> str:
    return f"auth:grace:{user_id}:{jti}"


def _normalize_username(username: str) -> str:
    """用户名归一化：计数键必须大小写不敏感，否则 Admin / admin 各记一份。"""
    return (username or "").strip().lower()


def _fail_key(username: str) -> str:
    return f"auth:fail:{_normalize_username(username)}"


def _encode_entry(role: str | None, version: int) -> str:
    """白名单条目的值。存 role 与 ver 只为排查问题时自解释，不参与鉴权判定。"""
    return json.dumps({"role": role, "ver": version}, ensure_ascii=False)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _ttl(value: float | int) -> int:
    """
    把秒数规范化成 Redis 可接受的整数 TTL。

    Redis 的过期粒度是整秒，且 `EX 0` 会立即删除键，因此下限钳到 1 秒。
    注意：不足 1 秒的宽限期会被放大到 1 秒（配置项是 60，不受影响）。
    """
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = 1
    return max(1, seconds)


def _translate_errors(func: F) -> F:
    """
    把 Redis 连接层异常转成 `RedisUnavailableError`。

    只有这一种异常会向上传播；调用方据此决定降级行为
    （登录忽略、续期/登出失败）。
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except RedisUnavailableError:
            raise
        except REDIS_ERRORS as exc:
            raise RedisUnavailableError(f"Redis 不可用（{type(exc).__name__}）") from exc

    return wrapper  # type: ignore[return-value]


# ==========================================================================
# 结果类型
# ==========================================================================
class RotationOutcome(StrEnum):
    """轮换结果。

    用 `StrEnum` 而非 `(str, Enum)`，理由见 app/core/security.py 的 TokenType。
    """

    ROTATED = "rotated"
    """正常轮换：旧 token 在白名单里，已换成新 token。"""

    GRACE_REPLAY = "grace_replay"
    """旧 token 已被轮换过，但落在 60 秒宽限期内，本次消费掉宽限标记后放行。"""

    REJECTED = "rejected"
    """拒绝：既不在白名单，也没有宽限标记（已登出 / 已过期清理 / 被强制下线 / 重放）。"""


@dataclass(frozen=True)
class RotationResult:
    """轮换判定结果。"""

    outcome: RotationOutcome
    in_whitelist: bool = False
    grace_hit: bool = False

    @property
    def ok(self) -> bool:
        return self.outcome is not RotationOutcome.REJECTED


# ==========================================================================
# 抽象接口
# ==========================================================================
class TokenStore(ABC):
    """
    refreshToken 白名单存储接口。

    两套实现（Redis / 内存）必须保持语义一致：
    - 所有方法在 Redis 不可用时抛 `RedisUnavailableError`
    - `rotate_refresh` 的「检查 + 消费」必须原子，保证同一 jti 只成功轮换一次
    """

    @abstractmethod
    async def ping(self) -> bool:
        """探活。"""

    @abstractmethod
    async def get_version(self, user_id: int) -> int:
        """读取用户的令牌版本号。从未被强制下线过时返回 0。"""

    @abstractmethod
    async def register_refresh(
        self,
        user_id: int,
        jti: str,
        *,
        role: str | None,
        ttl_seconds: float,
        version: int,
    ) -> None:
        """登记一个 refreshToken 到白名单。"""

    @abstractmethod
    async def rotate_refresh(
        self,
        user_id: int,
        old_jti: str,
        new_jti: str,
        *,
        role: str | None,
        ttl_seconds: float,
        version: int,
        grace_seconds: float,
    ) -> RotationResult:
        """轮换 refreshToken：原子地消费旧 jti 并登记新 jti。"""

    @abstractmethod
    async def revoke_refresh(self, user_id: int, jti: str) -> None:
        """吊销单个 refreshToken（登出）。"""

    @abstractmethod
    async def revoke_all(self, user_id: int) -> int:
        """强制下线该用户的全部会话，返回递增后的版本号。"""

    @abstractmethod
    async def record_login_failure(self, username: str, ttl_seconds: float) -> int:
        """记一次登录失败，返回当前连续失败次数。"""

    @abstractmethod
    async def get_login_failure(self, username: str) -> int:
        """读取连续登录失败次数。"""

    @abstractmethod
    async def clear_login_failure(self, username: str) -> None:
        """登录成功后清零失败计数。"""

    async def close(self) -> None:  # pragma: no cover - 默认无资源可释放
        """释放资源。Redis 客户端由 app.core.redis 统一管理，这里通常是空操作。"""
        return None


# ==========================================================================
# Redis 实现
# ==========================================================================
class RedisTokenStore(TokenStore):
    """基于 Redis 的白名单存储。生产环境使用。"""

    def __init__(self, client: Any) -> None:
        self._client = client

    @_translate_errors
    async def ping(self) -> bool:
        try:
            await self._client.ping()
            return True
        except REDIS_ERRORS:
            return False

    @_translate_errors
    async def get_version(self, user_id: int) -> int:
        raw = await self._client.get(_ver_key(user_id))
        return _to_int(raw, 0)

    @_translate_errors
    async def register_refresh(
        self,
        user_id: int,
        jti: str,
        *,
        role: str | None,
        ttl_seconds: float,
        version: int,
    ) -> None:
        ttl = _ttl(ttl_seconds)
        pipe = self._client.pipeline(transaction=True)
        pipe.set(_rt_key(user_id, jti), _encode_entry(role, version), ex=ttl)
        pipe.sadd(_urt_key(user_id), jti)
        # 集合 TTL 每次登录都续期，保证它不会比里面最年轻的成员先过期
        pipe.expire(_urt_key(user_id), ttl)
        await pipe.execute()

    @_translate_errors
    async def rotate_refresh(
        self,
        user_id: int,
        old_jti: str,
        new_jti: str,
        *,
        role: str | None,
        ttl_seconds: float,
        version: int,
        grace_seconds: float,
    ) -> RotationResult:
        old_key = _rt_key(user_id, old_jti)
        grace_key = _grace_key(user_id, old_jti)

        # ---- 阶段一：原子消费 -------------------------------------------
        # GET + DEL 放在同一个 MULTI/EXEC 里，二者之间不会插入其他客户端的命令，
        # 因此「读到值」与「删掉值」是原子的，等效于 Redis 6.2 的 GETDEL，
        # 但兼容更老的 Redis 版本。
        consume = self._client.pipeline(transaction=True)
        consume.get(old_key)
        consume.delete(old_key)
        consume.get(grace_key)
        consume.delete(grace_key)
        entry, _, grace, _ = await consume.execute()

        in_whitelist = entry is not None
        grace_hit = grace is not None
        if not in_whitelist and not grace_hit:
            return RotationResult(RotationOutcome.REJECTED)

        # ---- 阶段二：原子写入 -------------------------------------------
        ttl = _ttl(ttl_seconds)
        write = self._client.pipeline(transaction=True)
        write.set(_rt_key(user_id, new_jti), _encode_entry(role, version), ex=ttl)
        write.srem(_urt_key(user_id), old_jti)
        write.sadd(_urt_key(user_id), new_jti)
        write.expire(_urt_key(user_id), ttl)
        # 只在「真正轮换」（旧 jti 原本在白名单里）时补发宽限标记。
        #
        # 若在宽限路径（in_whitelist=False）也补发，标记就会被一次次重新武装，
        # 旧 jti 变成可以无限重放 —— 白名单形同虚设，被窃取的 refreshToken
        # 可以永久续命。阶段一已经删掉了标记，这里不再补发即「消费即失效」。
        if grace_seconds > 0 and in_whitelist:
            write.set(grace_key, "1", ex=_ttl(grace_seconds))
        else:
            write.delete(grace_key)
        await write.execute()

        outcome = RotationOutcome.ROTATED if in_whitelist else RotationOutcome.GRACE_REPLAY
        return RotationResult(outcome, in_whitelist=in_whitelist, grace_hit=grace_hit)

    @_translate_errors
    async def revoke_refresh(self, user_id: int, jti: str) -> None:
        pipe = self._client.pipeline(transaction=True)
        pipe.delete(_rt_key(user_id, jti))
        # 连同宽限标记一起删：否则登出后 60 秒内旧 token 仍能换出新 token
        pipe.delete(_grace_key(user_id, jti))
        pipe.srem(_urt_key(user_id), jti)
        await pipe.execute()

    @_translate_errors
    async def revoke_all(self, user_id: int) -> int:
        # 第一步：递增版本号。这是强制下线的**充分操作** ——
        # 版本对不上的 refreshToken 全部失效，不依赖下面的清理是否成功。
        # 先做且单独 await，保证即使后续清理失败，下线也已经生效。
        version = _to_int(await self._client.incr(_ver_key(user_id)), 0)

        # 第二步：尽力清理会话键，避免 Redis 里堆孤儿键。
        # 清理失败不影响下线效果，因此只记日志、不抛异常 ——
        # 否则管理员会看到「操作失败」但用户其实已被踢下线，反而误导。
        set_key = _urt_key(user_id)
        try:
            members = await self._client.smembers(set_key) or set()
            pipe = self._client.pipeline(transaction=False)
            for jti in members:
                pipe.delete(_rt_key(user_id, jti))
            pipe.delete(set_key)
            await pipe.execute()
        except REDIS_ERRORS as exc:
            logger.warning(
                "强制下线：会话键清理失败（版本号已递增，下线仍生效）: %s: %s",
                type(exc).__name__,
                exc,
            )
        return version

    @_translate_errors
    async def record_login_failure(self, username: str, ttl_seconds: float) -> int:
        key = _fail_key(username)
        pipe = self._client.pipeline(transaction=True)
        pipe.incr(key)
        # 每次失败都续期，形成滑动窗口：持续尝试则计数窗口一直有效
        pipe.expire(key, _ttl(ttl_seconds))
        count, _ = await pipe.execute()
        return _to_int(count, 0)

    @_translate_errors
    async def get_login_failure(self, username: str) -> int:
        return _to_int(await self._client.get(_fail_key(username)), 0)

    @_translate_errors
    async def clear_login_failure(self, username: str) -> None:
        await self._client.delete(_fail_key(username))


# ==========================================================================
# 内存实现
# ==========================================================================
class InMemoryTokenStore(TokenStore):
    """
    进程内白名单存储。

    两个用途：
    1. `REDIS_ENABLED=false` 时作为生产降级实现（功能完整，但**进程重启后
       所有会话失效**，用户需重新登录）。
    2. 离线测试的默认实现。

    并发语义与 Redis 实现对齐：`rotate_refresh` 的「检查 + 消费」之间**没有
    await**，因此在单线程事件循环里天然原子，等价于 Redis 的 MULTI/EXEC。
    修改本文件时务必保持这一点 —— 一旦在检查与写入之间插入 await，
    并发刷新就会双双成功，与 Redis 实现行为分叉。
    """

    def __init__(self) -> None:
        # key -> (value, expires_at)；expires_at 为 None 表示永不过期
        self._values: dict[str, tuple[str, float | None]] = {}
        self._sets: dict[str, tuple[set[str], float | None]] = {}
        self._counters: dict[str, int] = {}
        self._counter_expiry: dict[str, float] = {}
        # 版本号字典刻意不设过期，与 Redis 实现的「auth:ver 无 TTL」保持一致
        self._versions: dict[int, int] = {}

    # ---------- 内部工具 ----------
    def _expired(self, expires_at: float | None) -> bool:
        return expires_at is not None and expires_at <= time.monotonic()

    def _get_value(self, key: str) -> str | None:
        item = self._values.get(key)
        if item is None:
            return None
        value, expires_at = item
        if self._expired(expires_at):
            self._values.pop(key, None)
            return None
        return value

    def _set_value(self, key: str, value: str, ttl_seconds: float | None) -> None:
        expires_at = None if ttl_seconds is None else time.monotonic() + float(ttl_seconds)
        self._values[key] = (value, expires_at)

    def _delete(self, *keys: str) -> None:
        for key in keys:
            self._values.pop(key, None)
            self._sets.pop(key, None)
            self._counters.pop(key, None)
            self._counter_expiry.pop(key, None)

    def _get_counter(self, key: str) -> int:
        expires_at = self._counter_expiry.get(key)
        if expires_at is not None and expires_at <= time.monotonic():
            self._counters.pop(key, None)
            self._counter_expiry.pop(key, None)
            return 0
        return self._counters.get(key, 0)

    def _set_members(self, key: str) -> set[str]:
        item = self._sets.get(key)
        if item is None:
            return set()
        members, expires_at = item
        if self._expired(expires_at):
            self._sets.pop(key, None)
            return set()
        return set(members)

    def _store_set(self, key: str, members: set[str], ttl_seconds: float | None) -> None:
        expires_at = None if ttl_seconds is None else time.monotonic() + float(ttl_seconds)
        self._sets[key] = (members, expires_at)

    # ---------- 接口实现 ----------
    async def ping(self) -> bool:
        return True

    async def get_version(self, user_id: int) -> int:
        return self._versions.get(user_id, 0)

    async def register_refresh(
        self,
        user_id: int,
        jti: str,
        *,
        role: str | None,
        ttl_seconds: float,
        version: int,
    ) -> None:
        ttl = _ttl(ttl_seconds)
        self._set_value(_rt_key(user_id, jti), _encode_entry(role, version), ttl)
        members = self._set_members(_urt_key(user_id))
        members.add(jti)
        self._store_set(_urt_key(user_id), members, ttl)

    async def rotate_refresh(
        self,
        user_id: int,
        old_jti: str,
        new_jti: str,
        *,
        role: str | None,
        ttl_seconds: float,
        version: int,
        grace_seconds: float,
    ) -> RotationResult:
        old_key = _rt_key(user_id, old_jti)
        grace_key = _grace_key(user_id, old_jti)

        # ↓↓↓ 检查与消费之间不得出现 await（见类文档）↓↓↓
        entry = self._get_value(old_key)
        grace = self._get_value(grace_key)
        self._delete(old_key, grace_key)

        in_whitelist = entry is not None
        grace_hit = grace is not None
        if not in_whitelist and not grace_hit:
            return RotationResult(RotationOutcome.REJECTED)

        ttl = _ttl(ttl_seconds)
        self._set_value(_rt_key(user_id, new_jti), _encode_entry(role, version), ttl)
        members = self._set_members(_urt_key(user_id))
        members.discard(old_jti)
        members.add(new_jti)
        self._store_set(_urt_key(user_id), members, ttl)

        # 与 Redis 实现保持一致：只在真正轮换时补发宽限标记，
        # 宽限路径不补发，保证「消费即失效、不可无限重放」。
        if grace_seconds > 0 and in_whitelist:
            self._set_value(grace_key, "1", _ttl(grace_seconds))
        # ↑↑↑ 不得出现 await ↑↑↑

        outcome = RotationOutcome.ROTATED if in_whitelist else RotationOutcome.GRACE_REPLAY
        return RotationResult(outcome, in_whitelist=in_whitelist, grace_hit=grace_hit)

    async def revoke_refresh(self, user_id: int, jti: str) -> None:
        self._delete(_rt_key(user_id, jti), _grace_key(user_id, jti))
        set_key = _urt_key(user_id)
        item = self._sets.get(set_key)
        if item is not None:
            members, expires_at = item
            members.discard(jti)
            # 原地更新，保留原有 TTL（对应 Redis 的 SREM 不改动键过期时间）
            self._sets[set_key] = (members, expires_at)

    async def revoke_all(self, user_id: int) -> int:
        version = self._versions.get(user_id, 0) + 1
        self._versions[user_id] = version
        for jti in self._set_members(_urt_key(user_id)):
            self._values.pop(_rt_key(user_id, jti), None)
        self._sets.pop(_urt_key(user_id), None)
        return version

    async def record_login_failure(self, username: str, ttl_seconds: float) -> int:
        key = _fail_key(username)
        self._counter_expiry[key] = time.monotonic() + float(_ttl(ttl_seconds))
        count = self._get_counter(key) + 1
        self._counters[key] = count
        return count

    async def get_login_failure(self, username: str) -> int:
        return self._get_counter(_fail_key(username))

    async def clear_login_failure(self, username: str) -> None:
        self._delete(_fail_key(username))


# ==========================================================================
# 工厂
# ==========================================================================
def build_token_store() -> TokenStore:
    """
    按配置构造 TokenStore。

    `REDIS_ENABLED=false` → 内存实现（功能完整，重启后需重新登录）。
    `REDIS_ENABLED=true` 但 Redis 连不上 → 仍返回 Redis 实现，
    由调用方按决策 7 决定降级行为（登录忽略、续期/登出失败）。
    不在这里做「连不上就自动换内存」——那会让「登出无效」这类安全问题
    静默发生，比明确报错危险得多。
    """
    from app.core.redis import get_client  # 延迟导入，避免测试替换客户端时被缓存

    client = get_client()
    if client is None:
        logger.info("REDIS_ENABLED=false，refreshToken 白名单使用进程内内存实现")
        return InMemoryTokenStore()
    return RedisTokenStore(client)
