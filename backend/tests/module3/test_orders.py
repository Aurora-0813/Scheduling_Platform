"""预约创建 / 校验 / 状态机（docs/模块3-test.md TC-01 ~ TC-12）。"""

from datetime import time

import pytest

from app.core.error_codes import ErrorCode
from app.models import DeviceResource, SpaceResource

from .helpers import MOCK_USER_ID, OTHER_USER_ID, auth_headers, time_str


async def _create(client, **overrides):
    """创建一条预约，返回 (响应, orderId)。"""
    body = {
        "spaceId": 1,
        "deviceIds": [1],
        "startTime": time_str(1, 9),
        "endTime": time_str(1, 10),
    }
    body.update(overrides)
    r = await client.post("/api/v1/orders/create", json=body)
    data = r.json().get("data") or {}
    return r, data.get("orderId")


async def _add_space(db, **overrides) -> int:
    """加一个同时段开放的场地。

    夹具只种了 2 个场地，而设备容量用例要在**同一时段的 3 个不同场地**下单 ——
    第 3 步的时间冲突是按场地判的，同场地同时间根本走不到第 4 步的设备校验。
    """
    fields = {
        "space_name": "备用场地",
        "space_type": 1,
        "capacity": 5,
        "location": "9F",
        "open_start_time": time(8, 0),
        "open_end_time": time(22, 0),
        "status": 1,
    }
    fields.update(overrides)
    space = SpaceResource(**fields)
    db.add(space)
    await db.commit()
    await db.refresh(space)
    return space.id


# ---------------------------------------------------------------- 创建与校验


async def test_tc01_create_order_success(client):
    """TC-01 创建成功：返回待确认单，字段 camelCase，时间由库侧生成。"""
    r, oid = await _create(client)
    body = r.json()

    assert r.status_code == 200 and body["code"] == 200
    d = body["data"]
    assert oid is not None
    assert d["orderStatus"] == 1
    assert d["deviceIds"] == [1]
    assert d["userId"] == MOCK_USER_ID
    assert d["agentTrace"] == []  # §5.3 trace 必须是数组
    # create_time 由 server_default 生成，经 refresh 回填
    assert d["createTime"]
    assert d["updateTime"]


# TC-02 / TC-03 的状态码已从 422 改为 400（`40001`）。
# 团队基线的口径见 `docs/api.md` §1.4：Pydantic 校验失败与参数类业务失败**统一**
# 用 400 + 40001，FastAPI 默认的 422 被异常处理器显式改掉。前端只需要记住一条规则。
# 这两条时间校验已从 `schemas/order.py` 下沉到 `order_service`（那里是唯一校验点，
# Agent 的 Tool 路径也经过它），因此走的是 `conflictType="invalid_param"` 分支。


async def test_tc02_start_not_before_end(client):
    """TC-02 开始时间晚于结束时间 → 400 / 40001，且**具体原因要出现在响应里**。

    断言文案不是「顺手」：这两条消息一度被通用文案（「参数校验未通过：body
    取值不合法」）覆盖掉，用户看不到到底哪里错了。这里是防它复发的回归位。
    """
    r, _ = await _create(client, startTime=time_str(1, 10), endTime=time_str(1, 9))
    assert r.status_code == 400
    assert r.json()["code"] == ErrorCode.PARAM_INVALID
    assert "开始时间必须早于结束时间" in r.json()["message"]


async def test_tc03_invalid_time_format(client):
    """TC-03 时间格式非法（用 T 分隔）→ 400 / 40001，且提示出正确格式。"""
    bad = time_str(1, 9).replace(" ", "T")
    r, _ = await _create(client, startTime=bad)
    assert r.status_code == 400
    assert r.json()["code"] == ErrorCode.PARAM_INVALID
    assert "YYYY-MM-DD HH:mm:ss" in r.json()["message"]


async def test_tc04_space_not_found(client):
    """TC-04 场地不存在 → 404 / 40402（空间资源不存在）。

    同是 404，业务码要能区分「场地 / 设备 / 订单」——前端据此决定提示语。
    路由层按服务层返回的 `conflictDetail["target"]` 选异常类，见 `api/orders.py`。
    """
    r, _ = await _create(client, spaceId=999)
    assert r.status_code == 404
    assert r.json()["code"] == ErrorCode.SPACE_NOT_FOUND
    assert r.json()["message"] == "场地不存在"


async def test_tc05_device_not_found(client):
    """TC-05 设备不存在 → 404 / 40403，且提示里带上是哪一个 ID。"""
    r, _ = await _create(client, deviceIds=[999])
    assert r.status_code == 404
    assert r.json()["code"] == ErrorCode.DEVICE_NOT_FOUND
    assert "999" in r.json()["message"]


