"""
接口层测试夹具

两个端点都不使用 get_db 请求级会话（中间要等大模型，不能握着连接），
因此这里不覆盖 get_db，而是替换各端点模块里的服务函数与 session_scope。
数据库读写本身由阶段 5 的真实 API 冒烟验证覆盖。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


def make_token(
    user_id: int = 1,
    username: str = "张三",
    role_name: str | None = "普通使用者",
    *,
    expires_in_minutes: int = 60,
) -> str:
    """按认证模块的载荷约定签发一枚可用 token（仅测试用）"""
    payload = {
        "sub": str(user_id),
        "username": username,
        "roleName": role_name,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes),
    }
    if role_name is None:
        payload.pop("roleName")
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class StubSession:
    """只记录写入的假会话，不连数据库"""

    def __init__(self, fail_after: int | None = None) -> None:
        self.added: list = []
        self.flushes = 0
        self.commits = 0
        self.executed: list = []
        self._fail_after = fail_after

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1
        if self._fail_after is not None and self.flushes >= self._fail_after:
            raise RuntimeError("模拟写库失败")

    async def commit(self) -> None:
        self.commits += 1

    async def execute(self, stmt):
        self.executed.append(stmt)
        raise AssertionError("接口测试不应真正查库（服务函数已被替换）")

    @property
    def receiver_ids(self) -> list[int]:
        return [msg.receiver_id for msg in self.added]

    @property
    def notify_types(self) -> list[int]:
        return [msg.notify_type for msg in self.added]


@pytest.fixture
def session() -> StubSession:
    return StubSession()


@pytest.fixture
def patch_scope(monkeypatch, session):
    """
    把某个端点模块里的 session_scope 换成返回同一个假会话的实现。

    返回同一个实例是为了让用例能直接检查写入了什么。
    """

    def _patch(module):
        @asynccontextmanager
        async def scope():
            yield session

        monkeypatch.setattr(module, "session_scope", scope)
        return session

    return _patch


@pytest.fixture
def client():
    """不带鉴权覆盖的客户端：走真实的 JWT 解析链路"""
    from app.main import app

    app.dependency_overrides.clear()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def fake_llm():
    from app.agent.chains.llm import build_fake_llm

    return build_fake_llm(
        ['{"title": "AI 标题", "content": "AI 生成的正文内容。"}']
    )


@pytest.fixture
def client_with_llm(client, fake_llm):
    """把 LLM 依赖换成假模型，避免接口测试打到真实 API"""
    from app.api.deps import get_llm
    from app.main import app

    app.dependency_overrides[get_llm] = lambda: fake_llm
    yield client
    app.dependency_overrides.clear()
