"""
健康检查与就绪探针的测试（模块 10）

`GET /api/v1/ready` 是 **M1 验收（文档 2.1「库能连上」）的工具**，
因此它的行为必须固定住：

| 断言                                  | 为什么值得测                                     |
| ------------------------------------- | ------------------------------------------------ |
| `/health` 不碰数据库                   | 探活接口被依赖故障拖垮，会把可恢复的故障放大       |
| `/ready` 恒 200，结论放在 `status` 字段 | 它是诊断接口；503 会让浏览器只看到错误页，看不到原因 |
| Redis `disabled` 不算降级              | `REDIS_ENABLED=false` 是**正常配置**，不是故障     |
| 依赖失败时响应体不含连接串与密码        | 文档 9.4：探针接口是匿名可访问的                   |
| 数据库失败后回滚会话                    | 不回滚会让连接带着未完成事务回到池里               |
"""

from __future__ import annotations

import pytest

from app.api.v1 import health as health_module
from app.core.config import settings
from app.core.database import get_db
from app.core.error_codes import ErrorCode

pytestmark = pytest.mark.api


class _BrokenSession:
    """模拟「数据库连不上」的会话。"""

    def __init__(self) -> None:
        self.execute_calls = 0
        self.rollback_calls = 0

    async def execute(self, *_args: object, **_kwargs: object) -> None:
        self.execute_calls += 1
        raise RuntimeError("模拟数据库不可用")

    async def rollback(self) -> None:
        self.rollback_calls += 1


@pytest.fixture
def broken_db(application):
    """把 `get_db` 换成永远失败的会话。"""
    session = _BrokenSession()

    async def _override() -> _BrokenSession:
        return session

    application.dependency_overrides[get_db] = _override
    yield session
    application.dependency_overrides.pop(get_db, None)


@pytest.fixture
def degraded_redis(monkeypatch: pytest.MonkeyPatch):
    """让 Redis 探活返回 `degraded`（模拟 Redis 开了但连不上）。"""

    async def _degraded() -> str:
        return "degraded"

    monkeypatch.setattr(health_module, "redis_check_health", _degraded)


# ==========================================================================
# /health
# ==========================================================================
async def test_health_returns_envelope(client) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == ErrorCode.SUCCESS
    assert body["data"]["status"] == "ok"
    assert body["data"]["service"] == settings.APP_NAME


async def test_health_does_not_touch_the_database(client, broken_db: _BrokenSession) -> None:
    """
    `/health` 必须与依赖完全无关。

    它一旦开始检查数据库，「数据库慢」就会被编排层误判为「进程已死」
    并触发重启 —— 把局部故障放大成全量不可用。
    """
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert broken_db.execute_calls == 0


# ==========================================================================
# /ready
# ==========================================================================
async def test_ready_reports_healthy_state(client) -> None:
    """
    M1 验收：数据库通、Redis 按配置关闭 → `status=ok`。

    测试环境 `REDIS_ENABLED=false`（tests/conftest.py），因此 `redis`
    是 `disabled`；它不是故障，`status` 仍为 `ok`。
    """
    response = await client.get("/api/v1/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == ErrorCode.SUCCESS
    assert body["data"] == {
        "status": "ok",
        "db": "ok",
        "redis": "disabled",
        "appEnv": settings.APP_ENV,
    }


async def test_ready_is_degraded_when_redis_is_unreachable(client, degraded_redis: None) -> None:
    """Redis 开了但连不上 → `status=degraded`，但**仍是 HTTP 200**。"""
    response = await client.get("/api/v1/ready")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["redis"] == "degraded"
    assert data["status"] == "degraded"
    assert data["db"] == "ok"


async def test_ready_reports_db_error_without_raising_500(
    client, broken_db: _BrokenSession
) -> None:
    """数据库不可用 → `db=error`、`status=degraded`，接口本身仍是 200。"""
    response = await client.get("/api/v1/ready")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["db"] == "error"
    assert data["status"] == "degraded"


async def test_ready_rolls_back_after_a_failed_probe(client, broken_db: _BrokenSession) -> None:
    """
    探活失败后必须回滚。

    连接失败会让会话停在未完成的事务里，不回滚的话连接归还池子时
    带着脏事务，后续请求拿到它会出现难以复现的错误。
    """
    await client.get("/api/v1/ready")

    assert broken_db.rollback_calls == 1


async def test_ready_never_leaks_connection_details(client, broken_db: _BrokenSession) -> None:
    """
    探针是**匿名可访问**的，响应体里绝不能有连接串、主机、端口或密码（文档 9.4）。

    失败原因只进服务端日志。
    """
    response = await client.get("/api/v1/ready")

    text = response.text
    leaks = ["mysql+asyncmy", "asyncmy", "password", str(settings.DB_PORT), settings.DB_USER]
    if settings.DB_PASSWORD:
        leaks.append(settings.DB_PASSWORD)
    # 逐个报出泄露的片段，而不是只丢一句「断言失败」——
    # 否则排查时只能靠肉眼比对整段响应
    leaked = [item for item in leaks if item in text]
    assert not leaked, f"就绪探针响应体泄露了连接信息: {leaked}；完整响应: {text}"
