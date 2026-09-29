"""`space_service.query_spaces` 用例：时段重叠排除 + 开放时段过滤。

对应阶段 3 完成文档第 6 节第 1 条「`query_spaces` 时段盲区」——桩只收时段不用，
把已订出去的场地判为「可选」。本文件是那条遗留问题的回归护栏。

其中 `test_stage03_reported_case_is_fixed` 直接复现文档里记录的原始场景：
`10-15 13:00~17:00` 时段 space 4 已被订单占住，修复前仍返回 count=1。

全程离线：SQLite 临时库（conftest 的 `engine` / `db_session` 夹具），不连云库。
"""

from __future__ import annotations

import inspect
from datetime import datetime, time

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agent.tools._common import TIME_FORMATS as TOOL_TIME_FORMATS
from app.models.reservation import OCCUPYING_STATUS, ReserveOrder
from app.models.resource import SpaceResource
from app.services import space_service as space_service_module
from app.services.space_service import TIME_FORMATS, query_spaces

#: 文档里记录的那一时段（阶段 3 完成文档第 3 节原始输出）
WINDOW_START = "2026-10-15 13:00:00"
WINDOW_END = "2026-10-15 17:00:00"


# ==========================================================================
# 夹具
# ==========================================================================
@pytest.fixture
async def use_test_db(monkeypatch: pytest.MonkeyPatch, engine) -> None:
    """把 `space_service` 用的 `AsyncSessionLocal` 指到测试库。

    ⚠️ 必须打在 **`space_service` 模块**上，不能打 `app.core.database.AsyncSessionLocal`：
    `space_service` 写的是 `from app.core.database import AsyncSessionLocal`，
    该名字在 import 时已绑定进本模块的命名空间，改源头对已绑定的名字无效
    —— 测试会静默连回云库（或连不上），且看起来像「查询没生效」。
    """
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(space_service_module, "AsyncSessionLocal", factory)


async def _add_space(
    db,
    *,
    space_id: int,
    name: str,
    space_type: int,
    capacity: int,
    open_start: str | None = "09:00:00",
    open_end: str | None = "21:00:00",
    status: int = 1,
) -> None:
    db.add(
        SpaceResource(
            id=space_id,
            space_name=name,
            space_type=space_type,
            capacity=capacity,
            location="测试位置",
            budget=800,
            open_start_time=time.fromisoformat(open_start) if open_start else None,
            open_end_time=time.fromisoformat(open_end) if open_end else None,
            status=status,
        )
    )
    await db.commit()


async def _add_order(
    db, *, order_id: int, space_id: int, start: str, end: str, order_status: int
) -> None:
    db.add(
        ReserveOrder(
            id=order_id,
            user_id=1,
            space_id=space_id,
            start_time=datetime.strptime(start, "%Y-%m-%d %H:%M:%S"),
            end_time=datetime.strptime(end, "%Y-%m-%d %H:%M:%S"),
            order_status=order_status,
        )
    )
    await db.commit()


async def _query(
    *, capacity: int = 40, space_type: int = 2, start: str = WINDOW_START, end: str = WINDOW_END
) -> dict:
    return await query_spaces(
        capacity=capacity, space_type=space_type, start_time=start, end_time=end
    )


def _ids(result: dict) -> list[int]:
    return [s["id"] for s in result["spaces"]]


# ==========================================================================
# 一、时段重叠排除
# ==========================================================================
async def test_stage03_reported_case_is_fixed(use_test_db, db_session) -> None:
    """阶段 3 原始案例：space 4 在该时段已被占，必须被排除。

    修复前该查询返回 `count=1`（space 4 被判为「可选」），Agent 据此推荐，
    用户到 `lock_resources` 才被拒 —— 本用例即那条链路的回归护栏。
    """
    await _add_space(db_session, space_id=4, name="A栋3楼展厅", space_type=2, capacity=50)
    await _add_order(
        db_session,
        order_id=9,
        space_id=4,
        start=WINDOW_START,
        end=WINDOW_END,
        order_status=1,  # 待确认
    )

    result = await _query()

    assert result["count"] == 0, "已被订单占住的场地不得出现在候选里"
    assert result["spaces"] == []


