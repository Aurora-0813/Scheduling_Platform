"""
七、高峰时段与故障频次（S1–S8）—— 对应 docs/test.md 第七节

四项统计里，场地使用率（U 组）与设备闲置率（I 组）原本已有用例，
**高峰时段与故障频次此前没有任何直接用例** —— 覆盖率报告里
`dashboard_service.py` 缺的那两段就是这两个函数。本文件补上。

⚠️ **稀疏 vs 补齐 的契约（S2，重要）**
一度以为后端会把缺数据的小时补成 0、返回完整的 0–23。
实测**不是**：`get_peak_hours` 只返回**有预约的小时**，按 count 降序
（与 docs/api-dashboard.md 的响应示例 `"peakHours": [{"hour": 14, "count": 5}]` 一致）。

「补齐 0–23 点」是**前端职责**，已实现在
`frontend/src/components/dashboard/PeakHoursBarChart.vue` 的 `toFullDaySeries()`。

为什么不把补齐挪到后端：`peakHours` 的契约是「按 count 降序」，
而一个补齐的 24 元素数组按小时排列，与「降序」自相矛盾；
且它会让响应体从 1 个元素涨到 24 个（其中 20 个是 0）。
故本组按**稀疏**契约断言，S2 的用例名即为此而写。
"""
from datetime import datetime, timedelta

from app.services import dashboard_service as svc
from tests.helpers import build_session, make_device_rows, make_order_between, make_ticket

DAYS = svc.DEFAULT_DAYS


