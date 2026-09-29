"""
设备行锁的**云库实测**（会写库，但自带清理）

用途
----
验证 order_service 的「设备维度容量」判据在真实 MySQL/InnoDB 上是否守得住，
也就是 _lock_devices_stmt 的 docstring 里那段推演的实测。

为什么只能在云库上跑
--------------------
tests/conftest.py 在导入 app 之前就把 DATABASE_URL 钉成了临时 SQLite；
而 SQLite 方言会把 FOR UPDATE **编译掉**、pysqlite 又不会为 SELECT 开事务，
于是离线用例里几个协程都会读到「还差一个名额」→ 必然超卖。

所以 tests/test_agent_concurrency.py::test_assert_3b 与
tests/module3/test_order_service.py::test_concurrent_device_creation_does_not_oversell
挂着 xfail(strict=True) —— 那是**诚实**，不是偷懒。**不要**在离线环境里摘掉它们；
本脚本存在的意义，就是把「云库上到底行不行」变成一条可复现的命令。

A / B / C 三组对照
------------------
    A 组  原样（设备行锁在位）                                  -> 期望「恰好 cap 单成功」
    B 组  monkeypatch 去掉 with_for_update（读一样的行，只是不加锁） -> 期望「超卖」
    C 组  恢复原实现                                            -> 期望回到「恰好 cap 单成功」

B 组是**必需的反证**：只有 B 组真的超卖，才能说明 A 组的干净是被那把锁挡住的，
而不是「并发压力不够、碰巧没撞上」。若 B 组也没超卖，本脚本报「无法得出结论」
而不是「通过」。

用法（在 backend/ 目录下执行，需先起好 SSH 隧道）
------------------------------------------------
    python scripts/verify_locking.py
    python scripts/verify_locking.py --concurrency 8 --rounds 3
    python scripts/verify_locking.py --device-id 12

退出码
------
    0  结论明确：带锁不超卖、去锁超卖
    1  **设备超卖**（锁失效）—— 真问题，需要查
    2  无法得出结论（B 组也没超卖，本轮并发压力不足以复现竞态）

安全
----
- 只允许在**开发 / 测试**库上运行（APP_ENV 与库名双重校验），生产库直接拒绝。
- 全程只通过 order_service.create_order 写（走真实业务路径）；结束时按
  「id > 基线」删除本次新增的 reserve_order / notify_message 行，**不动**既有数据。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 允许以 `python scripts/verify_locking.py` 方式运行：把 backend/ 加进 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows 控制台默认 GBK，中文结论可能乱码甚至抛 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import sqlalchemy as sa
from sqlalchemy import text

from app.core.config import settings
from app.core.database import async_engine
from app.models.resource import DeviceResource
from app.services import order_service

_SEP = "=" * 72


def title(t: str) -> None:
    print()
    print(_SEP)
    print("  " + t)
    print(_SEP)


def ok(t: str) -> None:
    print("  [OK]   " + t)


def warn(t: str) -> None:
    print("  [WARN] " + t)


def fail(t: str) -> None:
    print("  [FAIL] " + t)


def say(t: str = "") -> None:
    print(t)


def _guard_environment() -> bool:
    """只放行开发 / 测试库。生产库一律拒绝 —— 本脚本唯一不可绕过的护栏。"""
    env = (settings.APP_ENV or "").lower()
    db = settings.DB_NAME or ""
    if env not in ("dev", "development", "local", "test"):
        fail(f"被拒绝：APP_ENV={settings.APP_ENV} 不是开发 / 测试环境。")
        say("         本脚本会真实写入预约订单，禁止对生产库运行。")
        return False
    if not any(k in db.lower() for k in ("dev", "test")):
        fail(f"被拒绝：库名 {db!r} 看起来不是开发 / 测试库。")
        return False
    return True


async def _snapshot() -> tuple[int, int]:
    """记录基线 id，用于收尾时只删本次新增的行。"""
    async with async_engine.connect() as conn:
        order_max = (await conn.execute(
            text("SELECT COALESCE(MAX(id), 0) FROM reserve_order"))).scalar()
        notify_max = (await conn.execute(
            text("SELECT COALESCE(MAX(id), 0) FROM notify_message"))).scalar()
    return int(order_max), int(notify_max)


async def _cleanup(order_max: int, notify_max: int) -> tuple[int, int]:
    """删除本次新增的行；返回 (删掉的订单数, 删掉的通知数)。"""
    async with async_engine.begin() as conn:
        n = (await conn.execute(
            text("DELETE FROM notify_message WHERE id > :m"), {"m": notify_max})).rowcount
        o = (await conn.execute(
            text("DELETE FROM reserve_order WHERE id > :m"), {"m": order_max})).rowcount
    return o, n


async def _pick_device(preferred: int | None) -> tuple[int, str, int]:
    """挑一台 available_count >= 2 且状态完好的设备作为争抢目标。"""
    stmt = sa.select(
        DeviceResource.id, DeviceResource.device_name, DeviceResource.available_count,
    )
    async with async_engine.connect() as conn:
        if preferred is not None:
            row = (await conn.execute(stmt.where(DeviceResource.id == preferred))).first()
            if row is None:
                raise SystemExit(f"指定的设备 id={preferred} 不存在")
            if not row[2] or row[2] < 2:
                raise SystemExit(
                    f"设备 id={preferred} 的 available_count={row[2]}，"
                    "必须 >= 2 才能区分「超卖」与「不超卖」"
                )
            return int(row[0]), str(row[1]), int(row[2])

        row = (await conn.execute(stmt.where(
            DeviceResource.device_status == 1,
            DeviceResource.available_count >= 2,
        ).order_by(DeviceResource.id).limit(1))).first()
        if row is None:
            raise SystemExit("库里没有 available_count >= 2 的完好设备，无法验证。")
        return int(row[0]), str(row[1]), int(row[2])


async def _pick_ids(table: str, n: int, extra_where: str = "") -> list[int]:
    """从某张表取前 n 个可用 id。"""
    sql = f"SELECT id FROM {table} WHERE status = 1 {extra_where} ORDER BY id LIMIT :n"
    async with async_engine.connect() as conn:
        rows = (await conn.execute(text(sql), {"n": n})).all()
    return [int(r[0]) for r in rows]


async def _free_window(offset_days: int) -> tuple[str, str]:
    """找一个全库都空的时段，避免撞上种子数据或历史残留。"""
    async with async_engine.connect() as conn:
        for extra in range(12):
            day = (datetime.now() + timedelta(days=offset_days + extra)).replace(
                hour=10, minute=0, second=0, microsecond=0)
            end = day + timedelta(hours=1)
            n = (await conn.execute(text(
                "SELECT COUNT(*) FROM reserve_order WHERE start_time < :e AND end_time > :s"
            ), {"s": day, "e": end})).scalar()
            if not n:
                return (day.strftime("%Y-%m-%d %H:%M:%S"),
                        end.strftime("%Y-%m-%d %H:%M:%S"))
    raise SystemExit("找不到空时段，库里的预约太密了。")


def _unlocked_stmt(device_ids: list[int]):
    """与生产实现**同一条查询**，唯独去掉 with_for_update（B 组用）。"""
    return (
        sa.select(DeviceResource)
        .where(DeviceResource.id.in_(device_ids))
        .order_by(DeviceResource.id)
    )


async def _race(*, label: str, device_id: int, window: tuple[str, str],
                spaces: list[int], users: list[int]) -> tuple[int, int, dict]:
    """
    并发抢同一台设备：每个协程用**不同场地**（避开场地锁的串行化），
    在同一时段争抢同一台设备。

    返回 (成功数, 该时段实际落库数, 拒绝原因统计)。
    """
    start, end = window
    tasks = [
        asyncio.create_task(order_service.create_order(
            user_id=users[i % len(users)],
            space_id=spaces[i],
            device_ids=[device_id],
            start_time=start,
            end_time=end,
            agent_request=f"verify_locking/{label}",
        ))
        for i in range(len(spaces))
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    succeeded = 0
    reasons: dict[str, int] = {}
    for item in results:
        if isinstance(item, Exception):
            key = "异常:" + type(item).__name__
            reasons[key] = reasons.get(key, 0) + 1
            continue
        if item.get("ok"):
            succeeded += 1
        else:
            key = str(item.get("reason"))
            reasons[key] = reasons.get(key, 0) + 1

    async with async_engine.connect() as conn:
        landed = (await conn.execute(text(
            "SELECT COUNT(*) FROM reserve_order "
            "WHERE start_time = :s AND order_status IN (1, 2)"
        ), {"s": start})).scalar()

    return succeeded, int(landed), reasons


async def _run_group(name: str, *, rounds: int, offset_base: int, device_id: int,
                     spaces: list[int], users: list[int], cap: int,
                     order_max: int, notify_max: int) -> bool:
    """跑一组对照，返回「是否出现过超卖」。"""
    oversold = False
    for rnd in range(1, rounds + 1):
        await _cleanup(order_max, notify_max)
        window = await _free_window(offset_base + rnd * 3)
        got, landed, reasons = await _race(
            label=f"{name}{rnd}", device_id=device_id, window=window,
            spaces=spaces, users=users)
        flag = "OK" if landed <= cap else "超卖"
        say(f"  第 {rnd} 轮  成功 {got}/{len(spaces)}  落库 {landed}  容量 {cap}"
            f"  [{flag}]  拒绝原因={reasons}")
        if landed > cap:
            oversold = True
    return oversold


async def main_async(args: argparse.Namespace) -> int:
    title("目标数据库")
    say("  " + settings.masked_database_url)
    say("  APP_ENV = " + str(settings.APP_ENV))

    if not _guard_environment():
        return 1

    device_id, device_name, cap = await _pick_device(args.device_id)
    users = await _pick_ids("sys_user", args.concurrency)
    spaces = await _pick_ids("space_resource", args.concurrency)
    if not users:
        raise SystemExit("库里没有启用的用户，无法下单。")
    if len(spaces) < args.concurrency:
        raise SystemExit(
            f"可用场地只有 {len(spaces)} 个，不够铺开 {args.concurrency} 个并发"
            "（同场地会先撞场地锁，测不到设备那一维）。"
        )

    order_max, notify_max = await _snapshot()
    title("实验设置")
    say(f"  争抢目标设备   id={device_id} {device_name}（available_count={cap}）")
    say(f"  每轮并发数     {args.concurrency}（各用不同场地，避开场地锁）")
    say(f"  每组轮数       {args.rounds}")
    say(f"  参与场地       {spaces}")
    say(f"  基线 id        reserve_order max={order_max}  notify_message max={notify_max}")

    original = order_service._lock_devices_stmt
    oversold_a = oversold_c = oversold_b = False
    try:
        title("A 组 · 原样（设备行锁 FOR UPDATE 在位）")
        oversold_a = await _run_group(
            "A", rounds=args.rounds, offset_base=400, device_id=device_id,
            spaces=spaces, users=users, cap=cap,
            order_max=order_max, notify_max=notify_max)

        title("B 组 · 反证（monkeypatch 去掉 with_for_update，读同一批行只是不加锁）")
        order_service._lock_devices_stmt = _unlocked_stmt
        oversold_b = await _run_group(
            "B", rounds=args.rounds, offset_base=500, device_id=device_id,
            spaces=spaces, users=users, cap=cap,
            order_max=order_max, notify_max=notify_max)

        title("C 组 · 复位（恢复原实现）")
        order_service._lock_devices_stmt = original
        oversold_c = await _run_group(
            "C", rounds=args.rounds, offset_base=600, device_id=device_id,
            spaces=spaces, users=users, cap=cap,
            order_max=order_max, notify_max=notify_max)
    finally:
        order_service._lock_devices_stmt = original
        deleted_o, deleted_n = await _cleanup(order_max, notify_max)
        title("清理")
        say(f"  删除本次新增：reserve_order {deleted_o} 行 / notify_message {deleted_n} 行")
        async with async_engine.connect() as conn:
            left = (await conn.execute(text("SELECT COUNT(*) FROM reserve_order"))).scalar()
            say(f"  reserve_order 剩余 {left} 行")
        await async_engine.dispose()

    title("结论")
    if oversold_a or oversold_c:
        fail("**设备超卖**：带锁也放行了超过 available_count 的单。")
        say("         锁的推演不成立，需要改用占用表方案 —— 别急着摘那两条 xfail。")
        return 1
    if not oversold_b:
        warn("无法得出结论：**去掉锁也没超卖**。")
        say("         本轮并发压力不足以复现竞态，只能记「当前负载下未观察到超卖」，")
        say("         **不能**据此断言锁不必要。可加大 --concurrency / --rounds 再试。")
        return 2
    ok("结论明确：带锁不超卖、去锁即超卖 —— 设备行锁确实是挡住超卖的那一环。")
    say("         与 _lock_devices_stmt 的推演一致，本结论可在云库上反复复现。")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="verify_locking.py",
        description="设备行锁的云库实测（会写库，自带清理）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--concurrency", type=int, default=6,
                        help="每轮并发协程数，默认 6（需 <= 可用场地数）")
    parser.add_argument("--rounds", type=int, default=1, help="每组轮数，默认 1")
    parser.add_argument("--device-id", type=int, default=None,
                        help="指定争抢的设备 id；默认自动挑第一台 available_count>=2 的完好设备")
    args = parser.parse_args()

    try:
        sys.exit(asyncio.run(main_async(args)))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