async def test_free_space_is_returned(use_test_db, db_session) -> None:
    """同一场地、同一时段，没有占位订单时必须返回 —— 证明上一条不是「永远为空」。"""
    await _add_space(db_session, space_id=4, name="A栋3楼展厅", space_type=2, capacity=50)

    result = await _query()

    assert _ids(result) == [4]
    assert result["spaces"][0]["spaceName"] == "A栋3楼展厅"


@pytest.mark.parametrize("order_status", [1, 2])
async def test_occupying_status_excludes(use_test_db, db_session, order_status) -> None:
    """`OCCUPYING_STATUS = (1, 2)`：待确认与已确认都占位。

    待确认（1）也占位是**有意比主文档 5.5 字面更严**——`create_order` 默认落 1，
    若只查 status=2，Agent 刚提交的待确认订单不占位，并发下会被重复预约。
    取值与 `create_order` 一致，由 `test_occupying_status_matches_order_service` 钉住。
    """
    await _add_space(db_session, space_id=4, name="A栋3楼展厅", space_type=2, capacity=50)
    await _add_order(
        db_session,
        order_id=1,
        space_id=4,
        start="2026-10-15 14:00:00",
        end="2026-10-15 16:00:00",
        order_status=order_status,
    )

    assert await _query() == {"count": 0, "spaces": []}


@pytest.mark.parametrize("order_status", [3, 4])
async def test_cancelled_and_finished_orders_do_not_occupy(
    use_test_db, db_session, order_status
) -> None:
    """已取消（3）与已完成（4）不占位：场地仍可订。

    种子数据专门备了正反证据（订单 3=已取消、订单 1=已完成均不拦），
    这里用同样的口径做离线版。
    """
    await _add_space(db_session, space_id=4, name="A栋3楼展厅", space_type=2, capacity=50)
    await _add_order(
        db_session,
        order_id=3,
        space_id=4,
        start=WINDOW_START,
        end=WINDOW_END,
        order_status=order_status,
    )

    assert _ids(await _query()) == [4]


async def test_touching_intervals_do_not_count_as_overlap(use_test_db, db_session) -> None:
    """首尾相接不算重叠（半开区间）：上一场 11:00 结束、本场 11:00 开始。

    `existing.end > start` 用的是严格大于，写错成 `>=` 会让紧邻的时段被误排除。
    """
    await _add_space(db_session, space_id=4, name="A栋3楼展厅", space_type=2, capacity=50)
    await _add_order(
        db_session,
        order_id=1,
        space_id=4,
        start="2026-10-15 09:00:00",
        end="2026-10-15 11:00:00",
        order_status=2,
    )

    result = await _query(start="2026-10-15 11:00:00", end="2026-10-15 13:00:00")

    assert _ids(result) == [4]


async def test_partially_overlapping_order_excludes(use_test_db, db_session) -> None:
    """部分重叠（尾压头）同样要排除，这是最容易漏判的一类。"""
    await _add_space(db_session, space_id=4, name="A栋3楼展厅", space_type=2, capacity=50)
    await _add_order(
        db_session,
        order_id=1,
        space_id=4,
        start="2026-10-15 16:00:00",
        end="2026-10-15 18:00:00",
        order_status=2,
    )

    assert await _query() == {"count": 0, "spaces": []}


async def test_other_space_order_does_not_exclude(use_test_db, db_session) -> None:
    """别家场地的订单不能连坐：space 5 被占，space 4 照常返回。"""
    await _add_space(db_session, space_id=4, name="A栋3楼展厅", space_type=2, capacity=50)
    await _add_space(db_session, space_id=5, name="C栋1楼展厅", space_type=2, capacity=45)
    await _add_order(
        db_session,
        order_id=1,
        space_id=5,
        start=WINDOW_START,
        end=WINDOW_END,
        order_status=2,
    )

    assert _ids(await _query()) == [4]


async def test_order_in_other_window_does_not_exclude(use_test_db, db_session) -> None:
    """同时段之外的历史订单不影响本次查询。"""
    await _add_space(db_session, space_id=4, name="A栋3楼展厅", space_type=2, capacity=50)
    await _add_order(
        db_session,
        order_id=1,
        space_id=4,
        start="2026-10-01 09:00:00",
        end="2026-10-01 11:00:00",
        order_status=2,
    )

    assert _ids(await _query()) == [4]


