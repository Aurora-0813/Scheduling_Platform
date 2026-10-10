"""
订单生命周期：时段已过的活跃单自动结单（2026-10-10 新增）

被测对象：`app/services/order_lifecycle.py::close_expired_orders`

规则：
    已确认(2) + end_time 已过 → 已完成(4)，`completed_at = end_time`
    待确认(1) + end_time 已过 → 已过期(5)，`cancelled_at = end_time`

⚠️ 本文件刻意**不通过 API** 造数据，而是直接写 ORM：要构造「时段在过去」的单，
   走 `/orders/create` 会被「时段重叠 / 开放时间」等前置校验拦住，
   而那些校验与被测逻辑无关。
"""

from datetime import datetime, timedelta

from sqlalchemy import select

from app.models.reservation import ACTIVE_ORDER_STATUSES, ReserveOrder
from app.services.order_lifecycle import close_expired_orders, expired_order_counts
from app.state_machine import OrderStatus

#: 判定用的基准时刻。固定值而非 now()，避免用例在午夜/秒级边界上抖动。
ANCHOR = datetime(2026, 10, 10, 12, 0, 0)


async def _order(db, *, status, start, end, space_id=1, user_id=1) -> int:
    """直接插一条订单，返回 id。"""
    o = ReserveOrder(
        user_id=user_id,
        space_id=space_id,
        device_ids=[],
        start_time=start,
        end_time=end,
        order_status=status,
    )
    db.add(o)
    await db.commit()
    await db.refresh(o)
    return int(o.id)


async def _reload(db, order_id: int) -> ReserveOrder:
    return (
        await db.execute(select(ReserveOrder).where(ReserveOrder.id == order_id))
    ).scalar_one()


# ---------------------------------------------------------------- 基本规则


async def test_confirmed_order_past_end_becomes_completed(db_session):
    """已确认 + 时段已过 → 已完成，且 `completed_at` 取 **end_time** 而非扫描时刻。"""
    end = ANCHOR - timedelta(hours=2)
    oid = await _order(
        db_session,
        status=OrderStatus.CONFIRMED.value,
        start=end - timedelta(hours=2),
        end=end,
    )

    counts = await close_expired_orders(db_session, at=ANCHOR)
    assert counts["completed"] == 1
    assert counts["expired"] == 0

    order = await _reload(db_session, oid)
    assert order.order_status == OrderStatus.COMPLETED.value
    assert order.completed_at == end, (
        "completed_at 必须取 end_time（业务完成时刻），不是扫描时刻 —— "
        "否则用户会看到「完成于扫描时间」，误导"
    )
    assert order.cancelled_at is None


async def test_pending_order_past_end_becomes_expired(db_session):
    """待确认 + 时段已过 → **已过期(5)**，不是已取消(3)。

    这是产品明确要求：用户要能分清「我自己取消的」与「我忘了确认、系统结单的」。
    """
    end = ANCHOR - timedelta(hours=1)
    oid = await _order(
        db_session,
        status=OrderStatus.PENDING.value,
        start=end - timedelta(hours=1),
        end=end,
    )

    counts = await close_expired_orders(db_session, at=ANCHOR)
    assert counts["expired"] == 1
    assert counts["completed"] == 0

    order = await _reload(db_session, oid)
    assert order.order_status == OrderStatus.EXPIRED.value, "待确认过期应是 5 已过期，不是 3 已取消"
    assert order.cancelled_at == end
    assert order.completed_at is None


async def test_counts_matches_what_would_be_closed(db_session):
    """`expired_order_counts` 是**只读**的：数值要与实际会结的单一致，且不写库。"""
    end = ANCHOR - timedelta(minutes=30)
    await _order(
        db_session, status=OrderStatus.CONFIRMED.value,
        start=end - timedelta(hours=1), end=end,
    )
    await _order(
        db_session, status=OrderStatus.PENDING.value,
        start=end - timedelta(hours=1), end=end, space_id=2,
    )

    before = await expired_order_counts(db_session, at=ANCHOR)
    assert before == {"toComplete": 1, "toExpire": 1}

    # 只读：查完不能有任何状态变化
    rows = (await db_session.execute(select(ReserveOrder.order_status))).scalars().all()
    assert set(rows) == {OrderStatus.CONFIRMED.value, OrderStatus.PENDING.value}, (
        "expired_order_counts 不该写库"
    )


# ---------------------------------------------------------------- 不该被动到的单


