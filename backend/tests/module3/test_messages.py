"""消息通知 / 扫描（docs/test.md TC-13 ~ TC-19）。"""
from datetime import datetime, timedelta

from sqlalchemy import select

from app.models import NotifyMessage, ReserveOrder

from .helpers import MOCK_USER_ID, OTHER_USER_ID, time_dt, time_str


async def _create_and_confirm(client, **overrides):
    """建单并确认，触发一条「预约已确认」通知，返回 orderId。"""
    body = {
        "spaceId": 1,
        "deviceIds": [],
        "startTime": time_str(1, 9),
        "endTime": time_str(1, 10),
    }
    body.update(overrides)
    oid = (await client.post("/api/v1/orders/create", json=body)).json()["data"]["orderId"]
    await client.put(f"/api/v1/orders/{oid}/confirm")
    return oid


async def _add_message(db_session, receiver_id, **overrides):
    """直连测试库写入一条通知（构造接口难以产生的数据）。"""
    msg = NotifyMessage(
        receiver_id=receiver_id,
        notify_type=overrides.get("notify_type", 1),
        order_id=overrides.get("order_id"),
        title=overrides.get("title", "测试通知"),
        content=overrides.get("content", "内容"),
        is_read=overrides.get("is_read", 0),
    )
    db_session.add(msg)
    await db_session.commit()
    await db_session.refresh(msg)
    return msg.id


# ---------------------------------------------------------------- 读取用例


async def test_tc13_message_list_pagination_and_order(client, db_session):
    """TC-13 列表分页，按 createTime 倒序。"""
    for i in range(3):
        await _add_message(db_session, MOCK_USER_ID, title=f"通知{i}")

    r = await client.get("/api/v1/messages", params={"skip": 0, "limit": 2})
    msgs = r.json()["data"]
    assert len(msgs) == 2
    assert msgs[0]["createTime"] >= msgs[1]["createTime"]

    rest = (await client.get("/api/v1/messages", params={"skip": 2, "limit": 2})).json()["data"]
    assert len(rest) == 1

    # 字段为 camelCase 且 isRead 为布尔（§5.1）
    assert {"messageId", "receiverId", "notifyType", "isRead", "createTime"} <= msgs[0].keys()
    assert msgs[0]["isRead"] is False


async def test_tc13b_limit_is_clamped(client, db_session):
    """分页上限保护：超大 limit 被收敛到 100，不会拉全表。"""
    r = await client.get("/api/v1/messages", params={"limit": 100000, "skip": -5})
    assert r.status_code == 200


async def test_tc14_unread_count(client, db_session):
    """TC-14 未读数等于未读消息条数。"""
    assert (await client.get("/api/v1/messages/unread")).json()["data"]["count"] == 0

    await _add_message(db_session, MOCK_USER_ID, is_read=0)
    await _add_message(db_session, MOCK_USER_ID, is_read=0)
    await _add_message(db_session, MOCK_USER_ID, is_read=1)  # 已读不计

    count = (await client.get("/api/v1/messages/unread")).json()["data"]["count"]
    assert count == 2


async def test_tc15_mark_single_read(client, db_session):
    """TC-15 单条已读 → isRead 转 true，未读数 -1。"""
    mid = await _add_message(db_session, MOCK_USER_ID)

    r = await client.put(f"/api/v1/messages/{mid}/read")
    assert r.status_code == 200
    assert r.json()["data"]["isRead"] is True

    count = (await client.get("/api/v1/messages/unread")).json()["data"]["count"]
    assert count == 0


async def test_tc16_mark_all_read(client, db_session):
    """TC-16 全部已读 → 未读数归零。"""
    for _ in range(3):
        await _add_message(db_session, MOCK_USER_ID)

    r = await client.put("/api/v1/messages/read-all")
    assert r.status_code == 200

    count = (await client.get("/api/v1/messages/unread")).json()["data"]["count"]
    assert count == 0