async def test_tc06_time_slot_conflict(client):
    """TC-06 该场地同时段已有未完成单 → 409 / 40901。"""
    _, _ = await _create(client)
    r, _ = await _create(client)  # 同场地同时段
    assert r.status_code == 409
    assert r.json()["code"] == ErrorCode.RESOURCE_CONFLICT
    assert r.json()["message"] == "该时段已被占用"


async def test_tc06b_adjacent_slot_not_conflict(client):
    """边界：首尾相接（10:00 结束 / 10:00 开始）不算冲突。"""
    _, _ = await _create(client, startTime=time_str(1, 9), endTime=time_str(1, 10))
    r, _ = await _create(client, startTime=time_str(1, 10), endTime=time_str(1, 11))
    assert r.status_code == 200


async def test_tc07_multiple_devices(client):
    """TC-07 多设备创建 → deviceIds 原样返回。"""
    r, _ = await _create(client, deviceIds=[1, 2])
    assert r.status_code == 200
    assert r.json()["data"]["deviceIds"] == [1, 2]


async def test_identity_comes_from_token_not_body(client):
    """§5.1 身份一律从 JWT 解析，请求体传 userId 不生效。

    请求体里塞 `userId` 是伪造身份最省事的一种：不碰任何请求头，也不触发认证
    分支，只赌服务端「顺手用了」这个字段。这里断言落库的归属是**令牌**里的那个。
    """
    r, _ = await _create(client, userId=OTHER_USER_ID)  # 伪造身份
    assert r.status_code == 200
    assert r.json()["data"]["userId"] == MOCK_USER_ID


# ---------------------------------------------------------------- 状态机流转


async def test_tc08_confirm_pending_order(client):
    """TC-08 确认待确认单 → 2，并生成「预约已确认」通知。"""
    _, oid = await _create(client)

    r = await client.put(f"/api/v1/orders/{oid}/confirm")
    assert r.status_code == 200
    assert r.json()["data"]["orderStatus"] == 2

    unread = (await client.get("/api/v1/messages/unread")).json()["data"]["count"]
    assert unread >= 1

    msgs = (await client.get("/api/v1/messages")).json()["data"]
    assert any(m["title"] == "预约已确认" and m["orderId"] == oid for m in msgs)


async def test_tc09_duplicate_confirm_rejected(client):
    """TC-09 重复确认 → 409。"""
    _, oid = await _create(client)
    await client.put(f"/api/v1/orders/{oid}/confirm")

    r = await client.put(f"/api/v1/orders/{oid}/confirm")
    assert r.status_code == 409
    assert r.json()["code"] == ErrorCode.ORDER_STATUS_CONFLICT
    assert r.json()["message"] == "当前状态不允许确认"


async def test_tc10_cancel_pending_order(client):
    """TC-10 取消待确认单 → 3；未确认过，无需任何释放动作。"""
    _, oid = await _create(client)
    r = await client.put(f"/api/v1/orders/{oid}/cancel")
    assert r.status_code == 200
    assert r.json()["data"]["orderStatus"] == 3


async def test_tc11_cancel_confirmed_releases_the_slot(client):
    """TC-11 取消已确认单 → 3，且**该单立刻不再占名额**。

    这条原先断言的是「触发了 `release_occupancy` hook」（monkeypatch 观测调用）。
    按 2026-09-28 定的口径，`available_count` 只读不写、占用用时推导，取消单离开
    `ACTIVE_ORDER_STATUSES` 即自动释放 —— 没有 hook 可触发（函数本身已删除）。

    所以改成断言**可观测的结果**而不是内部调用：取消后同一时段、同一设备能再下一单。
    这比原来那条更结实：它不依赖任何内部实现，钩子换成别的做法也照样成立。
    """
    _, oid = await _create(client, spaceId=1, deviceIds=[1])
    await client.put(f"/api/v1/orders/{oid}/confirm")
    assert (await _create(client, spaceId=2, deviceIds=[1]))[0].status_code == 409

    r = await client.put(f"/api/v1/orders/{oid}/cancel")
    assert r.status_code == 200
    assert r.json()["data"]["orderStatus"] == 3

    after, _ = await _create(client, spaceId=2, deviceIds=[1])
    assert after.status_code == 200, "取消已确认单后，名额必须立刻可用"


@pytest.mark.parametrize("action", ["confirm", "cancel"])
async def test_tc12_terminal_state_rejects_actions(client, action):
    """TC-12 终态（已取消）不可再 confirm / cancel。"""
    _, oid = await _create(client)
    await client.put(f"/api/v1/orders/{oid}/cancel")

    r = await client.put(f"/api/v1/orders/{oid}/{action}")
    assert r.status_code == 409