async def test_future_and_active_orders_untouched(db_session):
    """时段未结束的单**一律不动** —— 包括「正在进行中」和「未来」的。"""
    # 正在进行的：start 在过去、end 在未来
    running_id = await _order(
        db_session, status=OrderStatus.CONFIRMED.value,
        start=ANCHOR - timedelta(minutes=30), end=ANCHOR + timedelta(minutes=30),
    )
    # 未来的
    future_id = await _order(
        db_session, status=OrderStatus.PENDING.value,
        start=ANCHOR + timedelta(days=1), end=ANCHOR + timedelta(days=1, hours=2),
        space_id=2,
    )
    # 刚好在这一刻结束（end == ANCHOR）：判据是 `end_time < anchor`，严格小于，
    # 所以边界上的单**不算过期**，留给下一轮
    boundary_id = await _order(
        db_session, status=OrderStatus.CONFIRMED.value,
        start=ANCHOR - timedelta(hours=1), end=ANCHOR, space_id=3,
    )

    counts = await close_expired_orders(db_session, at=ANCHOR)
    assert counts == {"completed": 0, "expired": 0}

    for oid, expected in (
        (running_id, OrderStatus.CONFIRMED.value),
        (future_id, OrderStatus.PENDING.value),
        (boundary_id, OrderStatus.CONFIRMED.value),
    ):
        assert (await _reload(db_session, oid)).order_status == expected


async def test_terminal_orders_untouched(db_session):
    """已经是终态的单不该被再改一次（尤其是已取消的单不能被翻成已完成）。"""
    end = ANCHOR - timedelta(hours=3)
    cancelled_id = await _order(
        db_session, status=OrderStatus.CANCELLED.value,
        start=end - timedelta(hours=1), end=end,
    )
    completed_id = await _order(
        db_session, status=OrderStatus.COMPLETED.value,
        start=end - timedelta(hours=1), end=end, space_id=2,
    )
    expired_id = await _order(
        db_session, status=OrderStatus.EXPIRED.value,
        start=end - timedelta(hours=1), end=end, space_id=3,
    )

    counts = await close_expired_orders(db_session, at=ANCHOR)
    assert counts == {"completed": 0, "expired": 0}

    assert (await _reload(db_session, cancelled_id)).order_status == OrderStatus.CANCELLED.value
    assert (await _reload(db_session, completed_id)).order_status == OrderStatus.COMPLETED.value
    assert (await _reload(db_session, expired_id)).order_status == OrderStatus.EXPIRED.value


# ---------------------------------------------------------------- 幂等与并发


async def test_repeated_scan_is_idempotent(db_session):
    """连扫三次：只有第一次有动作，且不重复刷新 `completed_at`。"""
    end = ANCHOR - timedelta(hours=1)
    oid = await _order(
        db_session, status=OrderStatus.CONFIRMED.value,
        start=end - timedelta(hours=1), end=end,
    )

    first = await close_expired_orders(db_session, at=ANCHOR)
    assert first["completed"] == 1
    stamp = (await _reload(db_session, oid)).completed_at

    for _ in range(2):
        again = await close_expired_orders(db_session, at=ANCHOR)
        assert again == {"completed": 0, "expired": 0}, "重复扫描不该再有动作"

    assert (await _reload(db_session, oid)).completed_at == stamp, "completed_at 不该被覆盖"


async def test_confirm_right_before_sweep_is_not_expired(db_session):
    """乐观锁：单若在扫描前被用户确认（1→2），扫描**不该**把它判成已过期。

    实现上靠 UPDATE 的 `order_status = 1` 条件；这里用「先确认、再扫」模拟
    同一个语义（扫描读到的是已确认，于是走「已完成」分支而不是「已过期」）。
    """
    end = ANCHOR - timedelta(minutes=10)
    oid = await _order(
        db_session, status=OrderStatus.PENDING.value,
        start=end - timedelta(hours=1), end=end,
    )

    # 用户在扫描前确认了它
    order = await _reload(db_session, oid)
    order.order_status = OrderStatus.CONFIRMED.value
    await db_session.commit()

    counts = await close_expired_orders(db_session, at=ANCHOR)
    assert counts["expired"] == 0, "已确认的单不该被判成过期"
    assert counts["completed"] == 1
    assert (await _reload(db_session, oid)).order_status == OrderStatus.COMPLETED.value


# ---------------------------------------------------------------- 与占用口径的关系


async def test_closed_orders_leave_active_set(db_session):
    """结单后订单离开 `ACTIVE_ORDER_STATUSES` —— 这是本功能的**目的**。

    占用/剩余量都按这个常量现算（见 `docs/available_count口径判据.md`），
    所以「时段过去 → 结单 → 名额回来」这条链路是靠状态离开集合实现的，
    不需要任何回补代码。
    """
    end = ANCHOR - timedelta(hours=2)
    cid = await _order(
        db_session, status=OrderStatus.CONFIRMED.value,
        start=end - timedelta(hours=1), end=end,
    )
    pid = await _order(
        db_session, status=OrderStatus.PENDING.value,
        start=end - timedelta(hours=1), end=end, space_id=2,
    )

    await close_expired_orders(db_session, at=ANCHOR)

    still_active = (
        await db_session.execute(
            select(ReserveOrder.id).where(
                ReserveOrder.id.in_((cid, pid)),
                ReserveOrder.order_status.in_(ACTIVE_ORDER_STATUSES),
            )
        )
    ).scalars().all()
    assert list(still_active) == [], "结单后必须离开活跃集合，否则名额不会回来"

    # 5 已过期 也必须**不在**活跃集合里（新增状态时最易漏的一点）
    assert OrderStatus.EXPIRED.value not in ACTIVE_ORDER_STATUSES
