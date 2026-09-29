"""`GET /resources/spaces/{spaceId}/booked` 接口用例（2026-09-30 新增）。

为什么需要这个接口
------------------
小程序要能「选一个场地，看它哪些时间段已经被人订走了」。原有接口都答不了：
  · `/orders/my`         只看得到**自己**的预约
  · `/orders/user/{id}`  是按**人**查，不是按场地查
  · `/image/analyze`     回的 `availableTime` 语义是「剩余**空档**」，
                          拿不到「被谁、在哪一段」占掉的信息

本文件钉住三件事：
1. **占用口径**与下单判重同源（1 待确认 / 2 已确认）——否则会出现
   「接口说占了、下单却说没占」的自相矛盾。
2. **窗口语义**：只返回与「今天起 N 天」有重叠的订单，已取消 / 已完成一律释放。
3. **鉴权与错误码**：会暴露他人预约时段，必须登录；场地不存在给 40402。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reservation import ReserveOrder
from app.models.resource import SpaceResource
from tests.fakes.factories import ADMIN_PASSWORD, create_admin

pytestmark = pytest.mark.api

BOOKED = "/api/v1/resources/spaces/{space_id}/booked"


async def _seed(db: AsyncSession) -> None:
    """一个场地 + 三条订单：一条真占用、一条已取消、一条远在 40 天后（窗口外）。"""
    db.add(
        SpaceResource(
            id=6,
            space_name="综合楼大礼堂",
            space_type=3,
            capacity=80,
            location="综合楼1楼",
            budget=1500,
            open_start_time=time(8, 0),
            open_end_time=time(22, 0),
            status=1,
        )
    )

    today = date.today()
    soon = today + timedelta(days=2)
    far = today + timedelta(days=40)

    db.add(
        ReserveOrder(
            id=66,
            user_id=1,
            space_id=6,
            device_ids=[5, 1],
            start_time=datetime.combine(soon, time(14, 0)),
            end_time=datetime.combine(soon, time(16, 0)),
            order_status=2,  # 已确认 → 占用
        )
    )
    db.add(
        ReserveOrder(
            id=67,
            user_id=1,
            space_id=6,
            device_ids=[],
            start_time=datetime.combine(soon, time(18, 0)),
            end_time=datetime.combine(soon, time(20, 0)),
            order_status=3,  # 已取消 → 时段已释放
        )
    )
    db.add(
        ReserveOrder(
            id=68,
            user_id=1,
            space_id=6,
            device_ids=[],
            start_time=datetime.combine(far, time(10, 0)),
            end_time=datetime.combine(far, time(12, 0)),
            order_status=2,  # 占用，但在 7 天窗口之外
        )
    )
    await db.commit()


async def test_returns_only_occupying_slots_inside_window(
    client: httpx.AsyncClient, db_session: AsyncSession, login, auth_headers
) -> None:
    """默认窗口（今天起 7 天）内只回真占用的那条，已取消与窗口外的一律不回。"""
    await create_admin(db_session)
    await _seed(db_session)
    tokens = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]

    resp = await client.get(BOOKED.format(space_id=6), headers=auth_headers(tokens))
    assert resp.status_code == 200, resp.text

    data = resp.json()["data"]
    assert data["spaceId"] == 6
    assert data["spaceName"] == "综合楼大礼堂"
    assert data["days"] == 7
    # 场地信息一并返回，前端不必再单独查一次 /resources/spaces
    assert data["openStartTime"] == "08:00:00"
    assert data["openEndTime"] == "22:00:00"
    assert data["capacity"] == 80

    assert data["count"] == 1, "已取消的不算、窗口外的也不算"
    assert [b["orderId"] for b in data["bookings"]] == [66]

    booking = data["bookings"][0]
    assert booking["orderStatus"] == 2
    assert booking["deviceIds"] == [5, 1]
    # 时间是 'YYYY-MM-DD HH:mm:ss' 契约格式，不是 ISO 带 T/Z
    assert " " in booking["startTime"] and "T" not in booking["startTime"]


async def test_window_is_widened_by_days_param(
    client: httpx.AsyncClient, db_session: AsyncSession, login, auth_headers
) -> None:
    """days 放大到 60 天后，40 天后那条也要出现 —— 证明上一条不是「永远只有 1 条」。"""
    await create_admin(db_session)
    await _seed(db_session)
    tokens = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]

    resp = await client.get(
        BOOKED.format(space_id=6), params={"days": 60}, headers=auth_headers(tokens)
    )
    assert resp.status_code == 200, resp.text

    data = resp.json()["data"]
    assert data["days"] == 60
    assert sorted(b["orderId"] for b in data["bookings"]) == [66, 68]


async def test_empty_bookings_is_a_real_answer(
    client: httpx.AsyncClient, db_session: AsyncSession, login, auth_headers
) -> None:
    """没占用回 0 条、`bookings: []`，而不是报错 —— 「没人订」本身就是要展示给用户的信息。"""
    await create_admin(db_session)
    db_session.add(
        SpaceResource(
            id=8,
            space_name="中心广场",
            space_type=4,
            capacity=100,
            location="园区中心",
            status=1,
        )
    )
    await db_session.commit()
    tokens = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]

    resp = await client.get(BOOKED.format(space_id=8), headers=auth_headers(tokens))
    assert resp.status_code == 200, resp.text

    data = resp.json()["data"]
    assert data["count"] == 0
    assert data["bookings"] == []


async def test_requires_login(client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """会暴露他人的预约时段，不能裸奔。"""
    await _seed(db_session)

    resp = await client.get(BOOKED.format(space_id=6))
    assert resp.status_code == 401
    assert resp.json()["code"] == 40101


async def test_unknown_space_is_40402(
    client: httpx.AsyncClient, db_session: AsyncSession, login, auth_headers
) -> None:
    """场地不存在给 40402（与 inspect_service 的场地不存在同码），不是空列表。

    空列表会被前端渲染成「这个场地没人订」，把「场地根本不存在」谎报成「空闲」。
    """
    await create_admin(db_session)
    tokens = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]

    resp = await client.get(BOOKED.format(space_id=999), headers=auth_headers(tokens))
    assert resp.status_code == 404
    assert resp.json()["code"] == 40402


@pytest.mark.parametrize("bad_days", [0, -1, 999])
async def test_days_out_of_range_is_400(
    client: httpx.AsyncClient, db_session: AsyncSession, login, auth_headers, bad_days: int
) -> None:
    """days 越界由 FastAPI Query(ge/le) 拦下，统一成 40001 参数校验失败。"""
    await create_admin(db_session)
    await _seed(db_session)
    tokens = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]

    resp = await client.get(
        BOOKED.format(space_id=6), params={"days": bad_days}, headers=auth_headers(tokens)
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40001
