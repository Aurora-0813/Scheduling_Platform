"""
阶段 0 数据核查脚本（只读）

用途：确认云库可连接、各表是否有种子数据、device_ids 的真实存储格式、
      device_resource 的种子结构（行数 vs total_count），
      space_resource 开放时段字段的类型与空值情况。

对应两项核查：
  - device_resource 的「行数 vs SUM(total_count)」是否相等（第 3 节）
    决定 get_device_idle_rate 已定型口径在量纲上是否自洽
  - get_space_usage_rate 的分母实算 + 哪些行走兜底（第 4 节）
    分母口径 2026-09-28 已定型为「逐行读实际时段」，本节现用于上线前核对

用法（在 backend/ 目录下执行）：
    python scripts/check_data.py

本脚本只执行 SELECT，不写入、不修改任何数据。
连不上库时给出友好提示并以退出码 1 结束，不抛异常堆栈。
"""
import asyncio
import sys
from pathlib import Path

# 允许以 `python scripts/check_data.py` 方式运行：把 backend/ 加进 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows 控制台默认 GBK，中文结论可能乱码甚至抛 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.models.reservation import ReserveOrder
from app.models.resource import DeviceResource, SpaceResource
# 分母**直接调用服务里的实现**，不在这里复刻一遍 ——
# 复刻出来的「分母」证明不了服务算得对，还会随实现悄悄漂移。
from app.services.dashboard_service import DEFAULT_DAYS, OPEN_HOURS_FALLBACK, _open_hours

# 需核查行数的表（《规范》6.3 全部 9 张）
TABLES = [
    "sys_user",
    "sys_role",
    "sys_permission",
    "space_resource",
    "device_resource",
    "reserve_order",
    "inspect_record",
    "repair_ticket",
    "notify_message",
]

SAMPLE_LIMIT = 5  # 每类样本打印条数


