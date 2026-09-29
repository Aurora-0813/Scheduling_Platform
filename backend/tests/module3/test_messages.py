"""消息通知 / 扫描（docs/模块3-test.md TC-13 ~ TC-19）。"""

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


async def test_tc19_conflict_scan_reports_soft_conflicts_only(client, db_session):
    """TC-19 **改写**：`/conflicts/scan` 报的是**软冲突**；时段重叠**不归它管**。

    ⚠️ **2026-09-28 改写 —— 原断言的三个前提现在全都不成立。**

    原文断言：
        assert len(conflicts) == 1
        assert conflicts[0]["conflictType"] == "时段重叠"
        assert len(conflicts[0]["orderIds"]) == 2

    ① **接口换了实现**。`/conflicts/scan` 现在由**模块 7 的正式实现**提供
       （`app/api/v1/conflict.py`）：跑 5 条**软冲突规则**，`conflictType` 固定为
       「软冲突」、每条另带 `ruleCode`。模块 3 自己那份（`app/api/conflicts.py`，
       返回「时段重叠」）**未注册** —— `app/api/v1/__init__.py:86-87` 明确「不注册」。
       （本轮已按同一判断处理了 `docs/api.md:405` 的旧示例。）

    ② **口径本来就是分开的**。`docs/开发流程.md` §4.4 的表写得很明确：
           硬冲突 = 事务校验（后端算法），例：同一场地同时段重复预约
           软冲突 = AI 扫描，例：同团队连续活动无休息、容量远超需求
       **「AI 只负责软冲突，硬冲突由事务兜底」**。所以时段重叠**本就不该**出现在
       这个接口里 —— 它由 `create_order` 的 §5.5 第 3 步拦下，已由 TC-06 覆盖。

    ③ **`len(...) == 1` 是巧合**。实测那条命中的是 `space_idle`（长期闲置）：
       本文件的迷你种子只建了 space 1/2，而 space 2 从未被预约过，
       于是稳定产出一条 `{"ruleCode": "space_idle", "orderIds": []}`。
       它与「时段重叠」毫无关系，却让旧断言的前半条"碰巧"通过了。

    本用例改为验**当前实现真实承担的职责**：契约形状 + 只报软冲突 +
    不把时段重叠混进软冲突结果。
    """
    start = time_dt(1, 9)
    overlapping = [
        ReserveOrder(
            user_id=MOCK_USER_ID,
            space_id=1,
            device_ids=[],
            start_time=start,
            end_time=start + timedelta(hours=2),
            order_status=1,
            agent_request="",
            agent_trace=[],
        ),
        ReserveOrder(
            user_id=MOCK_USER_ID,
            space_id=1,
            device_ids=[],
            start_time=start + timedelta(hours=1),
            end_time=start + timedelta(hours=3),
            order_status=2,
            agent_request="",
            agent_trace=[],
        ),
    ]
    db_session.add_all(overlapping)
    await db_session.commit()

    r = await client.get("/api/v1/conflicts/scan")
    assert r.status_code == 200
    conflicts = r.json()["data"]

    # `docs/api.md` §5.2 的字段表：四个字段一个不少（`ruleCode` 是追加字段）
    for item in conflicts:
        assert set(item) >= {"conflictType", "orderIds", "suggestion", "ruleCode"}
        assert item["conflictType"] == "软冲突"
        assert item["suggestion"]

    # 时段重叠 = 硬冲突：应由事务兜底，不该由软冲突扫描报出来
    flagged = {oid for item in conflicts for oid in item["orderIds"]}
    overlapped_ids = {o.id for o in overlapping}
    assert not (flagged & overlapped_ids), (
        "时段重叠是硬冲突，应由 create_order 的事务兜底（§4.4 / §5.5），"
        f"不该由本接口报出。冲突报了 {sorted(flagged)}，重叠单是 {sorted(overlapped_ids)}"
    )


async def test_tc19b_conflict_scan_ignores_finished_orders(client, db_session):
    """已取消/已完成的单不参与冲突扫描。

    ⚠️ **2026-09-28 改写：把断言从「整体为空」收敛到「终态单没被算进去」。**

    原文是 `assert conflicts == []` —— 这条**过强**了。它顺带把另一条完全正常的
    规则也算成了失败：本文件的迷你种子只建了 space 1/2，而 **space 2 从未被预约过**，
    于是 `space_idle`（长期闲置，§4.4 第 5 条规则）稳定产出一条
    `{"ruleCode": "space_idle", "orderIds": []}`。那条**是对的**，
    与「终态单是否参与」毫无关系，却让本用例一直红着。

    改为**直接断言本用例真正关心的事**：终态订单不得出现在任何冲突的 `orderIds` 里。
    这比 `== []` 更精确 —— 不会因别的规则正常触发而误报，
    但依然能抓住「终态单被算进冲突」这个真问题（那才是本用例存在的理由）。
    """
    start = time_dt(1, 9)
    finished: list[ReserveOrder] = []
    for status in (3, 4):
        order = ReserveOrder(
            user_id=MOCK_USER_ID,
            space_id=1,
            device_ids=[],
            start_time=start,
            end_time=start + timedelta(hours=2),
            order_status=status,
            agent_request="",
            agent_trace=[],
        )
        finished.append(order)
        db_session.add(order)
    await db_session.commit()

    conflicts = (await client.get("/api/v1/conflicts/scan")).json()["data"]

    flagged = {oid for item in conflicts for oid in item["orderIds"]}
    finished_ids = {o.id for o in finished}
    assert not (flagged & finished_ids), (
        "已取消(3)/已完成(4)的单不在 ACTIVE_ORDER_STATUSES 里，不该被算进冲突。"
        f"冲突报了 {sorted(flagged)}，终态单是 {sorted(finished_ids)}"
    )


async def test_confirm_generates_unread_badge(client, db_session):
    """闭环：确认 → 未读 +1；整单读取后归零（对应流程文档 §5.2 快照）。"""
    await _create_and_confirm(client)
    assert (await client.get("/api/v1/messages/unread")).json()["data"]["count"] == 1

    await client.put("/api/v1/messages/read-all")
    assert (await client.get("/api/v1/messages/unread")).json()["data"]["count"] == 0

    rows = (await db_session.execute(select(NotifyMessage))).scalars().all()
    assert all(m.is_read == 1 for m in rows)
