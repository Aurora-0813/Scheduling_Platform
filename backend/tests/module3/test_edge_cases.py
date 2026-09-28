"""边界与兜底路径（补齐 docs/模块3-test.md 覆盖面之外的分支）。

覆盖对象：兼容用的旧路径、状态机不变量、统一异常兜底、身份兜底、连接串派生。
这些分支平时不被主流程走到，但正是线上出问题时唯一生效的代码。
"""
import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.core.error_codes import DEFAULT_MESSAGES, ErrorCode
from app.core.response import register_exception_handlers
from app.core.utils import parse_time
from app.models import ReserveOrder
from app.state_machine import IllegalTransitionError, OrderStatus, transition

from .helpers import MOCK_USER_ID, OTHER_USER_ID, auth_headers, time_str

UID = MOCK_USER_ID


# ------------------------------------------------- 兼容路径 /api/v1/orders/user/{userId}


async def _create(client, space_id=1, days=1, hour=9, user_id=None):
    """建一条预约，返回 orderId。`user_id` 给定时以该用户的真实 JWT 发起。"""
    r = await client.post("/api/v1/orders/create", json={
        "spaceId": space_id, "deviceIds": [],
        "startTime": time_str(days, hour), "endTime": time_str(days, hour + 1),
    }, headers=None if user_id is None else auth_headers(user_id))
    assert r.status_code == 200, r.text
    return r.json()["data"]["orderId"]


async def test_legacy_user_orders_endpoint_is_scoped(client, db_session):
    """旧路径只返回**本人**订单；查他人一律 404，且响应体里不带任何订单。

    这条原先断言的是漏洞本身（「`GET /orders/user/2` 会返回 2 号的单」），方向已反过来。
    查别人与被查用户不存在**同一处理**，不因原因不同而换个说法。
    """
    mine_id = await _create(client)

    # 直插一条归属他人的订单（接口无法造出他人数据，故走会话）
    db_session.add(ReserveOrder(
        user_id=OTHER_USER_ID, space_id=2, device_ids=[],
        start_time=parse_time(time_str(2, 14)), end_time=parse_time(time_str(2, 15)),
        order_status=OrderStatus.PENDING.value,
    ))
    await db_session.commit()

    # 本人：仍然可用（这是收紧后唯一保留的用法）
    mine = (await client.get(f"/api/v1/orders/user/{UID}")).json()["data"]
    assert [o["orderId"] for o in mine] == [mine_id]
    assert {o["userId"] for o in mine} == {UID}

    # 他人：404，且响应体不得泄露任何订单字段
    theirs = await client.get(f"/api/v1/orders/user/{OTHER_USER_ID}")
    assert theirs.status_code == 404
    assert theirs.json()["message"] == "预约不存在"
    assert theirs.json()["data"] is None
    assert "orderId" not in theirs.text

    # 被查用户不存在：与越权同一处理
    nobody = await client.get("/api/v1/orders/user/999999")
    assert nobody.status_code == 404
    assert nobody.json() == theirs.json()


async def test_legacy_user_orders_endpoint_accepts_matching_path(client):
    """路径参数与**令牌身份**一致时照常返回 —— 收紧挡的是跨用户，不是旧客户端。"""
    oid = await _create(client)
    r = await client.get(
        f"/api/v1/orders/user/{UID}", headers=auth_headers(UID)
    )
    assert r.status_code == 200
    assert [o["orderId"] for o in r.json()["data"]] == [oid]


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
    """404 之外还要钉住业务码与文案：团队基线是「真实 HTTP 状态码 + 5 位业务码」。

    这里必须是 `40404`（预约订单不存在）而不是通用的 `40400` —— 前端按 `code`
    分支，`40404` 才能提示「该预约已不存在」并刷新列表。
    """
    r = await client.put("/api/v1/orders/999999/confirm")
    assert r.status_code == 404
    assert r.json()["code"] == ErrorCode.ORDER_NOT_FOUND
    assert r.json()["message"] == "预约不存在"


async def test_cancel_missing_order_returns_404(client):
    r = await client.put("/api/v1/orders/999999/cancel")
    assert r.status_code == 404
    assert r.json()["code"] == ErrorCode.ORDER_NOT_FOUND
    assert r.json()["message"] == "预约不存在"


