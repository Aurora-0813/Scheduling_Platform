"""
接口层测试夹具

两个端点都不使用 get_db 请求级会话（中间要等大模型，不能握着连接），
因此这里不覆盖 get_db，而是替换各端点模块里的服务函数与 session_scope。
数据库读写本身由阶段 5 的真实 API 冒烟验证覆盖。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient


def make_token(
    user_id: int = 1,
    username: str = "张三",
    role_name: str | None = "普通使用者",
    *,
    expires_in_minutes: int = 60,
) -> str:
    """签发一枚**能被正式版 `decode_token` 接受**的 accessToken（仅测试用）。

    ⚠️ **2026-09-28 重写 —— 旧实现造的是模块 7 自己那套载荷，合并后一律被拒。**

    旧实现手搓 `{sub, username, roleName, exp}`，而团队的
    `app/core/security.py::decode_token` 用的是
    `options={"require": ["exp", "iat", "sub", "jti", "type"]}` ——
    **缺 `iat` / `jti` / `type` 直接判 `TokenInvalidError`（40102）**。
    结果：本目录下所有「带令牌」的请求全部 401，两个文件 30 例无一幸免。

    现在直接调用**生产函数**签发，载荷自然齐备，也不再与生产口径漂移。
    `username` 形参保留只为兼容既有调用点：用户名由数据库查询给出
    （见 `app/api/deps.py`），**不从令牌取**，故这里不再写进载荷。
    `role` 仍写进载荷（与生产一致），但**授权判定不用它** ——
    同样以数据库为准，理由见 `app/api/deps.py` 的模块 docstring。
    """
    from app.core.security import TokenType, create_token

    issued, _payload = create_token(
        user_id=user_id,
        role=role_name,
        token_type=TokenType.ACCESS,
        expires_delta=timedelta(minutes=expires_in_minutes),
    )
    return issued


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
def sync_client(monkeypatch):
    """**同步**客户端（`fastapi.testclient.TestClient`），走真实的 JWT 解析链路。

    ⚠️ **2026-09-28 由 `client` 改名而来 —— 这是修一个夹具遮蔽事故，不是美化。**

    本目录下混着两族用例，对「client」的期待正好相反：

    - **异步族**（`test_auth_api` / `test_cors` / `test_health_api` /
      `test_monitor_api` / `test_mock_routes` / `test_response_envelope`）：
      `async def` + `await client.get(...)` → 要全局 `tests/conftest.py` 的
      **异步** `httpx.AsyncClient`。
    - **同步族**（`test_notify_api` / `test_conflicts_api`，模块 7）：
      `def` + `client.get(...)` → 要本文件的**同步** `TestClient`。

    原来这里叫 `client`，按 pytest 的 conftest 就近原则，它把全局那个异步
    `client` **整个盖掉了** —— 于是异步用例拿到同步 TestClient，
    `await client.get(...)` 全部报
    `TypeError: object Response can't be used in 'await' expression`（实测约 180 例）。

    改名后：需要同步的显式要 `sync_client`（或下面的 `client_with_llm`），
    需要异步的继续写 `client` 并自动拿到全局那一个。
    """
    from app.main import app
    from app.services import auth_service

    # --- 让「离线空库」也能通过认证 -----------------------------------------
    # 正式版的 `get_current_user`（`app/api/deps.py`）验完令牌签名后会**查库**取用户
    # （`auth_service.get_user_by_id`）。而本目录刻意**不覆盖 `get_db`**
    # （见模块 docstring），全局引擎指向的是空的临时 SQLite ——
    # 于是令牌再合法也会因「用户不存在」被判 40100，30 例全部 401。
    #
    # 这里只把**查库那三处**换成桩。**令牌解析仍是真实实现**：
    # 「无令牌 / 头格式错 / 签名伪造 / 已过期 / 类型不对」这些分支照走真实路径、
    # 照样被正确拒绝 —— 那正是本目录要测的东西，不能一起 stub 掉。
    class _StubUser:
        def __init__(self, uid: int) -> None:
            self.id = uid
            self.username = "张三"
            self.password = ""
            self.role_id = 1
            self.avatar = None
            # 必须等于 USER_STATUS_ACTIVE，否则被判账号禁用（40108）
            self.status = auth_service.USER_STATUS_ACTIVE

    async def _stub_get_user_by_id(_db, user_id: int):
        return _StubUser(user_id)

    monkeypatch.setattr(auth_service, "get_user_by_id", _stub_get_user_by_id)
    monkeypatch.setattr(auth_service, "role_name_of", lambda _user: "普通使用者")
    monkeypatch.setattr(auth_service, "permissions_of", lambda _user: ["*"])

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
def client_with_llm(sync_client, fake_llm):
    """把 LLM 依赖换成假模型，避免接口测试打到真实 API（模块 7 的同步用例用）。"""
    from app.api.deps import get_llm
    from app.main import app

    app.dependency_overrides[get_llm] = lambda: fake_llm
    yield sync_client
    app.dependency_overrides.clear()
