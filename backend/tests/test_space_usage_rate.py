"""
三、场地使用率（U1–U11）—— 对应 docs/test.md 第三节

口径：`SPACE_OCCUPIED_STATUS = [1, 2, 4]`（待确认 + 已确认 + 已完成；已取消 3 排除）。
2026-09-27 定案 —— 旧实现是 `[2, 4]`，**漏了状态 1，会低估使用率**。

**分母（2026-09-28 定型，原 P2 待办已关闭）**：逐行读 `space_resource` 的
`open_start_time` / `open_end_time` 累加；时段缺失（NULL）或异常（`end <= start`）
才用 `OPEN_HOURS_FALLBACK = 14` 兜底。八条原有用例**全部可断言，无 skip**。

真库实测分布（2026-09-28 查得：8 个可用场地、无一行 NULL）：
    1× 户外场地 06:00-23:00 = 17h
    5× 会议室+多功能厅 08:00-22:00 = 14h
    2× 展厅 09:00-21:00 = 12h
    → 合计 111 h/天

**U9 按这个真实分布写** —— 它是唯一一条按真库形状锁分母的用例：
谁把实现改回「恒定 14h」，它会立刻失败（112×7 = 784 → 19.8% ≠ 20.0%）。
"""
from datetime import datetime, timedelta, time

import pytest

from app.services import dashboard_service as svc
from tests.helpers import build_session, make_order_between, make_space

DAYS = svc.DEFAULT_DAYS
SPACES_WITH_NULL_OPEN_TIME = 2                 # 「同 U3」的口径：2 个场地、开放时段均为 NULL
DENOMINATOR_196 = SPACES_WITH_NULL_OPEN_TIME * svc.OPEN_HOURS_FALLBACK * DAYS


# ------------------------------------------------------------
# 夹具助手
# ------------------------------------------------------------
def two_spaces_null_open_time():
    """U3 / U5–U8 的场地构造：2 个场地均可用，开放时段为 NULL → 各按 14h 兜底"""
    return [make_space(1), make_space(2)]


def order_with_hours(order_id, hours, status=2):
    """一条时长恰为 hours 的订单，起始时间落在窗口内"""
    end = datetime.now() - timedelta(hours=1)
    return make_order_between(
        order_id, end - timedelta(seconds=round(hours * 3600)), end, status=status
    )


def orders_totaling(total_hours, parts, status=2):
    """
    造 parts 条互相重叠的订单，总时长恰为 total_hours。

    用于 U5 的「脏数据注入」：单条订单在 7 天窗口内最多 168h，
    要超过 196h 的分母只能靠多条累加。
    """
    start = datetime.now() - timedelta(hours=96)
    each = total_hours / parts
    return [
        make_order_between(i + 1, start, start + timedelta(seconds=round(each * 3600)),
                           status=status)
        for i in range(parts)
    ]


async def usage(session, days=DAYS):
    return await svc.get_space_usage_rate(session, days)


# ============================================================
# U3 / U5–U8：现在可断言
# ============================================================
async def test_U3_两场地均为空时段的基线_20点0():
    """U3：2 个场地、开放时段均 NULL → 分母 (14+14)×7 = 196，分子 39.2h → 20.0%"""
    assert DENOMINATOR_196 == 196
    session = build_session(
        spaces=two_spaces_null_open_time(),
        orders=[order_with_hours(1, 39.2)],
    )

    assert await usage(session, DAYS) == 20.0


async def test_U5_分子超过分母被截断为100():
    """U5：分子注入 300h（超过分母 196h）→ 100.0，不得出现 153.1%"""
    session = build_session(
        spaces=two_spaces_null_open_time(),
        orders=orders_totaling(300, parts=3),
    )

    result = await usage(session, DAYS)

    assert result == 100.0
    assert result <= 100.0


async def test_U6_窗口内无有效订单_0点0():
    """U6：窗口内没有 [1,2,4] 状态的订单 → 0.0%"""
    session = build_session(spaces=two_spaces_null_open_time(), orders=[])

    assert await usage(session, DAYS) == 0.0


