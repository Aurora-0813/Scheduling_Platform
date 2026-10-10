"""
订单生命周期：把「时段已过」的单自动结单。

背景（2026-10-10 需求）
-----------------------
`ACTIVE_ORDER_STATUSES` 是 `(1 待确认, 2 已确认)`。原先**没有任何东西**会把过了
`end_time` 的单移出这个集合，于是：

  · 订单状态永远停在「已确认」，列表上看起来还在进行中；
  · 它一直占着 `available_count` 的**占用计算**（场地/设备的剩余量推导）。

⚠️ 注意区分两件事：
  · 场地占用**显示**（`space_service.space_occupancy`）早就在查询时按时间排除了过期单，
    所以界面看起来是对的；
  · 但**状态列本身**没变，其它按 `order_status` 过滤的查询（冲突扫描、剩余量、
    看板统计）仍然把它当活跃单。

本模块补的就是第二件事：**让状态与事实一致**。

结单规则
--------
| 原状态 | 条件 | 新状态 | 写哪个时刻 |
|---|---|---|---|
| 2 已确认 | `end_time < now` | **4 已完成** | `completed_at = end_time` |
| 1 待确认 | `end_time < now` | **5 已过期** | `cancelled_at = end_time` |

两条的判据都是 `end_time < now` —— **时段结束**即结单，与「是否有人用过」无关。
这是产品明确要求的：时段过去了，名额就该放出来。

为什么待确认是「已过期(5)」而不是「已取消(3)」
--------------------------------------------
用户要能分清「我自己取消的」与「我忘了确认、系统替我取消了」——责任归属不同。
混成一个状态会让列表无法自证，所以单独给一个终态。

为什么 `completed_at` 取 `end_time` 而不是 `now()`
--------------------------------------------------
`end_time` 才是业务上的完成时刻。扫描每 300 秒一轮，订单 22:00 结束、22:04 才被扫到，
写 `now()` 会让用户看到「完成于 22:04」——那是扫描时间，不是完成时间。

并发与幂等
----------
· 每条 UPDATE 都带 `order_status = <原状态>` 作为条件，**乐观锁**：
  若这一轮扫到之后、提交之前用户恰好点了确认（1→2），UPDATE 命中 0 行，
  不会把一个刚被确认的单误判成过期。
· 整个操作是**幂等**的：重复扫描时被处理过的单已不在筛选条件里，不会二次写入；
  `completed_at IS NULL` / `cancelled_at IS NULL` 是第二重保险。
· 两个状态各一条**批量 UPDATE**（不是逐行 ORM 循环），一次事务提交。
  **有意不分批**：判据 `end_time < now AND order_status IN (1,2)` 正好吃得上
  `idx_status_start (order_status, start_time)` 的最左前缀，单条语句即可完成；
  真正会积压的极端场景（服务停摆很久）下也只是一次较大的 UPDATE，
  比起为了分批引入游标与多轮提交的复杂度，更划算。
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.reservation import ReserveOrder
from app.state_machine import OrderStatus
from app.utils.time_utils import now

logger = logging.getLogger(__name__)

__all__ = ["close_expired_orders", "expired_order_counts"]


async def expired_order_counts(db: AsyncSession, *, at=None) -> dict[str, int]:
    """**只读**统计：当前有多少单该被自动结单（不写库）。

    抽出来是为了让「扫描任务到底会不会有动作」可以被观测与测试，
    而不必真去改数据。
    """
    anchor = at or now()
    rows = (
        await db.execute(
            select(ReserveOrder.order_status, func.count())
            .where(
                ReserveOrder.end_time < anchor,
                ReserveOrder.order_status.in_(
                    (OrderStatus.PENDING.value, OrderStatus.CONFIRMED.value)
                ),
            )
            .group_by(ReserveOrder.order_status)
        )
    ).all()
    by_status = {int(status): int(n) for status, n in rows}
    return {
        "toComplete": by_status.get(OrderStatus.CONFIRMED.value, 0),
        "toExpire": by_status.get(OrderStatus.PENDING.value, 0),
    }


async def close_expired_orders(
    db: AsyncSession | None = None, *, at=None
) -> dict[str, int]:
    """
    把时段已过的活跃单结单，返回 `{completed, expired}` 两个计数。

    `db` 留空时自建会话（给定时任务用）；传进来则复用调用方的事务
    （给测试与手工补扫用，便于回滚）。

    参数：
        at : datetime | None  以哪个时刻判定「已过」，留口子便于测试。默认系统时间。
    """
    anchor = at or now()
    owns_session = db is None
    session = db or AsyncSessionLocal()

    try:
        # ---- ① 已确认 且 时段已过 → 已完成 ----
        completed = await session.execute(
            update(ReserveOrder)
            .where(
                ReserveOrder.order_status == OrderStatus.CONFIRMED.value,
                ReserveOrder.end_time < anchor,
                # 已完成过的不再重复写（幂等；正常情况上面那条已排除，这里是双保险）
                ReserveOrder.completed_at.is_(None),
            )
            .values(
                order_status=OrderStatus.COMPLETED.value,
                # ⚠️ 取 end_time 而非 anchor：见模块文档「为什么 completed_at 取 end_time」
                completed_at=ReserveOrder.end_time,
                update_time=func.now(),
            )
        )

        # ---- ② 待确认 且 时段已过 → 已过期 ----
        expired = await session.execute(
            update(ReserveOrder)
            .where(
                ReserveOrder.order_status == OrderStatus.PENDING.value,
                ReserveOrder.end_time < anchor,
                ReserveOrder.cancelled_at.is_(None),
            )
            .values(
                order_status=OrderStatus.EXPIRED.value,
                cancelled_at=ReserveOrder.end_time,
                update_time=func.now(),
            )
        )

        counts = {
            "completed": int(completed.rowcount or 0),
            "expired": int(expired.rowcount or 0),
        }

        if owns_session:
            await session.commit()

        if counts["completed"] or counts["expired"]:
            logger.info(
                "订单自动结单：完成 %s 单、过期 %s 单（判定时刻 %s）",
                counts["completed"],
                counts["expired"],
                anchor,
            )
        return counts
    except Exception:
        if owns_session:
            await session.rollback()
        raise
    finally:
        if owns_session:
            await session.close()
