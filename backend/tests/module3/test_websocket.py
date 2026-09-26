"""WebSocket 推送（docs/test.md TC-20 ~ TC-22）。

说明：`ws.js` ↔ `/ws/notify` 的真实长连接验证按 docs/test.md §7.2 用脚本手工执行；
此处对 `ConnectionManager` 做单元级覆盖，并顺带验证「业务动作 → 推送」链路。
"""
import pytest

from app.services.message_service import create_message
from app.websocket import ConnectionManager, manager

from .helpers import MOCK_USER_ID, time_str


class FakeWebSocket:
    """替代真实 WebSocket 的测试替身，记录收到的推送。"""

    def __init__(self, fail: bool = False):
        self.sent: list[dict] = []
        self.accepted = False
        self._fail = fail

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict) -> None:
        if self._fail:
            raise RuntimeError("连接已断开")
        self.sent.append(message)


@pytest.fixture(autouse=True)
def _clean_manager():
    """每个用例前后清空全局连接表，避免用例互相污染。"""
    manager._connections.clear()
    yield
    manager._connections.clear()


# ---------------------------------------------------------------- 连接管理


async def test_tc20_connect_and_push_to_target_user():
    """TC-20 连接后定向推送，只发给目标用户。"""
    ws = FakeWebSocket()
    await manager.connect(MOCK_USER_ID, ws)
    assert ws.accepted

    await manager.send_to_user(MOCK_USER_ID, {"title": "预约已确认"})
    assert ws.sent == [{"title": "预约已确认"}]

    # 推给别的用户不应串号
    await manager.send_to_user(MOCK_USER_ID + 100, {"title": "他人消息"})
    assert len(ws.sent) == 1


async def test_multiple_connections_per_user():
    """同一用户的多个活跃连接都应收到（多端在线）。"""
    a, b = FakeWebSocket(), FakeWebSocket()
    await manager.connect(MOCK_USER_ID, a)
    await manager.connect(MOCK_USER_ID, b)

    await manager.send_to_user(MOCK_USER_ID, {"n": 1})
    assert a.sent == b.sent == [{"n": 1}]


async def test_tc21_offline_user_push_is_silent():
    """TC-21 用户未连 WebSocket：推送静默跳过，不抛异常。"""
    await manager.send_to_user(MOCK_USER_ID, {"title": "无人在线"})  # 不应抛异常


async def test_offline_user_message_still_persisted(client, db_session):
    """TC-21 推送失败不影响落库：用户离线时消息仍写入，可通过列表补看。"""
    msg = await create_message(
        db_session, MOCK_USER_ID, "预约已确认", "您的预约 #1 已确认",
        notify_type=1, order_id=None, background_tasks=None,
    )
    assert msg.id is not None
    assert msg.create_time is not None      # server_default 已回填

    msgs = (await client.get("/api/v1/messages")).json()["data"]
    assert [m["messageId"] for m in msgs] == [msg.id]


async def test_tc22_broken_connection_is_evicted():
    """TC-22 单连接发送失败 → 移除该连接，但不影响其它连接。"""
    broken, healthy = FakeWebSocket(fail=True), FakeWebSocket()
    await manager.connect(MOCK_USER_ID, broken)
    await manager.connect(MOCK_USER_ID, healthy)

    await manager.send_to_user(MOCK_USER_ID, {"n": 1})   # 不应抛异常

    assert healthy.sent == [{"n": 1}]
    assert broken not in manager._connections.get(MOCK_USER_ID, set())
    assert healthy in manager._connections.get(MOCK_USER_ID, set())


async def test_disconnect_cleans_up_user_entry():
    """断开后连接表清理干净，不残留空集合。"""
    ws = FakeWebSocket()
    await manager.connect(MOCK_USER_ID, ws)
    manager.disconnect(MOCK_USER_ID, ws)

    assert MOCK_USER_ID not in manager._connections


async def test_manager_isolation_between_instances():
    """管理器互相独立（防止误用全局单例导致串号）。"""
    other = ConnectionManager()
    ws = FakeWebSocket()
    await other.connect(MOCK_USER_ID, ws)

    assert other._connections.get(MOCK_USER_ID)
    assert not manager._connections.get(MOCK_USER_ID)


# ------------------------------------------------------ 业务动作 → 推送链路


async def test_confirm_pushes_realtime_notification(client):
    """确认预约后，在线用户应实时收到「预约已确认」推送（REST 触发 WS）。"""
    ws = FakeWebSocket()
    await manager.connect(MOCK_USER_ID, ws)

    oid = (await client.post("/api/v1/orders/create", json={
        "spaceId": 1, "deviceIds": [], "startTime": time_str(1, 9),
        "endTime": time_str(1, 10)})
    ).json()["data"]["orderId"]

    r = await client.put(f"/api/v1/orders/{oid}/confirm")
    assert r.status_code == 200

    assert len(ws.sent) == 1
    payload = ws.sent[0]
    assert payload["title"] == "预约已确认"
    assert payload["orderId"] == oid
    assert payload["receiverId"] == MOCK_USER_ID
    assert payload["isRead"] is False
    assert payload["messageId"] and payload["createTime"]


async def test_cancel_pushes_realtime_notification(client):
    """取消预约（变更致歉类型 notify_type=2）同样实时推送。"""
    ws = FakeWebSocket()
    await manager.connect(MOCK_USER_ID, ws)

    oid = (await client.post("/api/v1/orders/create", json={
        "spaceId": 1, "deviceIds": [], "startTime": time_str(1, 9),
        "endTime": time_str(1, 10)})
    ).json()["data"]["orderId"]

    await client.put(f"/api/v1/orders/{oid}/cancel")

    assert len(ws.sent) == 1
    assert ws.sent[0]["title"] == "预约已取消"
    assert ws.sent[0]["notifyType"] == 2   # 变更致歉（§6.3）