async def test_U7_只有待确认订单也必须计入_20点0():
    """
    U7：口径修正的回归用例。

    同一条 39.2h 的**待确认**(status=1) 订单：
        旧口径 [2,4] → 0.0%
        新口径 [1,2,4] → 20.0%
    断言本条即锁住「状态 1 必须计入」。
    """
    session = build_session(
        spaces=two_spaces_null_open_time(),
        orders=[order_with_hours(1, 39.2, status=1)],
    )

    assert await usage(session, DAYS) == 20.0


async def test_U8_只有已取消订单不得计入_0点0():
    """
    U8：反向锁。

    证明口径放宽到 [1,2,4] 时状态 3 仍被排除，
    而不是简单地把所有状态都放进来。
    """
    session = build_session(
        spaces=two_spaces_null_open_time(),
        orders=[order_with_hours(1, 39.2, status=3)],
    )

    assert await usage(session, DAYS) == 0.0


async def test_场地不可用时不计入分母():
    """status = 0 停用的场地不进分母（现状已实现，顺手锁住）"""
    spaces = two_spaces_null_open_time()
    spaces.append(make_space(3, status=0))
    session = build_session(spaces=spaces, orders=[order_with_hours(1, 39.2)])

    assert await usage(session, DAYS) == 20.0        # 分母仍是 196，不是 294


async def test_无可用场地时返回0点0():
    """全部场地停用 → 分母为 0，早退返回 0.0（不得 ZeroDivisionError）"""
    session = build_session(
        spaces=[make_space(1, status=0)],
        orders=[order_with_hours(1, 39.2)],
    )

    assert await usage(session, DAYS) == 0.0


# ============================================================
# U1 / U2 / U4：逐行读实际开放时段（2026-09-28 解禁 skip）
# ============================================================
# 这三条原本标 skip，理由是「分母仍硬编码 14h，跑起来必然失败」。
# 分母口径定型后（逐行累加 + NULL 兜底）**删掉 skip，断言体一字未动**
# —— 当初就是照「P2 落地后能用」写的。解禁的实际结果分两种：
#
#     U1 / U2  直接通过 —— 它们只依赖分母，分母修对了就成立
#     U4       失败 20.7 ≠ 20.0 —— 暴露出**第二个、独立的缺口**
#              （分子的场地过滤，详见 U4 上方的 xfail 理由）
#
# 定型前的失败值留档（恒定 14h：分母 = 可用场地数 × 14 × 7 = 294）：
#     U1  期望 20.0 → 16.2   (47.6 / 294)
#     U2  期望 20.0 → 18.6   (54.6 / 294)
#     U4  期望 20.0 → 19.3   (56.6 / 294 —— 分子里含停用场地那 2h)
# 都偏低，因为 9h/16h 的场地被按 14h 算了 —— 分母偏大，使用率被低估。
#
# ⚠️ U4 值得单独记一笔：**skip 掩盖的不只是它标称的那个问题**。
# 它造了一条挂在停用场地上的订单，而这条断言从未被执行过，
# 于是「分子算不算停用场地的订单」这个分母/分子口径不一致一直没人发现。

async def test_U1_三个场地各自开放时段_20点0():
    """
    U1：A 09:00–18:00(9h)、B 08:30–17:30(9h)、C 06:00–22:00(16h)
    分母 (9+9+16)×7 = 238，分子 47.6h → 20.0%
    """
    spaces = [
        make_space(1, open_start=time(9, 0), open_end=time(18, 0)),
        make_space(2, open_start=time(8, 30), open_end=time(17, 30)),
        make_space(3, open_start=time(6, 0), open_end=time(22, 0)),
    ]
    session = build_session(spaces=spaces, orders=orders_totaling(47.6, parts=2))

    assert await usage(session, DAYS) == 20.0