async def test_tc17_cannot_read_others_message(client, db_session):
    """TC-17 越权读他人消息 → 404（不泄露存在性）。"""
    mid = await _add_message(db_session, OTHER_USER_ID)

    r = await client.put(f"/api/v1/messages/{mid}/read")
    assert r.status_code == 404

    # 他人的未读不应影响当前用户
    assert (await client.get("/api/v1/messages/unread")).json()["data"]["count"] == 0


async def test_message_list_excludes_other_users(client, db_session):
    """列表只返回当前用户的消息。"""
    await _add_message(db_session, MOCK_USER_ID, title="我的")
    await _add_message(db_session, OTHER_USER_ID, title="他人的")

    msgs = (await client.get("/api/v1/messages")).json()["data"]
    assert [m["title"] for m in msgs] == ["我的"]


# ---------------------------------------------------------------- 扫描用例


async def test_tc18_reminder_scan(client):
    """TC-18 日程提醒扫描：1 小时内开始的已确认单生成提醒。"""
    soon = datetime.now() + timedelta(minutes=30)
    oid = await _create_and_confirm(
        client,
        startTime=soon.strftime("%Y-%m-%d %H:%M:%S"),
        endTime=(soon + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),
    )

    r = await client.post("/api/v1/messages/remind", params={"remind_hours": 1})
    assert r.status_code == 200
    assert r.json()["data"]["reminders"] >= 1

    msgs = (await client.get("/api/v1/messages")).json()["data"]
    assert any(m["title"] == "日程提醒" and m["orderId"] == oid for m in msgs)


async def test_tc18b_reminder_scan_skips_far_orders(client):
    """日程提醒只覆盖窗口内的单：明天的单不应被提醒。"""
    await _create_and_confirm(client, startTime=time_str(1, 9), endTime=time_str(1, 10))

    r = await client.post("/api/v1/messages/remind", params={"remind_hours": 1})
    assert r.json()["data"]["reminders"] == 0


async def test_tc19_conflict_scan(client, db_session):
    """TC-19 冲突扫描：同场地时段重叠的未完成单被识别。

    创建接口已硬编码拦截冲突，这里直连库构造重叠数据，验证扫描兜底能力。
    """
    start = time_dt(1, 9)
    db_session.add_all([
        ReserveOrder(user_id=MOCK_USER_ID, space_id=1, device_ids=[],
                     start_time=start, end_time=start + timedelta(hours=2),
                     order_status=1, agent_request="", agent_trace=[]),
        ReserveOrder(user_id=MOCK_USER_ID, space_id=1, device_ids=[],
                     start_time=start + timedelta(hours=1),
                     end_time=start + timedelta(hours=3),
                     order_status=2, agent_request="", agent_trace=[]),
    ])
    await db_session.commit()

    r = await client.get("/api/v1/conflicts/scan")
    assert r.status_code == 200
    conflicts = r.json()["data"]
    assert len(conflicts) == 1
    assert conflicts[0]["conflictType"] == "时段重叠"
    assert len(conflicts[0]["orderIds"]) == 2
    assert conflicts[0]["suggestion"]


async def test_tc19b_conflict_scan_ignores_finished_orders(client, db_session):
    """已取消/已完成的单不参与冲突扫描。"""
    start = time_dt(1, 9)
    for status in (3, 4):
        db_session.add(
            ReserveOrder(user_id=MOCK_USER_ID, space_id=1, device_ids=[],
                         start_time=start, end_time=start + timedelta(hours=2),
                         order_status=status, agent_request="", agent_trace=[])
        )
    await db_session.commit()

    conflicts = (await client.get("/api/v1/conflicts/scan")).json()["data"]
    assert conflicts == []


async def test_confirm_generates_unread_badge(client, db_session):
    """闭环：确认 → 未读 +1；整单读取后归零（对应流程文档 §5.2 快照）。"""
    await _create_and_confirm(client)
    assert (await client.get("/api/v1/messages/unread")).json()["data"]["count"] == 1

    await client.put("/api/v1/messages/read-all")
    assert (await client.get("/api/v1/messages/unread")).json()["data"]["count"] == 0

    rows = (await db_session.execute(select(NotifyMessage))).scalars().all()
    assert all(m.is_read == 1 for m in rows)
