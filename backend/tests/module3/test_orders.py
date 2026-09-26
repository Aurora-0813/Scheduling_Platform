"""预约创建 / 校验 / 状态机（docs/test.md TC-01 ~ TC-12）。"""
import pytest

from .helpers import MOCK_USER_ID, OTHER_USER_ID, time_str


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
    assert d["agentTrace"] == []            # §5.3 trace 必须是数组
    # create_time 由 server_default 生成，经 refresh 回填
    assert d["createTime"]
    assert d["updateTime"]


async def test_tc02_start_not_before_end(client):
    """TC-02 开始时间晚于结束时间 → 422。"""
    r, _ = await _create(client, startTime=time_str(1, 10), endTime=time_str(1, 9))
    assert r.status_code == 422
    assert "开始时间必须早于结束时间" in r.json()["message"]


async def test_tc03_invalid_time_format(client):
    """TC-03 时间格式非法（用 T 分隔）→ 422。"""
    bad = time_str(1, 9).replace(" ", "T")
    r, _ = await _create(client, startTime=bad)
    assert r.status_code == 422
    assert "YYYY-MM-DD HH:mm:ss" in r.json()["message"]


async def test_tc04_space_not_found(client):
    """TC-04 场地不存在 → 404。"""
    r, _ = await _create(client, spaceId=999)
    assert r.status_code == 404
    assert r.json()["message"] == "场地不存在"


async def test_tc05_device_not_found(client):
    """TC-05 设备不存在 → 404。"""
    r, _ = await _create(client, deviceIds=[999])
    assert r.status_code == 404
    assert "999" in r.json()["message"]


async def test_tc06_time_slot_conflict(client):
    """TC-06 该场地同时段已有未完成单 → 409。"""
    _, _ = await _create(client)
    r, _ = await _create(client)  # 同场地同时段
    assert r.status_code == 409
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


async def test_identity_comes_from_header_not_body(client):
    """§5.1 身份一律从 JWT（演示 X-User-Id）解析，请求体传 userId 不生效。"""
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
    assert r.json()["message"] == "当前状态不允许确认"


async def test_tc10_cancel_pending_order(client, monkeypatch):
    """TC-10 取消待确认单 → 3；未确认过，不应触发释放占用 hook。"""
    from app.api import orders as orders_api

    released = []
    monkeypatch.setattr(orders_api, "release_occupancy", lambda o: released.append(o.id))

    _, oid = await _create(client)
    r = await client.put(f"/api/v1/orders/{oid}/cancel")
    assert r.status_code == 200
    assert r.json()["data"]["orderStatus"] == 3
    assert released == []


async def test_tc11_cancel_confirmed_releases_occupancy(client, monkeypatch):
    """TC-11 取消已确认单 → 3，且触发释放场地/设备占用 hook。"""
    from app.api import orders as orders_api

    released = []
    monkeypatch.setattr(orders_api, "release_occupancy", lambda o: released.append(o.id))

    _, oid = await _create(client)
    await client.put(f"/api/v1/orders/{oid}/confirm")
    r = await client.put(f"/api/v1/orders/{oid}/cancel")
    assert r.status_code == 200
    assert r.json()["data"]["orderStatus"] == 3
    assert released == [oid]


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


# ---------------------------------------------------------------- 列表与详情


async def test_list_my_orders_only_mine(client):
    """GET /orders/my 只返回当前用户的单，按创建时间倒序。"""
    await _create(client, spaceId=1)
    await _create(client, spaceId=2)

    # 另一个用户的单
    await client.post(
        "/api/v1/orders/create",
        json={"spaceId": 1, "deviceIds": [], "startTime": time_str(2, 9),
              "endTime": time_str(2, 10)},
        headers={"X-User-Id": str(OTHER_USER_ID)},
    )

    r = await client.get("/api/v1/orders/my")
    orders = r.json()["data"]
    assert len(orders) == 2
    assert all(o["userId"] == MOCK_USER_ID for o in orders)
    assert orders[0]["createTime"] >= orders[1]["createTime"]  # 倒序


async def test_list_my_orders_filter_by_status(client):
    """状态筛选：status=2 只返回已确认单。"""
    _, oid = await _create(client)
    await _create(client, spaceId=2)
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