# ==========================================================================
# 二、开放时段过滤
# ==========================================================================
async def test_window_outside_open_hours_excluded(use_test_db, db_session) -> None:
    """展厅 09:00 才开门，08:00 开始的请求应被排除。"""
    await _add_space(db_session, space_id=4, name="A栋3楼展厅", space_type=2, capacity=50)

    result = await _query(start="2026-10-15 08:00:00", end="2026-10-15 10:00:00")

    assert result == {"count": 0, "spaces": []}


async def test_window_exceeding_close_time_excluded(use_test_db, db_session) -> None:
    """21:00 关门，订到 22:00 应被排除（结尾越界）。"""
    await _add_space(db_session, space_id=4, name="A栋3楼展厅", space_type=2, capacity=50)

    result = await _query(start="2026-10-15 20:00:00", end="2026-10-15 22:00:00")

    assert result == {"count": 0, "spaces": []}


async def test_window_equal_to_open_hours_included(use_test_db, db_session) -> None:
    """边界相等算通过：09:00~21:00 正好占满开放时段，应返回。"""
    await _add_space(db_session, space_id=4, name="A栋3楼展厅", space_type=2, capacity=50)

    result = await _query(start="2026-10-15 09:00:00", end="2026-10-15 21:00:00")

    assert _ids(result) == [4]


async def test_null_open_hours_means_unrestricted(use_test_db, db_session) -> None:
    """开放时段为 NULL 视为不限——覆盖 `or_(... is_(None))` 两个分支。"""
    await _add_space(
        db_session,
        space_id=4,
        name="户外场地",
        space_type=2,
        capacity=50,
        open_start=None,
        open_end=None,
    )

    result = await _query(start="2026-10-15 06:00:00", end="2026-10-15 23:00:00")

    assert _ids(result) == [4]


async def test_cross_day_window_returns_empty(use_test_db, db_session) -> None:
    """跨日请求返回空集。

    开放时段是 TIME（不含日期），表达不了跨日区间。若不加这道判断，
    「10-15 20:00 ~ 10-16 10:00」反而能同时满足 `open_start <= 20:00` 与
    `open_end >= 10:00` 而被判为合规 —— 那是个静默放行。
    """
    await _add_space(
        db_session,
        space_id=4,
        name="户外场地",
        space_type=2,
        capacity=50,
        open_start=None,
        open_end=None,
    )

    result = await _query(start="2026-10-15 20:00:00", end="2026-10-16 10:00:00")

    assert result == {"count": 0, "spaces": []}


# ==========================================================================
# 三、原有筛选维度未被破坏
# ==========================================================================
async def test_capacity_and_type_still_filter(use_test_db, db_session) -> None:
    """容量与类型仍在生效，且结果按容量升序。

    对应 stage-03 里「展厅仅 id4=50人 达标、id5=35人 被容量滤掉」那条。
    """
    await _add_space(db_session, space_id=4, name="A栋3楼展厅", space_type=2, capacity=50)
    await _add_space(db_session, space_id=5, name="C栋1楼展厅", space_type=2, capacity=35)
    await _add_space(db_session, space_id=1, name="A栋201会议室", space_type=1, capacity=60)

    result = await _query(capacity=40, space_type=2)

    assert _ids(result) == [4]


async def test_disabled_space_excluded(use_test_db, db_session) -> None:
    """`status=0`（停用）的场地始终不返回。"""
    await _add_space(db_session, space_id=4, name="A栋3楼展厅", space_type=2, capacity=50, status=0)

    assert await _query() == {"count": 0, "spaces": []}


# ==========================================================================
# 四、契约护栏
# ==========================================================================
def test_signature_is_frozen() -> None:
    """签名不得改动。

    主文档 §5.3 模块 4 冻结，阶段 3 的桩、阶段 4 的 Tool、阶段 7 的用例
    都以它为准。改参数名或增删参数都会让 Tool 层的 `_query_spaces_service(...)`
    调用当场 `TypeError` —— 这条用例把它钉死。
    """
    params = list(inspect.signature(query_spaces).parameters)

    assert params == ["capacity", "space_type", "start_time", "end_time"]


