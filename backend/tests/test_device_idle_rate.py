"""
二、设备闲置率（I1–I11）—— 对应 docs/test.md 第二节

口径（2026-09-27 定型）：
    分母 = SUM(device_resource.total_count)          —— 登记台数
    分子 = 窗口内 order_status IN (1,2) 的订单经 JSON_TABLE 展开后 COUNT(DISTINCT id)
（临时开关 COUNT_MODE 已删除，只剩这一套口径）

分子断言的做法：直接执行**生产的那条 SQL**（`svc._OCCUPIED_DEVICE_COUNT_SQL`），
由假会话换成 SQLite 的 json_each 等价写法在真引擎上跑。
这样 WHERE / JOIN / COUNT(DISTINCT) 的语义由数据库决定，
而不是测试自己用 Python 数一遍 —— 后者只能证明测试自己没数错。

⚠️ 期望值同时取决于「行数」和「每行 total_count」两个维度，必须与夹具一起写死，
否则用例会假失败（夹具 A / B 就是这个原因才都在）。
"""
from datetime import datetime, timedelta

from app.services import dashboard_service as svc
from tests.helpers import build_session, make_device_rows, make_order, make_order_between

DAYS = svc.DEFAULT_DAYS


# ------------------------------------------------------------
# 夹具（期望值与夹具写在同一个文件里 —— docs/test.md 0.4）
# ------------------------------------------------------------
def fixture_b():
    """夹具 B（正式口径）：15 行，每行 total_count = 1，合法 ID = {1..15}"""
    return make_device_rows(15)


def fixture_a():
    """夹具 A（量纲反例）：5 行，total_count = 4/4/3/2/2（合计 15 台）"""
    rows = make_device_rows(5)
    for row, count in zip(rows, [4, 4, 3, 2, 2]):
        row["total_count"] = count
        row["available_count"] = count
    return rows


# 三条「已确认」订单，去重后占用 {1..8} = 8 个 ID
ORDERS_FOR_EIGHT = [
    make_order(1, [1, 2, 3, 4]),
    make_order(2, [3, 4, 5, 6]),
    make_order(3, [6, 7, 8]),
]


# ------------------------------------------------------------
# 取数助手
# ------------------------------------------------------------
async def numerator(session, statuses=None, days=DAYS):
    """分子：直接跑生产 SQL（假会话把 JSON_TABLE 换成 json_each 等价写法）"""
    return (await session.execute(
        svc._OCCUPIED_DEVICE_COUNT_SQL,
        {
            "statuses": svc.DEVICE_OCCUPIED_STATUS if statuses is None else statuses,
            "since": datetime.now() - timedelta(days=days),
        },
    )).scalar()


async def idle(session, days=DAYS):
    """被测函数本身"""
    return await svc.get_device_idle_rate(session, days)


# ============================================================
# I1–I6 主用例
# ============================================================
async def test_I1_夹具B_闲置率46点7():
    """I1：分母 15、分子 8 → 46.7%"""
    session = build_session(devices=fixture_b(), orders=ORDERS_FOR_EIGHT)

    assert await numerator(session) == 8
    assert await idle(session) == 46.7


async def test_I2_夹具A_量纲反例_闲置率66点7():
    """
    I2：分母 15、分子 5 → 66.7%

    5 种设备全被借光仍显示三分之二闲置 —— 这正是**尚未解决的量纲风险**
    （每行 total_count>1 时，借走一行只计 1 台占用）。保留此用例是为了让风险可见。
    """
    session = build_session(
        devices=fixture_a(),
        orders=[make_order(1, [1, 2, 3, 4, 5])],
    )

    assert await numerator(session) == 5
    assert await idle(session) == 66.7


async def test_I3_窗口内无订单_闲置率100():
    """I3：无占用 → 100.0（是「全部闲置」，不是 0）"""
    session = build_session(devices=fixture_b(), orders=[])

    assert await numerator(session) == 0
    assert await idle(session) == 100.0


async def test_I4_全部被占用_闲置率0():
    """I4：15 台全被占用 → 0.0"""
    session = build_session(
        devices=fixture_b(),
        orders=[make_order(1, list(range(1, 16)))],
    )

    assert await numerator(session) == 15
    assert await idle(session) == 0.0


async def test_I5_设备表为空_闲置率0且只查一次():
    """I5：分母为 0 → 早退返回 0.0，且**不再发第二次查询**"""
    session = build_session(devices=[], orders=ORDERS_FOR_EIGHT)

    assert await idle(session) == 0.0
    assert len(session.executed) == 1, "分母为 0 时应当早退，不应再查分子"


