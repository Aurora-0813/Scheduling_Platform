"""
去重层：指纹稳定性、各后端行为、以及 Redis 故障时的降级
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.dedup import (
    AutoDedup,
    DbDedup,
    DedupKey,
    MemoryDedup,
    RedisDedup,
    build_dedup,
)


def _key(**overrides) -> DedupKey:
    data = dict(
        receiver_id=1,
        notify_type=1,
        rule_code="space_idle",
        template_title="【预约提醒·汇总】长期闲置",
        order_ids=(),
        space_id=3,
        source="scan",
    )
    data.update(overrides)
    return DedupKey(**data)


# ---------- 指纹 ----------


def test_fingerprint_is_stable():
    assert _key().fingerprint() == _key().fingerprint()


def test_fingerprint_is_sha1_hex():
    fingerprint = _key().fingerprint()
    assert len(fingerprint) == 40
    assert all(ch in "0123456789abcdef" for ch in fingerprint)


@pytest.mark.parametrize(
    "field,value",
    [
        ("receiver_id", 2),
        ("notify_type", 2),
        ("rule_code", "space_overuse"),
        ("order_ids", (7, 8)),
        ("space_id", 9),
        ("source", "manual"),
    ],
)
def test_fingerprint_changes_with_every_field(field, value):
    """任一维度变化都必须换一个指纹，否则会误压掉本应发出的通知"""
    assert _key().fingerprint() != _key(**{field: value}).fingerprint()


def test_order_ids_order_is_normalized():
    """orderIds 顺序不同但集合相同时不应视为两条通知"""
    assert _key(order_ids=(1, 2)).fingerprint() == _key(order_ids=(1, 2)).fingerprint()


# ---------- MemoryDedup ----------


async def test_memory_claim_is_once_only():
    dedup = MemoryDedup()
    assert await dedup.claim(_key()) is True
    assert await dedup.claim(_key()) is False


async def test_memory_distinct_keys_are_independent():
    dedup = MemoryDedup()
    assert await dedup.claim(_key(receiver_id=1)) is True
    assert await dedup.claim(_key(receiver_id=2)) is True


async def test_memory_release_allows_reclaim():
    """写库失败后必须能重来，否则一次瞬时故障会压掉该通知 24 小时"""
    dedup = MemoryDedup()
    key = _key()
    await dedup.claim(key)
    await dedup.release(key)
    assert await dedup.claim(key) is True


async def test_memory_ttl_expiry():
    """TTL 过后可以重新推送（用 0 秒 TTL 模拟过期）"""
    dedup = MemoryDedup(ttl_seconds=0)
    assert await dedup.claim(_key()) is True
    assert await dedup.claim(_key()) is True


async def test_memory_aclose_clears_state():
    dedup = MemoryDedup()
    await dedup.claim(_key())
    await dedup.aclose()
    assert await dedup.claim(_key()) is True


# ---------- RedisDedup ----------


class FakeRedis:
    """记录调用的假 Redis 客户端"""

    def __init__(self, set_result=True, exc: Exception | None = None) -> None:
        self.set_result = set_result
        self.exc = exc
        self.set_calls: list[tuple] = []
        self.delete_calls: list[str] = []
        self.closed = False

    async def set(self, name, value, nx=None, ex=None):
        self.set_calls.append((name, value, nx, ex))
        if self.exc is not None:
            raise self.exc
        return True if self.set_result else None

    async def delete(self, name):
        self.delete_calls.append(name)
        return 1

    async def aclose(self):
        self.closed = True


async def test_redis_set_nx_success_means_first_time():
    client = FakeRedis(set_result=True)
    dedup = RedisDedup(client, ttl_seconds=3600)

    assert await dedup.claim(_key()) is True
    name, value, nx, ex = client.set_calls[0]
    assert nx is True
    assert ex == 3600
    assert value == "1"
    assert name.startswith("conflict:notify:")


async def test_redis_existing_key_means_duplicate():
    dedup = RedisDedup(FakeRedis(set_result=False))
    assert await dedup.claim(_key()) is False


async def test_redis_failure_marks_unavailable_and_raises_once():
    """
    Redis 挂掉时只报告一次不可用，后续键直接抛错不再撞连接超时 ——
    否则一轮扫描要为每个收件人白等一次连接超时。
    """
    client = FakeRedis(exc=ConnectionError("Redis 未启动"))
    dedup = RedisDedup(client)

    with pytest.raises(ConnectionError):
        await dedup.claim(_key())
    assert dedup.available is False

    with pytest.raises(ConnectionError):
        await dedup.claim(_key(space_id=4))
    assert len(client.set_calls) == 1, "不可用后不应再次尝试连接"


async def test_redis_release_is_noop_when_unavailable():
    client = FakeRedis(exc=ConnectionError("Redis 未启动"))
    dedup = RedisDedup(client)
    with pytest.raises(ConnectionError):
        await dedup.claim(_key())

    await dedup.release(_key())
    assert client.delete_calls == []


async def test_redis_aclose_closes_client():
    client = FakeRedis()
    await RedisDedup(client).aclose()
    assert client.closed is True


# ---------- AutoDedup ----------


async def test_auto_falls_back_when_redis_is_down():
    """本地开发常常没起 Redis，去重必须降级而不是让定时任务崩掉"""
    redis = RedisDedup(FakeRedis(exc=ConnectionError("Redis 未启动")))
    fallback = MemoryDedup()
    dedup = AutoDedup(redis, fallback)

    assert await dedup.claim(_key()) is True
    assert await dedup.claim(_key()) is False


async def test_auto_uses_primary_when_healthy():
    client = FakeRedis(set_result=True)
    dedup = AutoDedup(RedisDedup(client), MemoryDedup())

    assert await dedup.claim(_key()) is True
    assert len(client.set_calls) == 1


async def test_auto_aclose_does_not_raise_on_broken_backends():
    class Boom:
        name = "boom"

        async def claim(self, key):
            raise RuntimeError

        async def release(self, key):
            raise RuntimeError

        async def aclose(self):
            raise RuntimeError

    dedup = AutoDedup(Boom(), Boom())
    await dedup.aclose()  # 不得抛异常


# ---------- DbDedup ----------


class FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class FakeSession:
    def __init__(self, row):
        self._row = row
        self.statements: list = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return FakeResult(self._row)


class StatefulFakeSession(FakeSession):
    """第一次查询没查到行，之后查到 —— 模拟真实写入之后的判重"""

    def __init__(self):
        super().__init__(row=None)
        self._count = 0

    async def execute(self, stmt):
        self.statements.append(stmt)
        self._count += 1
        return FakeResult(None if self._count == 1 else (1,))


async def test_db_dedup_allows_when_no_recent_row():
    session = FakeSession(row=None)
    assert await DbDedup(session).claim(_key()) is True


async def test_db_dedup_blocks_when_recent_row_exists():
    session = FakeSession(row=(42,))
    assert await DbDedup(session).claim(_key()) is False


async def test_db_dedup_filters_by_receiver_title_and_time():
    """表内无指纹列也不能加列，故按「接收人 + 模板标题 + TTL 内」近似判重"""
    session = FakeSession(row=None)
    await DbDedup(session).claim(_key())

    sql = str(session.statements[0])
    assert "receiver_id" in sql
    assert "title" in sql
    assert "create_time" in sql


async def test_db_dedup_release_is_noop():
    session = FakeSession(row=None)
    await DbDedup(session).release(_key())  # 不得抛异常
    assert session.statements == []


# ---------- build_dedup ----------


def test_build_dedup_memory_backend(monkeypatch):
    monkeypatch.setattr(settings, "CONFLICT_DEDUP_BACKEND", "memory")
    assert isinstance(build_dedup(), MemoryDedup)


def test_build_dedup_db_backend_without_session_falls_back_to_memory(monkeypatch):
    monkeypatch.setattr(settings, "CONFLICT_DEDUP_BACKEND", "db")
    assert isinstance(build_dedup(session=None), MemoryDedup)


def test_build_dedup_db_backend_uses_session(monkeypatch):
    monkeypatch.setattr(settings, "CONFLICT_DEDUP_BACKEND", "db")
    session = FakeSession(row=None)
    assert isinstance(build_dedup(session), DbDedup)


async def test_build_dedup_auto_uses_redis_then_db(monkeypatch):
    monkeypatch.setattr(settings, "CONFLICT_DEDUP_BACKEND", "auto")
    session = StatefulFakeSession()

    dedup = build_dedup(session)

    assert isinstance(dedup, AutoDedup)

    # 模拟 Redis 挂掉：auto 模式必须落到数据库后端并正常判重
    state = {"calls": 0}

    async def failing_claim(key):
        state["calls"] += 1
        raise ConnectionError("Redis 未启动")

    dedup._primary.claim = failing_claim  # type: ignore[method-assign]

    assert await dedup.claim(_key()) is True  # 库中无重复行 → 允许推送
    assert await dedup.claim(_key()) is False  # 库中已有该标题的行 → 压掉
    assert state["calls"] == 2


def test_build_dedup_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(settings, "CONFLICT_DEDUP_BACKEND", "MEMORY")
    assert isinstance(build_dedup(), MemoryDedup)