def test_occupying_status_matches_order_service() -> None:
    """本模块取的占位状态必须与模块 3 `create_order` 用的一致。

    ⚠️ **2026-09-28 修正：这条护栏原本是断的。**

    原用例写的是 `from app.services.order_service import OCCUPYING_STATUS`，
    但合并之后 `order_service` 里**已经没有** `OCCUPYING_STATUS` 这个名字 ——
    它改从 `app.models` 引入 `ACTIVE_ORDER_STATUSES`（见 `order_service.py:97-103`）。
    于是这一条 import 直接抛 `ImportError`：**整个套件里唯一一条没有任何 xfail 保护、
    必然变红的用例，而它本身恰恰是「防常量漂移」的护栏 —— 护栏自己断了。**
    现在改为引用 `create_order` **真正使用**的那一个常量，护栏语义不变。

    口径现状（2026-09-28 实测）：同一语义在仓库里有 4 处声明 ——
        · `app/models/reservation.py` 的 `ACTIVE_ORDER_STATUSES`（引 `OrderStatus` 枚举，规范版）
        · `app/models/reservation.py` 的 `OCCUPYING_STATUS`（字面量；空间查询在用）
        · `app/services/rules/base.py` 的 `ACTIVE_ORDER_STATUSES`（字面量）
        · `app/services/image_service.py` 的 `_ORDER_ACTIVE_STATUS`（字面量）
    本用例只钉住**本模块用的那一份**与 `create_order` 用的那一份之间的一致性 ——
    这是最要命的一条：它俩一分叉，就是并发重复预约（见下）。

    两份声明一旦分叉，后果是**并发重复预约**：`create_order` 落下的待确认订单按一边
    算占位、`query_spaces` 按另一边算可订，Agent 就会推荐一个刚被占住的场地。
    故用这条护栏代替注释防漂移。

    `int(s)` 转换是必要的：`ACTIVE_ORDER_STATUSES` 装的是 `OrderStatus` 枚举成员，
    直接与字面量元组比较虽然也相等（IntEnum），但显式取整让意图更清楚、也更抗将来改动。
    """
    from app.services.order_service import ACTIVE_ORDER_STATUSES as ORDER_SERVICE_ACTIVE

    assert OCCUPYING_STATUS == tuple(int(s) for s in ORDER_SERVICE_ACTIVE), (
        f"占位口径分叉：models.OCCUPYING_STATUS={OCCUPYING_STATUS}，"
        f"但 create_order 用的是 {tuple(ORDER_SERVICE_ACTIVE)}"
    )


def test_time_formats_match_tool_layer() -> None:
    """本层的时间格式表必须与 Tool 层一致。

    Tool 校验后把**原始字符串**透传给本函数（不归一化），两边格式表一旦分叉，
    就会出现「Tool 判合法、service 解析失败」—— 而失败点在 Agent 循环内部。
    两份声明因层次原因无法合并（service 不能反向 import agent 层），
    故用这条护栏代替注释防漂移。
    """
    assert TIME_FORMATS == TOOL_TIME_FORMATS


async def test_accepts_tool_layer_alternate_formats(use_test_db, db_session) -> None:
    """Tool 层接受的另外几种时间写法，本层也要能解。"""
    await _add_space(db_session, space_id=4, name="A栋3楼展厅", space_type=2, capacity=50)

    result = await query_spaces(
        capacity=40,
        space_type=2,
        start_time="2026-10-15T13:00:00",
        end_time="2026-10-15T17:00:00",
    )

    assert _ids(result) == [4]


async def test_reversed_time_raises(use_test_db) -> None:
    """时段倒置抛 `ParamInvalidError`（给绕过 Tool 直调 service 的入口兜底）。"""
    from app.core.exceptions import ParamInvalidError

    with pytest.raises(ParamInvalidError):
        await _query(start=WINDOW_END, end=WINDOW_START)


async def test_unparsable_time_raises(use_test_db) -> None:
    """自然语言时间解不出时响亮失败，不静默返回空集。"""
    from app.core.exceptions import ParamInvalidError

    with pytest.raises(ParamInvalidError):
        await _query(start="下周五下午", end=WINDOW_END)


# ==========================================================================
# 四、list_space_bookings：某场地被哪些订单占走了（2026-09-30 新增）
# ==========================================================================
from datetime import date, timedelta  # noqa: E402