async def test_I6a_脏数据ID超出设备表_被JOIN过滤():
    """
    I6a：订单引用了 device_resource 里不存在的 ID

    分子被 `JOIN device_resource` 过滤回真实存在的 15 台（不是 999），
    闲置率因而仍是 0.0，不会出现负数。
    """
    session = build_session(
        devices=fixture_b(),
        orders=[make_order(1, list(range(1, 1000)))],      # 1..999
    )

    assert await numerator(session) == 15, "不存在的设备 ID 应被 JOIN 过滤掉"
    assert await idle(session) == 0.0


async def test_I6b_分子超过分母_被min截断不为负():
    """
    I6b：`min` 兜底真的会被触发的情形

    要造出「分子 > 分母」得让某行 total_count = 0（15 行合计只有 14 台），
    此时分子 15 > 分母 14 —— 没有 min 就会算出 -7.1% 的负闲置率。
    （docs/test.md 的 I6 把这一条归因于「999 被 min 截断」，实际 999 是被 JOIN
    过滤的；min 兜底需要 total_count=0 这种脏数据才会触发。此处两条都测。）
    """
    devices = fixture_b()
    devices[0]["total_count"] = 0
    devices[0]["available_count"] = 0
    session = build_session(
        devices=devices,                                    # 合计 14 台
        orders=[make_order(1, list(range(1, 16)))],         # 占用 15 台
    )

    assert await numerator(session) == 15, "先确认分子确实超过了分母（否则这条用例证明不了 min）"
    assert await idle(session) == 0.0
    assert await idle(session) >= 0.0


# ============================================================
# I7–I11 device_ids 形态用例
# ============================================================
async def test_I7_标准数组且状态1计入占用():
    """I7：`[1, 2]`（status = 1 待确认）→ 分子 2，同时验证 status 1 计入占位"""
    session = build_session(devices=fixture_b(), orders=[make_order(1, [1, 2], status=1)])

    assert await numerator(session) == 2


async def test_I8_空数组计0():
    """I8：`[]` → 0（没借设备；不是 NULL，也不该报错）"""
    session = build_session(devices=fixture_b(), orders=[make_order(1, [])])

    assert await numerator(session) == 0


async def test_I9_NULL计0():
    """I9：`NULL` → 0（COALESCE(..., JSON_ARRAY()) 保证聚合不崩）"""
    session = build_session(devices=fixture_b(), orders=[make_order(1, None)])

    assert await numerator(session) == 0


async def test_I10_同一订单内重复ID去重():
    """I10：`[1, 1, 2]` → 2（JSON 数组不去重，靠 COUNT(DISTINCT) 兜住）"""
    session = build_session(devices=fixture_b(), orders=[make_order(1, [1, 1, 2])])

    assert await numerator(session) == 2


async def test_I11_不存在的设备ID被过滤():
    """I11：`[1, 999]` → 1（999 不在 device_resource，被 JOIN 过滤）"""
    session = build_session(devices=fixture_b(), orders=[make_order(1, [1, 999])])

    assert await numerator(session) == 1


# ============================================================
# 补充断言（docs/test.md 第二节「补充断言」）
# ============================================================
async def test_跨窗口订单不计入占用():
    """start_time 早于窗口的订单不占位，分子不变"""
    now = datetime.now()
    session = build_session(
        devices=fixture_b(),
        orders=[
            make_order(1, [1, 2]),                                          # 窗口内
            make_order_between(2, now - timedelta(days=10),
                               now - timedelta(days=10) + timedelta(hours=2),
                               device_ids=[3, 4, 5]),                       # 窗口外
        ],
    )

    assert await numerator(session) == 2


async def test_已取消与已完成都不计入设备占用():
    """status 3 已取消 / 4 已完成 → 不占位（口径 B：DEVICE_OCCUPIED_STATUS = [1, 2]）"""
    session = build_session(
        devices=fixture_b(),
        orders=[
            make_order(1, [1, 2], status=3),        # 已取消
            make_order(2, [3, 4], status=4),        # 已完成（设备已归还）
        ],
    )

    assert await numerator(session) == 0


async def test_已确认订单计入占用():
    """反向确认：status 2 已确认必须计入（避免上面两条被「全排除」蒙对）"""
    session = build_session(devices=fixture_b(), orders=[make_order(1, [1, 2], status=2)])

    assert await numerator(session) == 2
