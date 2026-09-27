"""边界与兜底路径（补齐 docs/test.md 覆盖面之外的分支）。

覆盖对象：兼容用的旧路径、状态机不变量、统一异常兜底、身份兜底、连接串派生。
这些分支平时不被主流程走到，但正是线上出问题时唯一生效的代码。
"""
import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.core.deps import MOCK_USER_ID
from app.core.exceptions import register_exception_handlers
from app.core.utils import parse_time
from app.models import ReserveOrder
from app.state_machine import IllegalTransitionError, OrderStatus, transition

from .helpers import OTHER_USER_ID, time_str

UID = MOCK_USER_ID


# ------------------------------------------------- 兼容路径 /api/v1/orders/user/{userId}


async def _create(client, space_id=1, days=1, hour=9, user_id=None):
    """建一条预约，返回 orderId。"""
    r = await client.post("/api/v1/orders/create", json={
        "spaceId": space_id, "deviceIds": [],
        "startTime": time_str(days, hour), "endTime": time_str(days, hour + 1),
    }, headers=None if user_id is None else {"X-User-Id": str(user_id)})
    assert r.status_code == 200, r.text
    return r.json()["data"]["orderId"]


async def test_legacy_user_orders_endpoint_is_scoped(client, db_session):
    """旧路径按路径参数查订单，且不会把他人订单带出来。"""
    mine_id = await _create(client)

    # 直插一条归属他人的订单（接口无法造出他人数据，故走会话）
    db_session.add(ReserveOrder(
        user_id=OTHER_USER_ID, space_id=2, device_ids=[],
        start_time=parse_time(time_str(2, 14)), end_time=parse_time(time_str(2, 15)),
        order_status=OrderStatus.PENDING.value,
    ))
    await db_session.commit()

    mine = (await client.get(f"/api/v1/orders/user/{UID}")).json()["data"]
    assert [o["orderId"] for o in mine] == [mine_id]
    assert {o["userId"] for o in mine} == {UID}

    theirs = (await client.get(f"/api/v1/orders/user/{OTHER_USER_ID}")).json()["data"]
    assert [o["userId"] for o in theirs] == [OTHER_USER_ID]

    nobody = (await client.get("/api/v1/orders/user/999999")).json()["data"]
    assert nobody == []


async def test_legacy_user_orders_endpoint_status_filter(client):
    """旧路径同样支持 status 过滤。"""
    oid = await _create(client)
    await client.put(f"/api/v1/orders/{oid}/confirm")

    pending = (await client.get(f"/api/v1/orders/user/{UID}?status=1")).json()["data"]
    confirmed = (await client.get(f"/api/v1/orders/user/{UID}?status=2")).json()["data"]

    assert pending == []
    assert [o["orderId"] for o in confirmed] == [oid]


# ------------------------------------------------- 不存在的订单：确认/取消 404


async def test_confirm_missing_order_returns_404(client):
    r = await client.put("/api/v1/orders/999999/confirm")
    assert r.status_code == 404
    assert r.json()["code"] == 404


async def test_cancel_missing_order_returns_404(client):
    r = await client.put("/api/v1/orders/999999/cancel")
    assert r.status_code == 404
    assert r.json()["code"] == 404


# ------------------------------------------------- 归属校验：他人订单一律 404

# 这三条钉的是同一个性质的漏洞：认证层只回答「你是谁」，不回答「这单是不是你的」。
# 路由里注入了 user_id 却不比对，等于把 orderId 当密码用——而 orderId 是自增的，
# 换个 X-User-Id 头就能读、能确认、能取消别人的预约。


async def test_cannot_read_others_order(client):
    """他人订单详情 → 404。

    这里必须是 404 而不是 403：403 等于承认「这单存在，只是不属于你」，
    可以拿来枚举全库有哪些 orderId。`messages.py` 对越权消息也是 404，口径一致。
    """
    oid = await _create(client, user_id=OTHER_USER_ID)

    r = await client.get(f"/api/v1/orders/{oid}")
    assert r.status_code == 404


async def test_cannot_confirm_others_order(client, db_session):
    """确认他人订单 → 404，且状态与通知都不能被动过。

    只断言 404 不够：这条路径的破坏力在于它**会写库**。若校验写在
    `transition()` 之后，接口照样返回 404，单子却已经被确认、通知也发出去了。
    """
    oid = await _create(client, user_id=OTHER_USER_ID)

    r = await client.put(f"/api/v1/orders/{oid}/confirm")
    assert r.status_code == 404

    order = await db_session.get(ReserveOrder, oid)
    assert order.order_status == OrderStatus.PENDING.value, "状态被越权改动了"
    # 通知不能发给原主人
    unread = await client.get(
        "/api/v1/messages/unread", headers={"X-User-Id": str(OTHER_USER_ID)}
    )
    assert unread.json()["data"]["count"] == 0