from app.services.space_service import list_space_bookings  # noqa: E402


async def test_list_space_bookings_returns_only_occupying_orders(db_session) -> None:
    """只返回「占用态」（1 待确认 / 2 已确认），并按开始时间升序。

    口径必须与 create_order / query_spaces 同源，否则会出现
    「这个接口说占了、下单却说没占」这种自相矛盾。
    """
    await _add_space(db_session, space_id=6, name="综合楼大礼堂", space_type=3, capacity=80)
    base = date(2026, 10, 1)
    # 已确认
    await _add_order(
        db_session, order_id=1, space_id=6,
        start="2026-10-02 10:00:00", end="2026-10-02 12:00:00", order_status=2,
    )
    # 待确认 —— 也算占用
    await _add_order(
        db_session, order_id=2, space_id=6,
        start="2026-10-01 09:00:00", end="2026-10-01 11:00:00", order_status=1,
    )
    # 已取消 / 已完成 —— 时段必须已经释放
    await _add_order(
        db_session, order_id=3, space_id=6,
        start="2026-10-03 09:00:00", end="2026-10-03 11:00:00", order_status=3,
    )
    await _add_order(
        db_session, order_id=4, space_id=6,
        start="2026-10-04 09:00:00", end="2026-10-04 11:00:00", order_status=4,
    )
    # 别的场地的订单不许串台
    await _add_space(db_session, space_id=7, name="综合楼小多功能厅", space_type=3, capacity=25)
    await _add_order(
        db_session, order_id=5, space_id=7,
        start="2026-10-02 10:00:00", end="2026-10-02 12:00:00", order_status=2,
    )

    rows = await list_space_bookings(db_session, 6, days=30, start=base)

    assert [r.id for r in rows] == [2, 1], "按 start_time 升序，且只含待确认/已确认"


async def test_list_space_bookings_window_overlap_is_half_open(db_session) -> None:
    """区间左闭右开：紧贴区间之前的订单不算，跨天占用要算进来。"""
    await _add_space(db_session, space_id=4, name="A栋3楼展厅", space_type=2, capacity=50)
    base = date(2026, 10, 10)
    # 完全落在区间内
    await _add_order(
        db_session, order_id=1, space_id=4,
        start="2026-10-10 09:00:00", end="2026-10-10 11:00:00", order_status=2,
    )
    # 区间开始之前就结束了 → 不算
    await _add_order(
        db_session, order_id=2, space_id=4,
        start="2026-10-09 15:00:00", end="2026-10-09 17:00:00", order_status=2,
    )
    # 跨天：起始早于区间、结束落在区间内 → 算
    await _add_order(
        db_session, order_id=3, space_id=4,
        start="2026-10-09 20:00:00", end="2026-10-10 02:00:00", order_status=2,
    )

    rows = await list_space_bookings(db_session, 4, days=2, start=base)

    assert sorted(r.id for r in rows) == [1, 3]


async def test_list_space_bookings_defaults_to_today(db_session) -> None:
    """不传 start 时从「今天」起算——前端走的就是这条默认路径。"""
    await _add_space(db_session, space_id=8, name="中心广场", space_type=4, capacity=100)

    today = date.today()
    inside = today + timedelta(days=2)
    outside = today + timedelta(days=40)

    await _add_order(
        db_session, order_id=1, space_id=8,
        start=f"{inside.isoformat()} 10:00:00", end=f"{inside.isoformat()} 12:00:00",
        order_status=2,
    )
    await _add_order(
        db_session, order_id=2, space_id=8,
        start=f"{outside.isoformat()} 10:00:00", end=f"{outside.isoformat()} 12:00:00",
        order_status=2,
    )

    rows = await list_space_bookings(db_session, 8, days=7)

    assert [r.id for r in rows] == [1], "超出 days 窗口的订单不该返回"


async def test_list_space_bookings_empty_is_a_real_answer(db_session) -> None:
    """没占用就返回空列表而不是抛异常——「没人订」本身就是要展示给用户的信息。"""
    await _add_space(db_session, space_id=9, name="B栋102会议室", space_type=1, capacity=30)
    assert await list_space_bookings(db_session, 9, days=7, start=date(2026, 10, 1)) == []