async def test_cancelled_slot_can_be_reused(client):
    """取消后该时段应可再次预约（冲突检测只统计 1/2 状态）。"""
    _, oid = await _create(client)
    await client.put(f"/api/v1/orders/{oid}/cancel")

    r, _ = await _create(client)  # 同场地同时段
    assert r.status_code == 200


async def test_agent_c01_02_capacity_and_cancel_roundtrip(client, db_session):
    """AGENT-C-01/02 判据 2~5 走真实 HTTP 全链路。

    容量 2 的设备：同时段前两单都成功（判据 2）→ 第三单 `409` / `40901`（判据 3）
    → `PUT /orders/{id}/cancel` 取消一单（判据 4）→ 第三单成功（判据 5）。

    「名额回落」没有回补代码：`ACTIVE_ORDER_STATUSES` 只有 1/2，取消单离开该集合，
    下一单算出来的占用自然少一。这条同时是**取消路由的回归位** —— 路由没注册
    会在判据 4 直接 404，而不是静默通过。
    """
    device = await db_session.get(DeviceResource, 1)
    device.total_count = device.available_count = 2
    await db_session.commit()
    third_space = await _add_space(db_session)

    first, first_id = await _create(client, spaceId=1, deviceIds=[1])  # 判据 1、2
    second, _ = await _create(client, spaceId=2, deviceIds=[1])
    assert (first.status_code, second.status_code) == (200, 200), "cap=2 时前两单必须成功"

    third, _ = await _create(client, spaceId=third_space, deviceIds=[1])  # 判据 3
    assert third.status_code == 409
    assert third.json()["code"] == ErrorCode.RESOURCE_CONFLICT

    cancelled = await client.put(f"/api/v1/orders/{first_id}/cancel")  # 判据 4
    assert cancelled.status_code == 200, "取消路由必须存在（404 = 路由没注册）"
    assert cancelled.json()["data"]["orderStatus"] == 3

    after, _ = await _create(client, spaceId=third_space, deviceIds=[1])  # 判据 5
    assert after.status_code == 200, "取消后名额必须回落"


# ---------------------------------------------------------------- 列表与详情


async def test_list_my_orders_only_mine(client):
    """GET /orders/my 只返回当前用户的单，按创建时间倒序。"""
    # 两条单同时段、不同场地 → 设备必须错开：同一设备在重叠时段只能被一条订单占用
    # （§5.5 第 4 步，见 tests/module3/test_order_service.py）
    await _create(client, spaceId=1, deviceIds=[1])
    await _create(client, spaceId=2, deviceIds=[2])

    # 另一个用户的单（断言状态码：这里静默失败过一次，列表用例会照常变绿）
    theirs = await client.post(
        "/api/v1/orders/create",
        json={
            "spaceId": 1,
            "deviceIds": [],
            "startTime": time_str(2, 9),
            "endTime": time_str(2, 10),
        },
        headers=auth_headers(OTHER_USER_ID),
    )
    assert theirs.status_code == 200, theirs.text

    r = await client.get("/api/v1/orders/my")
    orders = r.json()["data"]
    assert len(orders) == 2
    assert all(o["userId"] == MOCK_USER_ID for o in orders)
    assert orders[0]["createTime"] >= orders[1]["createTime"]  # 倒序


async def test_list_my_orders_filter_by_status(client):
    """状态筛选：status=2 只返回已确认单。"""
    _, oid = await _create(client)
    await _create(client, spaceId=2, deviceIds=[2])
    await client.put(f"/api/v1/orders/{oid}/confirm")

    r = await client.get("/api/v1/orders/my", params={"status": 2})
    orders = r.json()["data"]
    assert len(orders) == 1
    assert orders[0]["orderId"] == oid


async def test_order_detail_and_404(client):
    """详情接口：存在返回 camelCase，不存在返回 404。"""
    _, oid = await _create(client)

    r = await client.get(f"/api/v1/orders/{oid}")
    assert r.status_code == 200
    assert r.json()["data"]["orderId"] == oid

    r = await client.get("/api/v1/orders/999999")
    assert r.status_code == 404
    assert r.json()["message"] == "预约不存在"


async def test_resource_endpoints_camel_case(client):
    """资源接口返回 camelCase（§6.2），供小程序下拉联动。"""
    spaces = (await client.get("/api/v1/resources/spaces")).json()["data"]
    assert spaces and {"spaceId", "spaceName", "spaceType", "capacity"} <= spaces[0].keys()

    devices = (await client.get("/api/v1/resources/devices")).json()["data"]
    assert devices and {"deviceId", "deviceName", "deviceType"} <= devices[0].keys()
