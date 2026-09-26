"""真实 ASGI 栈：lifespan 建表 + `/ws/notify` 端点（docs/test.md TC-20）。

`test_websocket.py` 覆盖的是 `ConnectionManager` 本身；这里用 `TestClient` 走完整
ASGI 栈，覆盖 `main.py` 的 lifespan 与 WebSocket 端点函数体。

**注意**：`TestClient` 在自己的线程里跑独立事件循环，而 aiosqlite 的连接绑定创建它的
事件循环 —— 跨循环复用会报错。因此进出前后都要 `async_engine.dispose()` 让出连接池。
"""
import time

import pytest
from starlette.testclient import TestClient

from app.core.database import Base, async_engine
from app.main import app
from app.websocket import manager

from .helpers import MOCK_USER_ID, time_str


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


async def test_ws_notify_receives_realtime_push(fresh_engine):
    """TC-20 真实连接：连上 `/ws/notify` 后，confirm 的推送能实时收到。"""
    with TestClient(app) as c:
        with c.websocket_connect(f"/ws/notify?user_id={MOCK_USER_ID}") as ws:
            oid = c.post("/api/v1/orders/create", json={
                "spaceId": 1, "deviceIds": [],
                "startTime": time_str(1, 9), "endTime": time_str(1, 10),
            }).json()["data"]["orderId"]

            assert c.put(f"/api/v1/orders/{oid}/confirm").status_code == 200
            msg = ws.receive_json()

    assert msg["title"] == "预约已确认"
    assert msg["orderId"] == oid
    assert msg["receiverId"] == MOCK_USER_ID


async def test_ws_notify_receives_cancel_push(fresh_engine):
    """取消走的是变更致歉类型 notifyType=2（§6.3），真实连接同样可达。"""
    with TestClient(app) as c:
        with c.websocket_connect(f"/ws/notify?user_id={MOCK_USER_ID}") as ws:
            oid = c.post("/api/v1/orders/create", json={
                "spaceId": 1, "deviceIds": [],
                "startTime": time_str(1, 9), "endTime": time_str(1, 10),
            }).json()["data"]["orderId"]

            assert c.put(f"/api/v1/orders/{oid}/cancel").status_code == 200
            msg = ws.receive_json()

    assert msg["title"] == "预约已取消"
    assert msg["notifyType"] == 2


async def test_ws_notify_disconnect_cleans_up(fresh_engine):
    """客户端断开后，端点函数体的 `except WebSocketDisconnect` 分支要清理连接表。"""
    with TestClient(app) as c:
        with c.websocket_connect(f"/ws/notify?user_id={MOCK_USER_ID}") as ws:
            assert _wait_until(lambda: bool(manager._connections.get(MOCK_USER_ID)))
        # 退出 with 即断开

    assert _wait_until(lambda: not manager._connections.get(MOCK_USER_ID))


async def test_ws_notify_multiple_clients_same_user(fresh_engine):
    """同一用户多端在线时，两个连接都应收到推送。"""
    with TestClient(app) as c:
        with c.websocket_connect(f"/ws/notify?user_id={MOCK_USER_ID}") as a, \
             c.websocket_connect(f"/ws/notify?user_id={MOCK_USER_ID}") as b:
            oid = c.post("/api/v1/orders/create", json={
                "spaceId": 1, "deviceIds": [],
                "startTime": time_str(1, 9), "endTime": time_str(1, 10),
            }).json()["data"]["orderId"]

            assert c.put(f"/api/v1/orders/{oid}/confirm").status_code == 200
            assert a.receive_json()["orderId"] == oid
            assert b.receive_json()["orderId"] == oid