async def _check_counts(conn) -> None:
    """打印 9 张表的行数"""
    print("---------- 1. 各表行数 ----------")
    for table in TABLES:
        try:
            n = (await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar()
            print(f"  {table:18s} {n}")
        except Exception as e:
            # 单表查不到不影响其他表，继续核查
            print(f"  {table:18s} 查询失败: {type(e).__name__}: {str(e)[:80]}")
    print()


async def _check_device_ids(conn) -> int:
    """打印 reserve_order.device_ids 原始值，确认 JSON 存储格式。返回订单数"""
    order_count = (
        await conn.execute(select(func.count()).select_from(ReserveOrder))
    ).scalar() or 0

    print("---------- 2. reserve_order.device_ids 原始格式 ----------")
    if order_count == 0:
        print("  无数据，无法确认格式（需先导入 docs/seed.sql）\n")
        return 0

    rows = (await conn.execute(
        select(
            ReserveOrder.id,
            ReserveOrder.order_status,
            ReserveOrder.device_ids,
        )
        .order_by(ReserveOrder.id)
        .limit(SAMPLE_LIMIT)
    )).all()

    for r in rows:
        raw = r.device_ids
        # 关键信息：Python 类型的形态（list 说明驱动已反序列化，str 说明是原始 JSON）
        print(f"  id={r.id:<5} status={r.order_status}  "
              f"type={type(raw).__name__:<6} value={raw!r}")

    print(f"\n  小结：device_ids 的 Python 类型为 "
          f"{type(rows[0].device_ids).__name__}")
    print("  期望值是 list（JSON 数组 of int，贾世杰 2026-09-27 确认）。")
    print("  若出现 str / dict 等其他形态，说明与确认结果不符，")
    print("  需回头核对，因为 get_device_idle_rate 现已在 SQL 层用")
    print("  JSON_TABLE 展开该列，不再有 Python 层的兼容分支。\n")
    return order_count


async def _check_device_seed(conn) -> None:
    """打印 device_resource 的 id / total_count，确认种子结构"""
    row_count = (
        await conn.execute(select(func.count()).select_from(DeviceResource))
    ).scalar() or 0

    total_units = (
        await conn.execute(select(func.coalesce(func.sum(DeviceResource.total_count), 0)))
    ).scalar() or 0

    print("---------- 3. device_resource 种子结构 ----------")
    if row_count == 0:
        print("  无数据，无法确认结构（需先导入 docs/seed.sql）\n")
        return

    rows = (await conn.execute(
        select(
            DeviceResource.id,
            DeviceResource.device_name,
            DeviceResource.device_type,
            DeviceResource.device_status,
            DeviceResource.total_count,
            DeviceResource.available_count,
        )
        .order_by(DeviceResource.id)
        .limit(SAMPLE_LIMIT)
    )).all()

    print(f"  {'id':<6}{'设备名':<16}{'类型':<12}{'状态':<6}{'总数':<6}{'可用'}")
    for r in rows:
        print(f"  {r.id:<6}{str(r.device_name):<16}{str(r.device_type):<12}"
              f"{r.device_status:<6}{r.total_count:<6}{r.available_count}")

    print(f"\n  设备行数 COUNT = {row_count}")
    print(f"  台数合计 SUM(total_count) = {total_units}")

    print("\n  >>> 量纲判定（决定已定型口径是否自洽）<<<")
    if row_count == total_units:
        print("  两者相等 → 每行 total_count 均为 1。")
        print("  get_device_idle_rate 的分母（SUM 台数）与分子（去重 ID 数）同量纲，口径自洽。")
    else:
        print("  两者不等 → 存在「一行多台」的设备，分子分母量纲不一致！")
        print(f"  平均每行 {total_units / row_count:.2f} 台；"
              "借走一行只会计 1 台占用，占用被低估，")
        print("  闲置率因而偏高 —— 演示前必须重新讨论分子口径。另见开发计划 P1-3。")
    print()


async def _check_space_open_time(conn) -> None:
    """
    打印 space_resource 的开放时段，并**按服务的真实算法算出分母**。

    《规范》6.7 的 DDL 只对 open_time 非空的行回填了开放时段：
        UPDATE space_resource SET open_start_time='08:00:00', ... WHERE open_time IS NOT NULL;
    2026-09-28 真库实测：8 个可用场地**无一行 NULL**，但有三种时段
    （06:00-23:00 / 08:00-22:00 / 09:00-21:00），合计 111 h/天。
    分母据此改为**逐行**累加实际时段（原 P2 待办已关闭），
    缺失（NULL）或异常（`end <= start`）才用 OPEN_HOURS_FALLBACK = 14 兜底。

    于是本节的作用从「要不要改分母」变成两个**上线前的核对点**：
      1. 分母到底是多少 —— 照服务算法实算，不在这里另写一份
      2. **哪些行走的是兜底** —— 走兜底意味着该场地时段缺失或填反，
         是脏数据信号而非正常情况；真库当前应为 0 条
    """
    row_count = (
        await conn.execute(select(func.count()).select_from(SpaceResource))
    ).scalar() or 0

    print("---------- 4. space_resource 开放时段 ----------")
    if row_count == 0:
        print("  无数据，无法确认（需先导入 docs/seed.sql）\n")
        return

    rows = (await conn.execute(
        select(
            SpaceResource.id,
            SpaceResource.space_name,
            SpaceResource.capacity,
            SpaceResource.status,
            SpaceResource.open_start_time,
            SpaceResource.open_end_time,
        )
        .order_by(SpaceResource.id)
        .limit(SAMPLE_LIMIT)
    )).all()

    print(f"  {'id':<5}{'空间名':<20}{'容量':<6}{'状态':<6}"
          f"{'open_start':<13}{'open_end':<13}")
    for r in rows:
        print(f"  {r.id:<5}{str(r.space_name):<20}{r.capacity:<6}{r.status:<6}"
              f"{str(r.open_start_time):<13}{str(r.open_end_time):<13}")

    # 类型区分：datetime.time / str / None 三者要分开看
    print(f"\n  前 5 条 Python 类型："
          f"open_start_time={type(rows[0].open_start_time).__name__}  "
          f"open_end_time={type(rows[0].open_end_time).__name__}")

    # 全表统计（比只看前 5 条可靠）：类型集合 + NULL 数 + 分母实算
    all_rows = (await conn.execute(
        select(
            SpaceResource.id,
            SpaceResource.space_name,
            SpaceResource.status,
            SpaceResource.open_start_time,
            SpaceResource.open_end_time,
        ).order_by(SpaceResource.id)
    )).all()

    types_start = {type(r.open_start_time).__name__ for r in all_rows}
    types_end = {type(r.open_end_time).__name__ for r in all_rows}
    null_start = sum(1 for r in all_rows if r.open_start_time is None)
    null_end = sum(1 for r in all_rows if r.open_end_time is None)

    print(f"\n  全表 {row_count} 条的分布：")
    print(f"    open_start_time  类型集合 = {sorted(types_start)}   NULL 数 = {null_start}")
    print(f"    open_end_time    类型集合 = {sorted(types_end)}   NULL 数 = {null_end}")

    # 类型核对**必须在实算之前**：`_open_hours` 做的是 `end.hour - start.hour`，
    # 值若是 str 会直接 AttributeError。诊断脚本的职责是报告，不是崩掉 ——
    # 所以类型不对就先说清楚、**不往下算**（C 用例锁的就是这条）。
    non_null_types = (types_start | types_end) - {"NoneType"}
    if non_null_types and non_null_types != {"time"}:
        print(f"\n  ⚠️ 非空值类型不全是 datetime.time（实际 {sorted(non_null_types)}）")
        print("     → 先不实算分母。需确认驱动返回形式并统一解析后再看。\n")
        return

    if not non_null_types:
        print("\n  该字段全部为 NULL → 分母只能全部走兜底。")

    # NULL 行的处置（2026-09-27 决策：兜底，不当作「不可用」排除）
    if null_start or null_end:
        print(f"  存在 NULL 行（start {null_start} 条 / end {null_end} 条）"
              f"→ 按兜底 {OPEN_HOURS_FALLBACK}h/天 计，不作为「不可用」排除。")
    else:
        print("  无 NULL 行 → 分母可完全按各场地实际开放时段累加。")

    if non_null_types:
        print("  非空值类型均为 datetime.time → 直接做时间减法取时长，无需解析字符串。")

    # ---------- 分母：调服务的实现实算 ----------
    available = [r for r in all_rows if r.status == 1]
    if not available:
        print("\n  >>> 分母 <<<")
        print("  没有 status=1 的可用场地 → get_space_usage_rate 早退返回 0.0。")
        print("  这是设计行为（分母为 0 不得 ZeroDivisionError），不是故障。\n")
        return

    print(f"\n  >>> get_space_usage_rate 的分母（调 _open_hours 实算；"
          f"可用场地 {len(available)}/{row_count} 个）<<<")

    hours_per_day = 0.0
    fallback_rows = []
    for r in available:
        # 兜底判据与 `_open_hours` 内部一致：时段缺失，或 end <= start（填反/跨天）。
        # 之所以要在这里复刻这两行，是因为 `_open_hours` 只回数值、
        # 不告诉调用方「这个数是不是兜底来的」——而 14h 也可能是真实时段
        # （08:00-22:00），光比数值分不出来。服务若改判据，这里要跟着改。
        missing = r.open_start_time is None or r.open_end_time is None
        reversed_span = (
            not missing and r.open_end_time <= r.open_start_time
        )
        used_fallback = missing or reversed_span

        hours = _open_hours(r.open_start_time, r.open_end_time)
        hours_per_day += hours

        reason = ""
        if missing:
            reason = "  ← 兜底：时段为 NULL"
        elif reversed_span:
            reason = "  ← 兜底：end <= start"
        if used_fallback:
            fallback_rows.append(r)

        print(f"    id={r.id:<4}{str(r.space_name):<18}"
              f"{str(r.open_start_time):<9}→ {str(r.open_end_time):<9}"
              f"{hours:>5.1f} h/天{reason}")

    print(f"\n    合计 {hours_per_day:.1f} h/天   ×{DEFAULT_DAYS} 天 = "
          f"{hours_per_day * DEFAULT_DAYS:.1f} h")

    if fallback_rows:
        print(f"\n  ⚠️ {len(fallback_rows)} 条走的是兜底 OPEN_HOURS_FALLBACK = "
              f"{OPEN_HOURS_FALLBACK}h —— 该场地时段缺失或 end <= start。")
        print("     这会让分母偏离真实容量（且不报错，只是数字静静地偏），请核对原始数据：")
        for r in fallback_rows:
            print(f"       id={r.id} {r.space_name}  "
                  f"open_start={r.open_start_time}  open_end={r.open_end_time}")
    else:
        print("\n  可用场地时段齐全且 end > start → 分母全部由真实时段累加，无兜底行。")
    print()


async def main() -> int:
    print("=" * 60)
    print("阶段 0 数据核查（只读）")
    print("=" * 60)
    print(f"连接目标：{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}  "
          f"用户={settings.DB_USER}\n")

    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            print("[连接成功]\n")
            await _check_counts(conn)
            order_count = await _check_device_ids(conn)
            await _check_device_seed(conn)
            await _check_space_open_time(conn)

        print("=" * 60)
        if order_count == 0:
            print("结论：库能连上，但没有预约数据 —— 看板会全为 0，")
            print("      演示前需要集成组执行 docs/seed.sql。")
        else:
            print("结论：核查完成。第 3 节的量纲判定若为「两者不等」，")
            print("      请告知，需重新讨论 get_device_idle_rate 的分子口径。")
        print("=" * 60)
        return 0

    except Exception as e:
        # 连不上是阶段 0 的预期状态，给排查提示而不是堆栈
        print("[连接失败]")
        print(f"  错误类型：{type(e).__name__}")
        print(f"  错误信息：{str(e)[:300]}")
        print()
        print("  排查方向：")
        print("    1. SSH 隧道是否已启动（当前指向 127.0.0.1，需本地端口转发）")
        print("    2. 或改用云库公网 IP + 确认本机 IP 已在白名单内")
        print("    3. 核对 .env 中 DB_HOST / DB_PORT / DB_USER / DB_PASSWORD")
        print()
        print("  隧道通了之后重新执行本脚本即可。")
        return 1

    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
