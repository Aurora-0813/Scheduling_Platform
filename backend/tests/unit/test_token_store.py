"""
TokenStore 白名单/轮换/宽限期/强制下线测试

同一组用例**同时跑两套实现**（内存实现与跑在 FakeRedis 上的 Redis 实现），
保证二者语义不分叉。这是本文件最重要的设计：`RedisTokenStore` 是生产实现，
但真实 Redis 在当前环境不可达，用 FakeRedis 让它真正被执行到。
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.exceptions import RedisUnavailableError
from app.core.token_store import (
    InMemoryTokenStore,
    RedisTokenStore,
    RotationOutcome,
    TokenStore,
    build_token_store,
)
from tests.fakes.fake_redis import FakeRedis

pytestmark = pytest.mark.unit

USER_ID = 1001
OTHER_USER_ID = 1002
TTL = 600.0

# 宽限期最小只能取 1 秒：Redis 的过期粒度是整秒，token_store._ttl() 会把
# 不足 1 秒的值钳到 1，所以测试不能假设亚秒级过期（配置里是 60 秒，
# 这里取最小值把等待时间压到最短）。
GRACE = 1.0


@pytest.fixture(params=["memory", "redis"])
def store(request: pytest.FixtureRequest) -> TokenStore:
    """两套实现各跑一遍同样的用例。"""
    if request.param == "memory":
        return InMemoryTokenStore()
    return RedisTokenStore(FakeRedis())


async def _register(
    store: TokenStore, jti: str, *, user_id: int = USER_ID, version: int = 0
) -> None:
    await store.register_refresh(user_id, jti, role="admin", ttl_seconds=TTL, version=version)


async def _rotate(
    store: TokenStore,
    old_jti: str,
    new_jti: str,
    *,
    user_id: int = USER_ID,
    version: int = 0,
    grace: float = GRACE,
):
    return await store.rotate_refresh(
        user_id,
        old_jti,
        new_jti,
        role="admin",
        ttl_seconds=TTL,
        version=version,
        grace_seconds=grace,
    )


# ==========================================================================
# 轮换与宽限期
# ==========================================================================
async def test_whitelisted_jti_can_rotate(store: TokenStore) -> None:
    await _register(store, "j1")
    result = await _rotate(store, "j1", "j2")
    assert result.ok is True
    assert result.outcome is RotationOutcome.ROTATED
    assert result.in_whitelist is True


async def test_unknown_jti_is_rejected(store: TokenStore) -> None:
    """从未签发过的 jti 必须被拒 —— 伪造/篡改 token 的主防线。"""
    result = await _rotate(store, "never-issued", "j2")
    assert result.ok is False
    assert result.outcome is RotationOutcome.REJECTED


async def test_grace_allows_exactly_one_replay(store: TokenStore) -> None:
    """宽限期解决前端并发刷新误伤，但只放行一次，不可无限重放。"""
    await _register(store, "j1")
    await _rotate(store, "j1", "j2")

    replay = await _rotate(store, "j1", "j3")
    assert replay.ok is True
    assert replay.outcome is RotationOutcome.GRACE_REPLAY
    assert replay.grace_hit is True

    second_replay = await _rotate(store, "j1", "j4")
    assert second_replay.ok is False
    assert second_replay.outcome is RotationOutcome.REJECTED


async def test_grace_expires(store: TokenStore) -> None:
    """宽限标记过期后不得再放行 —— 否则宽限期就成了永久后门。"""
    await _register(store, "g1")
    await _rotate(store, "g1", "g2")
    await asyncio.sleep(GRACE + 0.1)
    result = await _rotate(store, "g1", "g3")
    assert result.ok is False
    assert result.outcome is RotationOutcome.REJECTED


async def test_rotated_token_is_still_usable(store: TokenStore) -> None:
    """轮换出来的新 token 本身不受宽限期约束，一直可用到自身过期。"""
    await _register(store, "j1")
    await _rotate(store, "j1", "j2")
    result = await _rotate(store, "j2", "j3")
    assert result.ok is True
    assert result.outcome is RotationOutcome.ROTATED


async def test_concurrent_rotation_only_one_wins(store: TokenStore) -> None:
    """
    并发刷新同一个 refreshToken 只能成功一次。

    这条用例守住的是 `rotate_refresh` 的原子性：检查与消费之间若存在
    竞态，重放防线就形同虚设。Redis 实现靠 MULTI/EXEC 内的 GET+DEL，
    内存实现靠「检查与写入之间没有 await」。
    """
    await _register(store, "c1")
    results = await asyncio.gather(
        *[_rotate(store, "c1", f"c-new-{index}", grace=0.0) for index in range(5)]
    )
    success_count = sum(1 for item in results if item.ok)
    assert success_count == 1, [item.outcome.value for item in results]


# ==========================================================================
# 登出与强制下线
# ==========================================================================
async def test_revoke_makes_token_immediately_invalid(store: TokenStore) -> None:
    await _register(store, "j1")
    await store.revoke_refresh(USER_ID, "j1")
    result = await _rotate(store, "j1", "j2")
    assert result.ok is False


async def test_revoke_clears_grace_marker(store: TokenStore) -> None:
    """登出要把宽限标记一起删掉，否则登出后 60 秒内旧 token 仍能换新。"""
    await _register(store, "j1")
    await _rotate(store, "j1", "j2")  # j1 由此获得宽限标记
    await store.revoke_refresh(USER_ID, "j1")
    result = await _rotate(store, "j1", "j3")
    assert result.ok is False


async def test_revoke_all_bumps_version(store: TokenStore) -> None:
    """强制下线：版本号递增，且所有会话失效。"""
    assert await store.get_version(USER_ID) == 0

    await _register(store, "k1")
    await _register(store, "k2")
    version = await store.revoke_all(USER_ID)

    assert version == 1
    assert await store.get_version(USER_ID) == 1

    for jti in ("k1", "k2"):
        result = await _rotate(store, jti, "k9", version=1)
        assert result.ok is False, jti


async def test_revoke_all_only_affects_target_user(store: TokenStore) -> None:
    await _register(store, "mine", user_id=USER_ID)
    await _register(store, "theirs", user_id=OTHER_USER_ID)
    await store.revoke_all(USER_ID)
    assert await store.get_version(OTHER_USER_ID) == 0
    result = await _rotate(store, "theirs", "theirs2", user_id=OTHER_USER_ID)
    assert result.ok is True


async def test_version_is_monotonic(store: TokenStore) -> None:
    """版本号只增不减，否则旧 token 会在版本回落后重新生效。"""
    assert await store.revoke_all(USER_ID) == 1
    assert await store.revoke_all(USER_ID) == 2
    assert await store.get_version(USER_ID) == 2


# ==========================================================================
# 登录失败计数（风控）
# ==========================================================================
async def test_login_failure_counter(store: TokenStore) -> None:
    assert await store.get_login_failure("admin") == 0
    assert await store.record_login_failure("admin", 900) == 1
    assert await store.record_login_failure("admin", 900) == 2
    assert await store.record_login_failure("admin", 900) == 3
    assert await store.get_login_failure("admin") == 3


async def test_login_failure_counter_is_case_insensitive(store: TokenStore) -> None:
    """Admin / admin / ADMIN 必须收敛到同一个计数，否则可以绕过锁定。"""
    await store.record_login_failure("Admin", 900)
    assert await store.get_login_failure("admin") == 1
    assert await store.get_login_failure(" ADMIN ") == 1


async def test_login_failure_counter_isolated_per_user(store: TokenStore) -> None:
    await store.record_login_failure("alice", 900)
    await store.record_login_failure("alice", 900)
    await store.record_login_failure("bob", 900)
    assert await store.get_login_failure("alice") == 2
    assert await store.get_login_failure("bob") == 1


async def test_clear_login_failure(store: TokenStore) -> None:
    await store.record_login_failure("admin", 900)
    await store.clear_login_failure("admin")
    assert await store.get_login_failure("admin") == 0


# ==========================================================================
# Redis 实现特有：不可用时的抛错与降级边界
# ==========================================================================
def _failing_store() -> tuple[RedisTokenStore, FakeRedis]:
    fake = FakeRedis()
    return RedisTokenStore(fake), fake


async def test_redis_failure_raises_unavailable_on_read() -> None:
    store, fake = _failing_store()
    fake.fail_next(1)
    with pytest.raises(RedisUnavailableError):
        await store.get_version(USER_ID)


async def test_redis_failure_raises_unavailable_on_register() -> None:
    store, fake = _failing_store()
    fake.fail_next(1)
    with pytest.raises(RedisUnavailableError):
        await store.register_refresh(USER_ID, "j1", role="user", ttl_seconds=TTL, version=0)


async def test_redis_failure_raises_unavailable_on_rotate() -> None:
    store, fake = _failing_store()
    fake.fail_next(1)
    with pytest.raises(RedisUnavailableError):
        await _rotate(store, "j1", "j2")


async def test_redis_failure_raises_unavailable_on_revoke() -> None:
    store, fake = _failing_store()
    fake.fail_next(1)
    with pytest.raises(RedisUnavailableError):
        await store.revoke_refresh(USER_ID, "j1")


async def test_revoke_all_survives_cleanup_failure() -> None:
    """
    强制下线时，只要版本号递增成功就算成功。

    会话键清理是「尽力而为」：清理失败若向上抛错，管理员会看到「操作失败」
    但用户其实已被踢下线，反而误导；而版本号已递增，下线效果是确定的。
    """
    store, fake = _failing_store()
    await _register(store, "m1")
    assert await store.revoke_all(USER_ID) == 1

    await _register(store, "m2", version=1)

    async def _boom(key: str) -> set[str]:
        raise __import__("redis").exceptions.ConnectionError("注入：清理阶段失败")

    original = fake.smembers
    fake.smembers = _boom  # type: ignore[method-assign]
    try:
        version = await store.revoke_all(USER_ID)
    finally:
        fake.smembers = original  # type: ignore[method-assign]

    assert version == 2
    assert await store.get_version(USER_ID) == 2


async def test_in_memory_store_never_raises() -> None:
    """内存实现是降级路径，任何情况下都不应抛 RedisUnavailableError。"""
    store = InMemoryTokenStore()
    assert await store.ping() is True
    await store.register_refresh(USER_ID, "j1", role=None, ttl_seconds=TTL, version=0)
    assert (await _rotate(store, "j1", "j2")).ok is True


# ==========================================================================
# 工厂
# ==========================================================================
def test_build_token_store_respects_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import redis as redis_module

    monkeypatch.setattr(redis_module, "get_client", lambda: None)
    assert isinstance(build_token_store(), InMemoryTokenStore)

    monkeypatch.setattr(redis_module, "get_client", lambda: FakeRedis())
    assert isinstance(build_token_store(), RedisTokenStore)