# ------------------------------------------------------------
# 夹具助手
# ------------------------------------------------------------
def order_at(hour, order_id=1, status=2, days_ago=1):
    """
    造一条**开始时间恰为指定小时**的订单（窗口内）。

    用 `replace(hour=...)` 而不是相对偏移，让断言里的小时值可预期 ——
    相对偏移算出来的小时会随跑测试的时刻变化，导致用例白天绿、半夜红。
    """
    start = (datetime.now() - timedelta(days=days_ago)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    return make_order_between(order_id, start, start + timedelta(hours=1), status=status)


def hours_of(peak_hours):
    return [item["hour"] for item in peak_hours]


def counts_of(fault_frequency):
    return [item["count"] for item in fault_frequency]


# ============================================================
# S1–S4：get_peak_hours
# ============================================================
async def test_S1_状态口径只统计1_2_4():
    """
    S1：状态口径 = `SPACE_OCCUPIED_STATUS = [1, 2, 4]`（与场地使用率同口径）。

    理由：高峰时段反映的是**预约活动热度**，已完成的预约也是真实发生过的活动；
    换用别的口径会让「使用率图」和「高峰图」互相矛盾。
    这里放 status 3（已取消）与 0 做反向锁 —— 防止口径被放宽成「全部状态」。
    """
    session = build_session(
        devices=make_device_rows(3),
        orders=[
            order_at(9, order_id=1, status=1),     # 待确认 → 计入
            order_at(10, order_id=2, status=2),    # 已确认 → 计入
            order_at(11, order_id=3, status=4),    # 已完成 → 计入
            order_at(12, order_id=4, status=3),    # 已取消 → **不计入**
            order_at(13, order_id=5, status=0),    # 其他   → **不计入**
        ],
    )

    peak = await svc.get_peak_hours(session, DAYS)

    assert sorted(hours_of(peak)) == [9, 10, 11]
    assert 12 not in hours_of(peak), "已取消(3)的订单不得计入高峰"
    assert 13 not in hours_of(peak), "状态 0 的订单不得计入高峰"


async def test_S2_返回稀疏数组_缺数据的小时不补0():
    """
    S2：只返回**有预约的小时**；缺数据的小时**不出现**在数组里。

    这不是缺陷，是契约（见文件头）。「补齐 0–23 点」由前端
    `PeakHoursBarChart.vue` 负责，pytest 侧不重复断言那条 ——
    把补齐搬到后端会与「按 count 降序」的契约冲突。
    """
    session = build_session(
        devices=make_device_rows(3),
        orders=[order_at(3, order_id=1), order_at(20, order_id=2)],
    )

    peak = await svc.get_peak_hours(session, DAYS)

    assert sorted(hours_of(peak)) == [3, 20]
    assert len(peak) == 2, "缺数据的小时不应被补成 0（那是前端的职责）"
    assert all(item["hour"] in range(24) for item in peak), "小时必须在 0-23 内"


async def test_S3_count降序():
    """S3：按 count 降序 —— 前端因此可以直接取 [0] 当峰值，不必自己排序"""
    session = build_session(
        devices=make_device_rows(3),
        orders=[
            order_at(8, order_id=1), order_at(8, order_id=2), order_at(8, order_id=3),
            order_at(9, order_id=4), order_at(9, order_id=5),
            order_at(10, order_id=6),
        ],
    )

    peak = await svc.get_peak_hours(session, DAYS)

    assert hours_of(peak) == [8, 9, 10]
    assert counts_of(peak) == [3, 2, 1], "必须降序"


async def test_S4_窗口外订单与无订单都返回空数组():
    """S4：窗口外订单不计入；一条订单都没有时返回 `[]`（不是报错、不是 None）"""
    out_of_window = build_session(
        devices=make_device_rows(3),
        orders=[order_at(14, order_id=1, days_ago=10)],       # 10 天前，窗口是 7 天
    )
    empty = build_session(devices=make_device_rows(3), orders=[])

    assert await svc.get_peak_hours(out_of_window, DAYS) == []
    assert await svc.get_peak_hours(empty, DAYS) == []


async def test_S5_高峰取开始时间而不是结束时间():
    """
    S5：小时取自 `start_time`。

    一条 23:00 开始、次日 01:00 结束的订单，高峰应记在 **23 点**。
    若实现改成 `func.hour(end_time)`，跨零点的订单会被记到第二天凌晨 ——
    而这个改动在别的用例下都看不出来，故单列一条。
    """
    start = (datetime.now() - timedelta(days=1)).replace(
        hour=23, minute=0, second=0, microsecond=0
    )
    session = build_session(
        devices=make_device_rows(3),
        orders=[make_order_between(1, start, start + timedelta(hours=2), status=2)],
    )

    peak = await svc.get_peak_hours(session, DAYS)

    assert hours_of(peak) == [23], "小时必须取 start_time，不是 end_time"


# ============================================================
# S6–S9：get_fault_frequency
# ============================================================
async def test_S6_超过10台设备时只返回前10():
    """S6：`limit` 默认 10 → 12 台都有工单时只返回 10 条（Top 10 截断）"""
    devices = make_device_rows(12)
    tickets = [make_ticket(i, device_id=i) for i in range(1, 13)]
    session = build_session(devices=devices, tickets=tickets)

    result = await svc.get_fault_frequency(session, 10)

    assert len(result) == 10
    assert len(result) < 12, "截断真的发生了（否则这条用例证明不了 Top 10）"


async def test_S7_count降序且最多的排最前():
    """S7：按工单数降序；并列时顺序不限（这里只断言 count 序列）"""
    devices = make_device_rows(3)
    tickets = (
        [make_ticket(1, device_id=1), make_ticket(2, device_id=1), make_ticket(3, device_id=1)]
        + [make_ticket(4, device_id=2), make_ticket(5, device_id=2)]
        + [make_ticket(6, device_id=3)]
    )
    session = build_session(devices=devices, tickets=tickets)

    result = await svc.get_fault_frequency(session, 10)

    assert counts_of(result) == [3, 2, 1]
    assert result[0]["deviceName"] == "设备1"


async def test_S8_无工单时返回空数组():
    """S8：窗口内一张维修工单都没有 → `[]`（前端据此显示「暂无维修工单」）"""
    session = build_session(devices=make_device_rows(3), tickets=[])

    assert await svc.get_fault_frequency(session, 10) == []


async def test_S9_工单指向不存在的设备被JOIN过滤():
    """
    S9：`repair_ticket.device_id` 指向已不存在的设备 → 不出现在结果里。

    `get_fault_frequency` 用 INNER JOIN `device_resource`，
    因此拿不到设备名的工单会被丢掉 —— 不会出现 `deviceName: None` 的行。
    """
    session = build_session(
        devices=[],
        tickets=[make_ticket(1, device_id=99)],       # 设备 99 不存在
    )

    assert await svc.get_fault_frequency(session, 10) == []
