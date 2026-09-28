"""
九、聚合入口 `get_all_stats`（G1–G2）

**为什么单列一个文件**：U / I / S 三组测的是四个统计函数**各自**的行为，
C / E / D 组则一律把 `get_all_stats` 换成桩 —— 而桩返回的正是「正确的那份 dict」。
于是出现一个盲点：**谁把聚合入口里的 key 改名或漏掉一项，全部用例照样绿**，
因为没有任何一条用例真的进过这个函数（覆盖率报告里它就一直是那 1 行未覆盖）。

本文件用内存库跑**真实**的聚合路径，补上这个盲点。
"""
from datetime import datetime, timedelta

from app.services import dashboard_service as svc
from tests.helpers import build_session, make_device_rows, make_order_between, make_space, make_ticket

DAYS = svc.DEFAULT_DAYS

# 与 docs/api-dashboard.md / schemas.dashboard.DashboardStatsData 一致的四项
EXPECTED_KEYS = ["spaceUsageRate", "deviceIdleRate", "peakHours", "faultFrequency"]


def _session_with_data():
    """一份「四项都算得出非空结果」的数据，避免 0 值让断言失去区分度"""
    start = (datetime.now() - timedelta(days=1)).replace(
        hour=14, minute=0, second=0, microsecond=0
    )
    return build_session(
        devices=make_device_rows(3),
        spaces=[make_space(1)],
        orders=[make_order_between(1, start, start + timedelta(hours=2), status=2)],
        tickets=[make_ticket(1, device_id=1)],
    )


async def test_G1_聚合入口返回四项且key与契约一致():
    """
    G1：`get_all_stats` 返回的 dict **恰好**是契约里的四个 key，顺序也一致。

    顺序一并断言：`/stats` 的响应体顺序由它决定（C1 锁的是 HTTP 层，
    这里锁的是**源头** —— 真出问题时这条能直接指向聚合入口，不用一路往下查）。
    """
    stats = await svc.get_all_stats(_session_with_data(), DAYS)

    assert list(stats.keys()) == EXPECTED_KEYS


async def test_G3_降级占位与正常聚合的key完全一致():
    """
    G3：`empty_stats()` 的 key **逐字等于** `get_all_stats()` 的 key。

    这条锁的是 2026-09-28 新增的 `/stats` 库不可达兜底：降级时前端拿到的
    data 结构**不能变**，否则它得为降级写第二套解析。
    两处 key 分别在两个函数里手写，最容易漂移 —— 比如给正常路径加了第五项
    统计却忘了给占位也加，那时前端在降级时读到 `undefined`，比 500 更难查。

    刻意**比较 key 而不是值**：值的类型差异是必然的（0.0 vs 真实数字），
    形状一致才是契约。
    """
    real_keys = (await svc.get_all_stats(_session_with_data(), DAYS)).keys()
    assert list(svc.empty_stats().keys()) == list(real_keys)


async def test_G2_聚合入口各项形状正确且与单独调用一致():
    """
    G2：聚合结果与**逐个调用**四个函数的结果一致，且类型/形状正确。

    这条防的是「聚合时顺手做了额外加工」——
    比如把 `spaceUsageRate` 又 round 一次、或把 `peakHours` 截断到 5 条。
    那样 `/stats` 和「单独调 `get_peak_hours`」就会给前端两个不同的答案。
    """
    session = _session_with_data()
    stats = await svc.get_all_stats(session, DAYS)

    assert stats["spaceUsageRate"] == await svc.get_space_usage_rate(session, DAYS)
    assert stats["deviceIdleRate"] == await svc.get_device_idle_rate(session, DAYS)
    assert stats["peakHours"] == await svc.get_peak_hours(session, DAYS)
    assert stats["faultFrequency"] == await svc.get_fault_frequency(session, 10)

    assert isinstance(stats["spaceUsageRate"], float)
    assert isinstance(stats["deviceIdleRate"], float)
    assert isinstance(stats["peakHours"], list)
    assert isinstance(stats["faultFrequency"], list)

    # days 真的透传到下游（不是被聚合入口吞掉、各函数偷偷用默认值）。
    # 实测差异只出现在 spaceUsageRate（分母 7×14h vs 30×14h → 2.0 vs 0.5）；
    # 这里的 14h 走的是**兜底**路径 —— `make_space(1)` 的开放时段是 NULL
    # （2026-09-28 起分母逐行读实际时段，不再是恒定 14h）。
    # peakHours / faultFrequency 在 7 天与 30 天窗口下相同，因为夹具那条数据
    # 两个窗口都落在里面。所以这条只证明 days 抵达了**使用率**那一项 ——
    # 另外三项各自的 days 透传由 U / I / S 组的用例负责，不靠这条兜。
    assert await svc.get_all_stats(session, 30) != stats, \
        "窗口天数应影响结果；两者相等说明 days 没有传到 get_space_usage_rate"
