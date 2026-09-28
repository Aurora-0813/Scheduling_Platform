"""真实 ASGI 栈：lifespan 建表 + `/ws/notify` 端点（docs/模块3-test.md TC-20）。

`test_websocket.py` 覆盖的是 `ConnectionManager` 本身；这里用 `TestClient` 走完整
ASGI 栈，覆盖 `main.py` 的 lifespan 与 WebSocket 端点函数体。

**注意**：`TestClient` 在自己的线程里跑独立事件循环，而 aiosqlite 的连接绑定创建它的
事件循环 —— 跨循环复用会报错。因此进出前后都要 `async_engine.dispose()` 让出连接池。
"""
import time
from datetime import timedelta

import pytest
from starlette.testclient import TestClient

from app.core.database import Base, async_engine
from app.main import app
from app.websocket import manager

from .helpers import MOCK_USER_ID, OTHER_USER_ID, access_token, auth_headers, time_str

#: WS 握手用的 URL。身份走令牌而不是 user_id —— 见 app/main.py 的说明。
#: 断言里也用它，避免「测试和实现各拼一遍」导致口径漂移。
WS_URL = f"/ws/notify?token={access_token(MOCK_USER_ID)}"

#: `TestClient` 的同步请求不会带上客户端默认头，身份得逐条给。
REST_HEADERS = auth_headers(MOCK_USER_ID)


@pytest.fixture(autouse=True)
def _clean_manager():
    manager._connections.clear()
    yield
    manager._connections.clear()


@pytest.fixture
async def fresh_engine(_fresh_db):
    """先让 `_fresh_db` 灌完种子，再把连池让出给 TestClient 自己的事件循环。"""
    await async_engine.dispose()
    yield
    await async_engine.dispose()


def _wait_until(predicate, timeout: float = 1.0) -> bool:
    """短时轮询等待断连回调落定，避免依赖精确时序。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


# ------------------------------------------------------------ lifespan（§6.5）


async def test_lifespan_builds_schema_when_missing(fresh_engine):
    """清空全部表后由 lifespan 重建 —— 证明启动建表真的生效。"""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await async_engine.dispose()

    with TestClient(app) as c:          # 进入即触发 lifespan
        r = c.get("/api/v1/resources/spaces")

    assert r.status_code == 200, "表未重建会因缺表直接 500"
    assert r.json()["data"] == [], "重建后应是空表（种子已被清掉）"


# ------------------------------------------------------------ /ws/notify 端点


async def _create(client, headers=REST_HEADERS) -> int:
    """同步 `TestClient` 版建单，返回 orderId。"""
    r = client.post("/api/v1/orders/create", json={
        "spaceId": 1, "deviceIds": [],
        "startTime": time_str(1, 9), "endTime": time_str(1, 10),
    }, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]["orderId"]


async def test_ws_notify_receives_realtime_push(fresh_engine):
    """TC-20 真实连接：连上 `/ws/notify` 后，confirm 的推送能实时收到。"""
    with TestClient(app) as c:
        with c.websocket_connect(WS_URL) as ws:
            oid = await _create(c)
            assert c.put(f"/api/v1/orders/{oid}/confirm",
                         headers=REST_HEADERS).status_code == 200
            msg = ws.receive_json()

    assert msg["title"] == "预约已确认"
    assert msg["orderId"] == oid
    assert msg["receiverId"] == MOCK_USER_ID


async def test_ws_notify_receives_cancel_push(fresh_engine):
    """取消走的是变更致歉类型 notifyType=2（§6.3），真实连接同样可达。"""
    with TestClient(app) as c:
        with c.websocket_connect(WS_URL) as ws:
            oid = await _create(c)
            assert c.put(f"/api/v1/orders/{oid}/cancel",
                         headers=REST_HEADERS).status_code == 200
            msg = ws.receive_json()

    assert msg["title"] == "预约已取消"
    assert msg["notifyType"] == 2


async def test_ws_notify_disconnect_cleans_up(fresh_engine):
    """客户端断开后，端点函数体的 `except WebSocketDisconnect` 分支要清理连接表。"""
    with TestClient(app) as c:
        with c.websocket_connect(WS_URL) as ws:
            assert _wait_until(lambda: bool(manager._connections.get(MOCK_USER_ID)))
        # 退出 with 即断开

    assert _wait_until(lambda: not manager._connections.get(MOCK_USER_ID))


async def test_ws_notify_multiple_clients_same_user(fresh_engine):
    """同一用户多端在线时，两个连接都应收到推送。"""
    with TestClient(app) as c:
        with c.websocket_connect(WS_URL) as a, c.websocket_connect(WS_URL) as b:
            oid = await _create(c)
            assert c.put(f"/api/v1/orders/{oid}/confirm",
                         headers=REST_HEADERS).status_code == 200
            assert a.receive_json()["orderId"] == oid
            assert b.receive_json()["orderId"] == oid


# ------------------------------------------------- 握手鉴权（§5.1）


def _connect_rejected(url: str) -> bool:
    """尝试握手，返回是否被拒。被拒时 Starlette 抛 `WebSocketDisconnect`。"""
    from starlette.websockets import WebSocketDisconnect as _WSD

    with TestClient(app) as c:
        try:
            with c.websocket_connect(url):
                return False
        except _WSD:
            return True


@pytest.mark.parametrize("url", [
    "/ws/notify",                                   # 完全不带凭据
    f"/ws/notify?user_id={MOCK_USER_ID}",           # 旧写法：自报身份必须失效
    f"/ws/notify?user_id={OTHER_USER_ID}",          # 旧写法：更不能冒用他人
    "/ws/notify?token=not-a-jwt",                   # 令牌是假的
    f"/ws/notify?token={access_token(MOCK_USER_ID)[:-3]}xx",   # 签名被改坏
])
async def test_ws_handshake_rejects_unauthenticated(fresh_engine, url):
    """`?user_id=` 那条路必须彻底关闭。

    这条曾经是**任何人不带令牌**都能走的：`/ws/notify?user_id=2` 一连接，
    2 号的预约确认/取消通知就实时推给了陌生人。而 `user_id` 是自增的，
    枚举一遍就收全了。现在握手只认令牌，签名不对就不 accept。
    """
    assert _connect_rejected(url) is True


async def test_ws_handshake_rejects_refresh_token(fresh_engine):
    """refreshToken 不能用来开实时通道 —— 与 REST 侧同一条口径。

    不然「accessToken 短有效期」这层设计就被绕开了：refreshToken 活得更久，
    拿它连 WS 等于拿到一条长期的通知订阅。
    """
    from app.core.security import TokenType as _TT
    from app.core.security import create_token

    refresh, _ = create_token(MOCK_USER_ID, "user", _TT.REFRESH, timedelta(hours=1))
    assert _connect_rejected(f"/ws/notify?token={refresh}") is True