# ------------------------------------------------- 归属校验：他人订单一律 404

# 这三条钉的是同一个性质的漏洞：认证层只回答「你是谁」，不回答「这单是不是你的」。
# 路由里注入了身份却不比对，等于把 orderId 当密码用 —— 而 orderId 是自增的，
# 换一个令牌就能读、能确认、能取消别人的预约。


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
    # 通知不能发给原主人（以他人身份查未读数）
    unread = await client.get(
        "/api/v1/messages/unread", headers=auth_headers(OTHER_USER_ID)
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


async def test_missing_token_is_rejected_not_defaulted(client):
    """不带令牌一律 401 / 40101 —— 身份**没有**兜底路径。

    本模块早先有一版读 `X-User-Id` 的 mock：没带令牌时兜底成演示用户 1。那等于
    把 §5.1 降级成可选项 —— 线上漏配令牌不会报错，只会安静地以 1 号身份读写数据。
    现在身份只有一个来源（JWT），缺失就是「未登录」。

    顺带钉住：那个旧请求头必须**彻底失效**，而不只是「不再优先」。
    """
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    body = {
        "spaceId": 1, "deviceIds": [],
        "startTime": time_str(1, 9), "endTime": time_str(1, 10),
        "userId": OTHER_USER_ID,          # 请求体里的 userId 也不作数
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as bare:
        r = await bare.post("/api/v1/orders/create", json=body)
        stale = await bare.post(
            "/api/v1/orders/create", json=body,
            headers={"X-User-Id": str(OTHER_USER_ID)},   # 旧 mock 的身份来源
        )

    for resp in (r, stale):
        assert resp.status_code == 401
        assert resp.json()["code"] == ErrorCode.TOKEN_MISSING
        assert resp.json()["data"] is None


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
    """未捕获异常 → 500 + 统一响应体（5 位业务码），且不泄漏堆栈。"""
    transport = httpx.ASGITransport(app=_throwing_app(RuntimeError("内部细节不应外泄")),
                                    raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/boom")

    assert r.status_code == 500
    assert r.json() == {
        "code": ErrorCode.INTERNAL_ERROR,
        "message": DEFAULT_MESSAGES[ErrorCode.INTERNAL_ERROR],
        "data": None,
    }
    assert "内部细节" not in r.text


async def test_illegal_transition_becomes_409_envelope():
    """状态机非法流转若逃过前置校验，兜底为 409 / 40903 而非 500。

    `IllegalTransitionError` 继承自团队的 `OrderStatusConflictError`（见
    `app/state_machine.py`），因此走的是 `BizError` 处理器，拿到的是
    「订单当前状态不允许该操作」这一段的专用业务码，而不是通用 40900。
    """
    transport = httpx.ASGITransport(
        app=_throwing_app(IllegalTransitionError("非法状态流转: 3 -> 2")),
        raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/boom")

    assert r.status_code == 409
    assert r.json()["code"] == ErrorCode.ORDER_STATUS_CONFLICT
    assert "非法状态流转" in r.json()["message"]


async def test_http_exception_uses_same_envelope(client):
    """404 等 HTTPException 同样是统一响应体（不是 FastAPI 默认的 detail 结构）。"""
    r = await client.get("/api/v1/orders/999999")
    assert r.status_code == 404
    assert set(r.json()) == {"code", "message", "data"}


# ------------------------------------------------- 同步驱动已彻底移除（§3.4）


def test_no_sync_database_path_remains():
    """`Settings.sync_database_url` 与 `app.core.database` 的同步引擎都已删除。

    §3.4 禁止同步驱动 PyMySQL / mysqlclient。团队此前的同步引擎是为 Alembic
    保留的，迁移改全异步（`alembic/env.py` 用 `async_engine_from_config`）后
    一并删除。本用例把「同步路径不存在」钉死：任一属性被加回来，都说明有人
    重新引入了 PyMySQL。这是 §3.4 的硬约束，不是风格问题。
    """
    import app.core.database as database

    s = Settings(DATABASE_URL="mysql+asyncmy://u:p@h:3308/d?charset=utf8mb4")
    assert not hasattr(s, "sync_database_url")
    assert not hasattr(database, "sync_engine")
    assert not hasattr(database, "SyncSessionLocal")