async def test_cannot_cancel_others_order(client, db_session):
    """取消他人订单 → 404，且状态不变（§5.3 取消是契约接口，越权影响面最大）。"""
    oid = await _create(client, user_id=OTHER_USER_ID)

    r = await client.put(f"/api/v1/orders/{oid}/cancel")
    assert r.status_code == 404

    order = await db_session.get(ReserveOrder, oid)
    assert order.order_status == OrderStatus.PENDING.value, "状态被越权改动了"


async def test_others_order_is_indistinguishable_from_missing(client):
    """越权与不存在必须返回**完全相同**的响应，否则可用于探测哪些 orderId 存在。"""
    oid = await _create(client, user_id=OTHER_USER_ID)

    theirs = await client.get(f"/api/v1/orders/{oid}")
    missing = await client.get("/api/v1/orders/999999")

    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json()


async def test_owner_can_still_use_own_order(client):
    """回归：加了归属校验之后，本人读 / 确认 / 取消照常可用（别把门焊死）。"""
    oid = await _create(client)

    assert (await client.get(f"/api/v1/orders/{oid}")).status_code == 200
    assert (await client.put(f"/api/v1/orders/{oid}/confirm")).status_code == 200
    assert (await client.put(f"/api/v1/orders/{oid}/cancel")).status_code == 200


# ------------------------------------------------- 身份兜底（§5.1）


async def test_missing_identity_header_falls_back_to_mock_user(client):
    """未带任何身份头时兜底 mock 用户 1，绝不放行请求体里的任意 userId。"""
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as bare:
        created = (await bare.post("/api/v1/orders/create", json={
            "spaceId": 1, "deviceIds": [],
            "startTime": time_str(1, 9), "endTime": time_str(1, 10),
            "userId": OTHER_USER_ID,          # 请求体里的 userId 必须被忽略
        })).json()["data"]

        mine = (await bare.get("/api/v1/orders/my")).json()["data"]

    assert created["userId"] == MOCK_USER_ID
    assert [o["userId"] for o in mine] == [MOCK_USER_ID]


# ------------------------------------------------- 状态机不变量


def test_transition_rejects_illegal_and_raises():
    """绕过 can_transition 直接流转必须抛错——这是防非法写入的最后一道闸。"""

    class _Order:
        order_status = OrderStatus.CANCELLED.value   # 终态

    order = _Order()
    with pytest.raises(IllegalTransitionError):
        transition(order, OrderStatus.CONFIRMED)
    assert order.order_status == OrderStatus.CANCELLED.value   # 未被改写

    order.order_status = OrderStatus.PENDING.value
    transition(order, OrderStatus.CONFIRMED)
    assert order.order_status == OrderStatus.CONFIRMED.value


# ------------------------------------------------- 统一异常兜底（§5.2 / §7.3）


def _throwing_app(exc: Exception) -> FastAPI:
    """挂一个必抛异常的临时 app，端到端验证兜底处理器（不改动真实 app 的路由）。"""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise exc

    return app


async def test_unhandled_exception_becomes_500_envelope():
    """未捕获异常 → 500 + 统一响应体，且不泄漏堆栈。"""
    transport = httpx.ASGITransport(app=_throwing_app(RuntimeError("内部细节不应外泄")),
                                    raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/boom")

    assert r.status_code == 500
    assert r.json() == {"code": 500, "message": "服务器内部错误", "data": None}
    assert "内部细节" not in r.text


async def test_illegal_transition_becomes_409_envelope():
    """状态机非法流转若逃过前置校验，兜底为 409 而非 500。"""
    transport = httpx.ASGITransport(
        app=_throwing_app(IllegalTransitionError("非法状态流转: 3 -> 2")),
        raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/boom")

    assert r.status_code == 409
    assert r.json()["code"] == 409
    assert "非法状态流转" in r.json()["message"]


async def test_http_exception_uses_same_envelope(client):
    """404 等 HTTPException 同样是统一响应体（不是 FastAPI 默认的 detail 结构）。"""
    r = await client.get("/api/v1/orders/999999")
    assert r.status_code == 404
    assert set(r.json()) == {"code", "message", "data"}


# ------------------------------------------------- 连接串派生


def test_sync_url_converts_asyncmy_to_pymysql():
    """显式 DATABASE_URL 也要给出对应的同步串（Alembic / 同步脚本用）。"""
    s = Settings(DATABASE_URL="mysql+asyncmy://u:p@h:3308/d?charset=utf8mb4")
    assert s.sync_database_url == "mysql+pymysql://u:p@h:3308/d?charset=utf8mb4"