async def test_U2_含空时段场地按14h兜底_20点0():
    """
    U2：A 09:00–18:00(9h)、B NULL→14h、C 06:00–22:00(16h)
    分母 (9+14+16)×7 = 273，分子 54.6h → 20.0%

    注意 NULL 是**按行**兜底，不是全局二选一。
    """
    spaces = [
        make_space(1, open_start=time(9, 0), open_end=time(18, 0)),
        make_space(2),                                      # 开放时段为 NULL → 14h
        make_space(3, open_start=time(6, 0), open_end=time(22, 0)),
    ]
    session = build_session(spaces=spaces, orders=orders_totaling(54.6, parts=2))

    assert await usage(session, DAYS) == 20.0


@pytest.mark.xfail(
    strict=True,
    reason=(
        "已知缺口（2026-09-28 解禁 skip 时发现）：分子没按场地状态过滤。"
        "分母只累加 status=1 的场地容量（273h），分子却把挂在停用场地上那 2h 也算了进去 "
        "→ 56.6/273 = 20.7%，而本用例要求 20.0%。两侧口径不一致："
        "**算一个不存在的容量上的占用**。"
        "真库当前 8 个场地全是 status=1，所以**现在影响为 0**；"
        "一旦有场地停用（维修、闭馆），使用率会被虚高，且不报错。"
        "修法：分子查询 JOIN space_resource 并加 `SpaceResource.status == 1`，"
        "与分母取同一个场地集合（已在内存 SQLite 上验证：JOIN 后 2 条 54.6h → 20.0%）。"
        "strict=True 的用意：谁修好了这条会 XPASS 报错，逼着把本标记摘掉、"
        "让 U4 变回一条正常的绿色断言 —— 而不是被静悄悄放过。"
    ),
)
async def test_U4_停用场地的订单不得计入分子_20点0():
    """
    U4：4 个场地，其中 1 个 status=0 停用；有效 3 个同 U2
    分母 273，分子 54.6h（**停用场地的订单不得计入分子**）→ 20.0%

    当前实测 20.7%（= 56.6/273）—— 分子多算了停用场地那 2h，见上方 xfail 理由。
    """
    spaces = [
        make_space(1, open_start=time(9, 0), open_end=time(18, 0)),
        make_space(2),
        make_space(3, open_start=time(6, 0), open_end=time(22, 0)),
        make_space(4, status=0, open_start=time(8, 0), open_end=time(20, 0)),
    ]
    orders = orders_totaling(54.6, parts=2, status=2)
    orders.append(make_order_between(99, datetime.now() - timedelta(hours=3),
                                     datetime.now() - timedelta(hours=1),
                                     status=2, space_id=4))       # 停用场地上的订单
    session = build_session(spaces=spaces, orders=orders)

    assert await usage(session, DAYS) == 20.0


# ============================================================
# U9–U10：分母口径定型后新增（真库分布 / 异常时段兜底）
# ============================================================
async def test_U9_真库分布三类场地逐行累加_20点0():
    """
    U9：按**真库实测分布**（2026-09-28 查询）造 8 个可用场地，全部非 NULL：

        1× 户外场地   06:00-23:00 = 17h
        5× 会议室/多功能厅 08:00-22:00 = 14h
        2× 展厅       09:00-21:00 = 12h
        分母 = (17 + 70 + 24) × 7 = 777，分子 155.4h → 20.0%

    **这条是分母口径的终态锁**：唯一一条按真库形状写的用例。
    谁把实现改回「恒定 14h」，分母会变成 8×14×7 = 784 → 155.4/784 = 19.8%，
    立刻失败并指向这里 —— 而固定 10h 那种改法（8×10×7=560）会算出 27.8%，
    偏得更远。
    """
    spaces = [make_space(1, open_start=time(6, 0), open_end=time(23, 0))]
    spaces += [make_space(i, open_start=time(8, 0), open_end=time(22, 0))
               for i in range(2, 7)]                                  # 5 个会议室/多功能厅
    spaces += [make_space(i, open_start=time(9, 0), open_end=time(21, 0))
               for i in range(7, 9)]                                  # 2 个展厅

    session = build_session(spaces=spaces, orders=orders_totaling(155.4, parts=2))

    assert await usage(session, DAYS) == 20.0


async def test_U10_开放时段异常时按兜底不猜跨天_20点0():
    """
    U10：`end <= start` 的两类情形（跨天营业 / 字段填反）**不猜跨天**，按兜底 14h。

        场地1  22:00 → 06:00   填反或跨天 → 无法区分 → 兜底 14h
        场地2  09:00 → 21:00   正常 → 12h
        分母 = (14 + 12) × 7 = 182，分子 36.4h → 20.0%

    锁的是「不写 `+24h` 跨天分支」这个有意决定（真库三种时段都不跨零点）。
    若哪天有人加了跨天支持，场地1 会算成 8h，分母变 140 → 26.0%，这条会失败并
    指向这里 —— 那时应先在业务上确认跨天场地的语义，再决定是改代码还是改这条。
    """
    spaces = [
        make_space(1, open_start=time(22, 0), open_end=time(6, 0)),
        make_space(2, open_start=time(9, 0), open_end=time(21, 0)),
    ]
    session = build_session(spaces=spaces, orders=orders_totaling(36.4, parts=2))

    assert await usage(session, DAYS) == 20.0


# ============================================================
# U11：脏数据下界（2026-09-28 补，与 A.1 的 /stats 兜底同批）
# ============================================================
async def test_U11_脏数据end小于start不得算出负值_20点0():
    """
    U11：一条 `end_time < start_time` 的脏订单不得把分子拉成负数。

        场地：2 个（开放时段 NULL → 各 14h 兜底），分母 196
        订单：39.2h 正常 + 一条填反的（start 1h 前、end 100h 前，时长 -99h）
        期望：分子只算 39.2h → **20.0%**（脏数据按 0 计）

    **为什么这条不能省**：`reserve_order` 的 start/end 只有 NOT NULL，
    **没有 CHECK 约束保证 `end > start`**。补这个下界之前实测过 ——
    就是这样一条脏数据让使用率算成 **-30.5%**，而
    `DashboardStatsData.space_usage_rate` 是 `ge=0`，于是 FastAPI 响应校验失败，
    **`/stats` 直接返回 500**，整个看板挂掉（不只那一项指标）。
    上界早有 `min(..., 100)` 挡着（防假饱和），下界一直漏着 —— 这条锁的是补上的下界。

    **断言 20.0 而不是「只要 >= 0 就行」**，是为了同时锁住「夹在**每一行**」
    这个实现选择：若改成最后夹总数，那条 -99h 会把这批里真实的 39.2h 一起抹成 0
    （→ 0.0%），等于用脏数据覆盖好数据。那时这条会失败并指向这里。
    """
    now = datetime.now()
    orders = [
        order_with_hours(1, 39.2),
        make_order_between(2, now - timedelta(hours=1), now - timedelta(hours=100), status=2),
    ]
    session = build_session(spaces=two_spaces_null_open_time(), orders=orders)

    assert await usage(session, DAYS) == 20.0


def test_U11补充_占用时长helper对异常区间一律回0():
    """
    直接锁 `_occupied_hours` 的契约：`end <= start` 一律回 0.0，永不回负数。

    与 U11 的分工：U11 证明「聚合结果不受脏数据拖累」，这条证明**根因**那一步 ——
    两条都失败时能直接区分是「夹错了行」还是「压根没夹」。
    """
    base = datetime(2026, 9, 28, 12, 0, 0)

    assert svc._occupied_hours(base, base + timedelta(hours=2)) == 2.0
    assert svc._occupied_hours(base, base) == 0.0                      # 零长
    assert svc._occupied_hours(base, base - timedelta(hours=99)) == 0.0  # 填反
    assert svc._occupied_hours(base, base - timedelta(seconds=1)) == 0.0
