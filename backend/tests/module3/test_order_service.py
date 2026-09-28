"""服务层契约：`app.services.order_service.create_order`（§5.5 事务六步）。

这批用例**绕过 HTTP** 直接调服务层，理由有二：

1. Agent 的 `lock_resources` Tool 就是这么调的（§4.3 / §9.3）——HTTP 路由只是它的
   一个调用方。契约真正的消费者是 Agent，测它就得按 Agent 的调法测。
2. 「业务性失败不抛异常、返回结构化结果」这条只有直调才测得出来：走 HTTP 时早被
   路由翻译成状态码了，异常与否都被吃掉。

`test_frozen_signature_is_keyword_only` 是这批用例里最要紧的一条：签名已冻结
（对方模块的 Tool 直接依赖），参数名、顺序、关键字限定的任何变动都会让那个模块
在运行时静默错位，而不是报错。
"""
from datetime import time
from inspect import Parameter, signature

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models import DeviceResource, ReserveOrder, SpaceResource
from app.services import order_service
from app.services.order_service import create_order
from app.state_machine import OrderStatus

from .helpers import MOCK_USER_ID, OTHER_USER_ID, time_str

#: 冻结的参数表（名字 + 顺序）。改这里 = 改契约，必须先通知核心调度 Agent 模块。
FROZEN_PARAMS = [
    "user_id",
    "space_id",
    "start_time",
    "end_time",
    "device_ids",
    "agent_request",
    "agent_trace",
    "order_status",
]

#: 冻结的返回字段集：成功与失败**同一套字段**，调用方无需分支取值。
FROZEN_RESULT_KEYS = {"ok", "orderId", "reason", "conflictType", "conflictDetail"}


async def _call(**overrides):
    """按 Agent Tool 的调法调一次服务层。"""
    kwargs = {
        "user_id": MOCK_USER_ID,
        "space_id": 1,
        "start_time": time_str(1, 9),
        "end_time": time_str(1, 10),
    }
    kwargs.update(overrides)
    return await create_order(**kwargs)


async def _count_orders() -> int:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(func.count(ReserveOrder.id)))).scalar_one()


async def _add_device(**overrides) -> int:
    """插一台测试设备（夹具只种了 2 台完好设备，异常态要现造）。"""
    fields = {
        "device_name": "测试设备",
        "device_type": "其他",
        "device_status": 1,
        "total_count": 1,
        "available_count": 1,
    }
    fields.update(overrides)
    async with AsyncSessionLocal() as db:
        device = DeviceResource(**fields)
        db.add(device)
        await db.commit()
        await db.refresh(device)
        return device.id


async def _add_space(**overrides) -> int:
    """插一个测试场地。

    夹具只种了 2 个场地，而设备容量用例需要**同一时段、不同场地**的多张订单：
    第 3 步的时间冲突是按场地判的，同场地同时间会在设备容量之前就拒掉，
    测出来的就不是容量行为了。
    """
    fields = {
        "space_name": "测试场地",
        "space_type": 1,
        "capacity": 5,
        "location": "9F",
        "open_start_time": time(8, 0),
        "open_end_time": time(22, 0),
        "status": 1,
    }
    fields.update(overrides)
    async with AsyncSessionLocal() as db:
        space = SpaceResource(**fields)
        db.add(space)
        await db.commit()
        await db.refresh(space)
        return space.id


# ---------------------------------------------------------------- 冻结契约本身


def test_frozen_signature_is_keyword_only():
    """签名冻结：参数名/顺序/关键字限定/db 不进签名，四项一次锁死。

    - keyword-only：位置传参一律拒绝，避免日后在中间插参数时静默错位
    - 没有 `db`：Tool 拿不到 `AsyncSession`（§7.4），会话必须由服务层自管
    """
    params = list(signature(create_order).parameters.values())

    assert [p.name for p in params] == FROZEN_PARAMS
    assert all(p.kind is Parameter.KEYWORD_ONLY for p in params), "全部参数必须 keyword-only"
    assert "db" not in {p.name for p in params}, "签名里不得出现 db（会话自管，§5.5）"

    # 每个参数都必须有类型标注和默认值（除前四个必填）——冻结期不允许再改
    required = {"user_id", "space_id", "start_time", "end_time"}
    for p in params:
        assert p.annotation is not Parameter.empty, f"{p.name} 缺类型标注"
        assert (p.default is Parameter.empty) is (p.name in required), f"{p.name} 默认值不符合冻结表"


async def test_result_keys_identical_on_success_and_failure():
    """成功与失败返回**字段集相同**，调用方不必写两套取值分支。"""
    ok = await _call()
    bad = await _call(space_id=999)

    assert set(ok) == FROZEN_RESULT_KEYS
    assert set(bad) == FROZEN_RESULT_KEYS
    assert ok["ok"] is True and ok["orderId"] and ok["conflictType"] is None
    assert bad["ok"] is False and bad["orderId"] is None and bad["conflictType"] == "not_found"


# ---------------------------------------------------------------- 成功路径


async def test_create_success_persists_and_returns_order_id():
    """成功：返回 orderId，订单落库为待确认，agent_trace 原样存 JSON。"""
    trace = [
        {"step": 1, "result": "解析需求", "timestamp": "2026-01-01 09:00:00"},
        {"step": 2, "result": "生成方案", "timestamp": "2026-01-01 09:00:03"},
    ]
    r = await _call(device_ids=[1], agent_request="明天上午要个会议室", agent_trace=trace)
    assert r["ok"] is True
    assert r["reason"] == "预约创建成功"

    async with AsyncSessionLocal() as db:
        order = await db.get(ReserveOrder, r["orderId"])
        assert order.user_id == MOCK_USER_ID
        assert order.space_id == 1
        assert order.device_ids == [1]
        assert order.order_status == OrderStatus.PENDING.value
        assert order.agent_request == "明天上午要个会议室"
        assert order.agent_trace == trace


async def test_order_status_defaults_to_pending_and_can_be_overridden():
    """order_status 默认 1（待确认）；调用方可显式传 2（Agent 的 needConfirm 为 false 时）。"""
    default = await _call()
    explicit = await _call(space_id=2, start_time=time_str(2, 9), end_time=time_str(2, 10),
                           order_status=OrderStatus.CONFIRMED.value)

    async with AsyncSessionLocal() as db:
        assert (await db.get(ReserveOrder, default["orderId"])).order_status == 1
        assert (await db.get(ReserveOrder, explicit["orderId"])).order_status == 2


async def test_empty_agent_request_stored_as_null():
    """agentRequest 为空串时落 NULL（§6.3 该列可空），不落空字符串。"""
    r = await _call(agent_request="")
    async with AsyncSessionLocal() as db:
        assert (await db.get(ReserveOrder, r["orderId"])).agent_request is None


async def test_agent_request_truncated_to_column_width():
    """agentRequest 超长按 §6.3 表6 的 VARCHAR(1024) 截断，不因长度丢单。"""
    r = await _call(agent_request="需" * 2000)
    assert r["ok"] is True
    async with AsyncSessionLocal() as db:
        stored = (await db.get(ReserveOrder, r["orderId"])).agent_request
        assert len(stored) == 1024


# ---------------------------------------------------------------- §5.5 第 3 步：时间冲突


async def test_time_conflict_returns_structured_detail():
    """同时段同场地 → time_conflict，并带上冲突订单明细供屏 3 展示。"""
    first = await _call()
    second = await _call()

    assert second["ok"] is False
    assert second["conflictType"] == "time_conflict"
    assert second["reason"] == "该时段已被占用"
    conflicts = second["conflictDetail"]["conflicts"]
    assert [c["orderId"] for c in conflicts] == [first["orderId"]]
    assert conflicts[0]["startTime"] == time_str(1, 9)


async def test_adjacent_slots_are_not_conflicts():
    """半开区间：首尾相接（10:00 结束 / 10:00 开始）不算冲突。"""
    await _call(start_time=time_str(1, 9), end_time=time_str(1, 10))
    r = await _call(start_time=time_str(1, 10), end_time=time_str(1, 11))
    assert r["ok"] is True


async def test_cancelled_order_frees_the_slot():
    """已取消的订单不占时段（冲突只统计 1/2 状态）。"""
    first = await _call()
    async with AsyncSessionLocal() as db:
        order = await db.get(ReserveOrder, first["orderId"])
        order.order_status = OrderStatus.CANCELLED.value
        await db.commit()

    assert (await _call())["ok"] is True


# ---------------------------------------------------------------- §5.5 第 4 步：设备


async def test_device_time_overlap_is_rejected():
    """同一设备在重叠时段被占满 → device_conflict（换场地也一样）。

    夹具里的设备 `available_count=1`，所以「被占一次」就等于约满；容量 > 1 的
    情形见下面 AGENT-C-01/02 那一组。
    """
    await _call(space_id=1, device_ids=[1])
    r = await _call(space_id=2, device_ids=[1])   # 换场地，但设备仍是 1

    assert r["ok"] is False
    assert r["conflictType"] == "device_conflict"
    assert r["reason"] == "该时段设备已约满"
    assert r["conflictDetail"]["conflicts"][0]["deviceIds"] == [1]


async def test_different_devices_do_not_collide():
    """不同设备互不影响。"""
    await _call(space_id=1, device_ids=[1])
    assert (await _call(space_id=2, device_ids=[2]))["ok"] is True


async def test_device_not_found_is_not_a_conflict():
    """设备不存在 → `not_found`（HTTP 404），不是 `device_conflict`（409）。

    归错类会把 §5.3 模块3 契约里的 404 整体变成 409。
    """
    r = await _call(device_ids=[999])
    assert r["ok"] is False and r["conflictType"] == "not_found"
    assert "999" in r["reason"]
    assert r["conflictDetail"] == {"target": "device", "deviceIds": [999]}


async def test_device_with_abnormal_status_rejected():
    """设备状态非 1（损坏/缺失配件）→ 拒绝。"""
    did = await _add_device(device_status=2, device_name="坏的投影仪")
    r = await _call(device_ids=[did])

    assert r["ok"] is False and r["conflictType"] == "device_conflict"
    assert "坏的投影仪" in r["reason"]
    assert r["conflictDetail"]["conflicts"] == [{"deviceId": did, "reason": "status"}]


async def test_device_without_stock_rejected():
    """available_count 为 0 → 拒绝。

    0 在这里的含义是**可用上限为 0**（这台设备不参与预约），不是「恰好借光了」。
    注意本函数**只读不写** available_count：它是上限不是余额，剩余量用时推导
    （见 `_device_conflicts`），所以 §5.5 六步没有扣减、也没有第 7 步回补。
    """
    did = await _add_device(available_count=0, device_name="无库存音响")
    r = await _call(device_ids=[did])

    assert r["ok"] is False and r["conflictType"] == "device_conflict"
    assert "无库存音响" in r["reason"]
    assert r["conflictDetail"]["conflicts"] == [{"deviceId": did, "reason": "exhausted"}]

    async with AsyncSessionLocal() as db:
        assert (await db.get(DeviceResource, did)).available_count == 0   # 未被扣减


# ------------------------------------------------ AGENT-C-01/02：设备容量（用时推导）
#
# `device_resource.available_count` = **可用上限**，不是「还剩几台」。剩余量用时推导：
#     该时段剩余量 = available_count − 该时段重叠单数
# 因此容量的判据是计数比较（`重叠单数 >= available_count` 才拒），且**没有任何
# 扣减/回补代码** —— 取消/完成让订单离开 `ACTIVE_ORDER_STATUSES`，名额自动回来。
# 下面 7 条对应 `给徐川-available_count口径判据.md` §4 的判据表，供 AGENT-C-01/02 对齐。


async def test_capacity_allows_up_to_available_count():
    """判据 1~3：cap=2 时第 1、2 单成功，第 3 单才被拒（409 / 40901）。

    判据 2 是这次改动的**核心**：旧实现「查到重叠就拒」会让第 2 单也失败。
    """
    did = await _add_device(total_count=2, available_count=2, device_name="双份投影仪")
    third_space = await _add_space()

    first = await _call(space_id=1, device_ids=[did])                    # 判据 1
    second = await _call(space_id=2, device_ids=[did])                   # 判据 2

    assert first["ok"] is True
    assert second["ok"] is True, "cap=2 时第 2 单必须成功（旧实现会误拒）"

    third = await _call(space_id=third_space, device_ids=[did])          # 判据 3
    assert third["ok"] is False
    assert third["conflictType"] == "device_conflict"

    # 形状按 `docs/api.md` 里 `create_order` 的冻结契约：一单一条，列出占着这台
    # 设备的那些单（不是「一台一条」的计数条目 —— 改形状要走 §5.3）
    conflicts = third["conflictDetail"]["conflicts"]
    assert sorted(c["orderId"] for c in conflicts) == sorted(
        [first["orderId"], second["orderId"]]
    )
    assert all(c["deviceIds"] == [did] for c in conflicts)


async def test_cancel_frees_a_slot_without_any_refund_code():
    """判据 4、5：取消一单后名额自动回落，第 3 单可建。

    「回落」不需要回补代码：`ACTIVE_ORDER_STATUSES` 只有 1/2（3已取消 / 4已完成
    是终态），取消单离开该集合，下一单算出来的 used 自然少一。这正是「用时推导」
    相对「写时扣减」的价值 —— 写时扣减必须在取消**和**完成两条路径上都记得回补，
    漏一条就会单调递减到 0，而且不报错、不进日志。
    """
    did = await _add_device(total_count=2, available_count=2, device_name="双份投影仪")
    third_space = await _add_space()

    first = await _call(space_id=1, device_ids=[did])
    await _call(space_id=2, device_ids=[did])
    assert (await _call(space_id=third_space, device_ids=[did]))["ok"] is False

    async with AsyncSessionLocal() as db:                                # 判据 4
        order = await db.get(ReserveOrder, first["orderId"])
        order.order_status = OrderStatus.CANCELLED.value
        await db.commit()

    after = await _call(space_id=third_space, device_ids=[did])          # 判据 5
    assert after["ok"] is True, "取消后名额必须回落"


async def test_adjacent_slot_does_not_consume_capacity():
    """判据 6：首尾相接不算重叠（半开区间），名额不跨时段累计。"""
    did = await _add_device(total_count=1, available_count=1, device_name="单份投影仪")
    await _call(device_ids=[did], start_time=time_str(1, 9), end_time=time_str(1, 10))

    r = await _call(device_ids=[did], start_time=time_str(1, 10), end_time=time_str(1, 11))
    assert r["ok"] is True


async def test_capacity_is_counted_per_device():
    """判据 7：容量按设备各算各的 —— 设备 A 约满不影响设备 B。"""
    a = await _add_device(total_count=1, available_count=1, device_name="设备A")
    b = await _add_device(total_count=1, available_count=1, device_name="设备B")
    await _call(space_id=1, device_ids=[a])

    assert (await _call(space_id=2, device_ids=[b]))["ok"] is True


async def test_error_detail_names_only_the_exhausted_device():
    """一台约满、一台空闲时，detail 只报约满的那台（前端据此提示换哪台）。"""
    a = await _add_device(total_count=1, available_count=1, device_name="设备A")
    b = await _add_device(total_count=1, available_count=1, device_name="设备B")
    first = await _call(space_id=1, device_ids=[a])

    r = await _call(space_id=2, device_ids=[a, b])
    assert r["conflictType"] == "device_conflict"

    conflicts = r["conflictDetail"]["conflicts"]
    assert [c["orderId"] for c in conflicts] == [first["orderId"]]
    assert conflicts[0]["deviceIds"] == [a], "不得捎带只用到空闲设备 B 的单"


async def test_successful_order_never_writes_available_count():
    """下单一律不写 `available_count`：那列是上限，不是余额。

    这条与 `test_device_without_stock_rejected` 一起把「不扣减」钉死 —— 哪天有人
    往 `create_order` 里加了 `available_count -= 1`，两条会红，而串台要几周后才显形。
    """
    did = await _add_device(total_count=2, available_count=2, device_name="双份投影仪")
    assert (await _call(device_ids=[did]))["ok"] is True

    async with AsyncSessionLocal() as db:
        assert (await db.get(DeviceResource, did)).available_count == 2


def test_hit_device_ids_tolerates_dirty_json():
    """设备 JSON 列里混入脏数据时跳过该项，不让一条脏行把整个创建流程炸掉。

    `reserve_order.device_ids` 是 JSON 列且非必填，历史数据/别的模块写入的内容
    不保证全是整数 —— 这里的选择是**跳过**而不是抛错：为了一个脏元素拒绝一次
    合法预约，比漏判一个设备冲突更难排查。
    """
    assert order_service._hit_device_ids([1, "2", None, "x", 3], {2, 3}) == [2, 3]
    assert order_service._hit_device_ids(None, {1}) == []
    assert order_service._hit_device_ids([], {1}) == []


async def test_time_check_runs_before_device_check():
    """校验顺序按 §5.5：第 3 步（时间）先于第 4 步（设备）。

    同时踩两条时先报时间冲突——顺序反了会让「换场地试试」这类自动重试
    拿到误导性的原因（明明换场地也没用，却报设备问题）。
    """
    await _call(space_id=1, device_ids=[1])

    r = await _call(space_id=1, device_ids=[999])   # 同场地同时段 + 设备不存在
    assert r["conflictType"] == "time_conflict"


# ---------------------------------------------------------------- 其它业务性失败


async def test_space_not_found():
    r = await _call(space_id=999)
    assert r["ok"] is False and r["conflictType"] == "not_found"
    assert r["reason"] == "场地不存在"


async def test_user_not_found():
    """预约人必须是真实用户：云库上 user_id 是真外键，先查比让它炸成 500 友好。"""
    r = await _call(user_id=999999)
    assert r["ok"] is False and r["conflictType"] == "not_found"
    assert r["reason"] == "用户不存在"


async def test_missing_user_id_is_rejected_not_raised():
    """缺 user_id 时明确报错而不是抛异常或落 NULL —— 身份必须从 JWT 解析后传入。

    Agent 侧若忘了把 JWT 里的 user_id 传下来，这里就是唯一的拦截点。
    """
    r = await _call(user_id=None)
    assert r["ok"] is False and r["conflictType"] == "invalid_param"
    assert "user_id" in r["reason"]


async def test_illegal_order_status_rejected():
    """创建态只能是 1/2（状态机入口），3/4 是流转出来的结果态。"""
    for bad in (3, 4, 99):
        r = await _call(order_status=bad)
        assert r["ok"] is False and r["conflictType"] == "invalid_param"
        assert "order_status" in r["reason"]


async def test_invalid_time_format_rejected():
    r = await _call(start_time=time_str(1, 9).replace(" ", "T"))
    assert r["ok"] is False and r["conflictType"] == "invalid_param"
    assert "YYYY-MM-DD HH:mm:ss" in r["reason"]


async def test_start_not_before_end_rejected():
    r = await _call(start_time=time_str(1, 10), end_time=time_str(1, 9))
    assert r["ok"] is False and r["conflictType"] == "invalid_param"
    assert "开始时间必须早于结束时间" in r["reason"]


# ---------------------------------------------------------------- 模型输出边界（§9.3）


async def test_string_numbers_from_model_are_coerced():
    """模型把数字写成字符串是常态（`"space_id": "1"`），能转就转，不因此拒绝一次合法预约。"""
    r = await create_order(
        user_id=str(MOCK_USER_ID),
        space_id="1",
        start_time=time_str(1, 9),
        end_time=time_str(1, 10),
        device_ids=["1"],
        order_status=str(OrderStatus.CONFIRMED.value),
    )
    assert r["ok"] is True

    async with AsyncSessionLocal() as db:
        order = await db.get(ReserveOrder, r["orderId"])
        assert order.user_id == MOCK_USER_ID
        assert order.space_id == 1
        assert order.device_ids == [1]
        assert order.order_status == OrderStatus.CONFIRMED.value


async def test_non_numeric_ids_rejected():
    """转不成整数的入参一律 invalid_param —— 不能带进 SQL 才炸。"""
    assert (await _call(user_id="abc"))["conflictType"] == "invalid_param"
    assert (await _call(space_id="abc"))["conflictType"] == "invalid_param"
    assert (await _call(device_ids=[None]))["conflictType"] == "invalid_param"
    assert (await _call(device_ids=["x"]))["conflictType"] == "invalid_param"


async def test_device_ids_must_be_an_array():
    """`device_ids` 传字符串（`"1"` 会被逐字符迭代）必须被挡住，不能静默当成 [1]。"""
    r = await _call(device_ids="1")
    assert r["ok"] is False and r["conflictType"] == "invalid_param"
    assert "device_ids" in r["reason"]


async def test_bad_agent_payload_types_rejected():
    """agentRequest 必须是字符串、agentTrace 必须是对象数组（§5.3 模块4）。"""
    r = await _call(agent_request={"text": "开会"})
    assert r["ok"] is False and r["conflictType"] == "invalid_param"

    r = await _call(agent_trace={"step": 1})
    assert r["ok"] is False and r["conflictType"] == "invalid_param"
    assert "agent_trace" in r["reason"]


async def test_duplicate_device_ids_rejected():
    r = await _call(device_ids=[1, 1])
    assert r["ok"] is False and r["conflictType"] == "invalid_param"
    assert "重复" in r["reason"]


# ---------------------------------------------------------------- §5.5 原子性


async def test_failed_creation_leaves_nothing_behind():
    """§5.5：校验失败必须 ROLLBACK —— 失败的几次调用不能在库里留下任何行。"""
    await _call()                      # 1 条
    before = await _count_orders()

    await _call()                                  # 时间冲突
    await _call(space_id=2, device_ids=[999])      # 设备不存在
    await _call(space_id=999)                      # 场地不存在

    assert await _count_orders() == before


def test_lock_is_emitted_on_mysql_and_compiled_away_on_sqlite():
    """`§5.5` 第 2 步的行锁**必须真的出现在 SQL 里**（MySQL 方言下）。

    这条断言是因为单测跑不了锁：SQLite 方言会把 `FOR UPDATE` 编译掉，所以在
    临时 SQLite 上无论怎么并发抢时段都能全过 —— 删掉 `with_for_update()`，
    整套用例照样全绿，而云库上的并发防护已经没了。唯一能在 CI 里钉住它的办法
    就是直接编译这条语句，比对两种方言的输出。
    """
    from sqlalchemy.dialects import mysql, sqlite

    stmt = order_service._lock_space_stmt(1)   # noqa: SLF001 - 冻结期的机械护栏

    mysql_sql = str(stmt.compile(dialect=mysql.dialect()))
    sqlite_sql = str(stmt.compile(dialect=sqlite.dialect()))

    assert "FOR UPDATE" in mysql_sql, "§5.5 第 2 步的行锁丢了吗？"
    assert "FOR UPDATE" not in sqlite_sql, "SQLite 不支持行锁，此处应被方言编译掉"
    # 锁的对象必须是场地行本身，不是整张表、也不是别的表
    assert "space_resource" in mysql_sql


async def test_write_identity_is_never_taken_from_caller_body():
    """身份只认参数里传进来的值；服务层不做任何「从请求里猜身份」的动作。"""
    r = await _call(user_id=OTHER_USER_ID)
    async with AsyncSessionLocal() as db:
        assert (await db.get(ReserveOrder, r["orderId"])).user_id == OTHER_USER_ID


# ---------------------------------------------------------------- update_agent_trace


#: 补写链路冻结的参数表（`create_order` 之外**新增**的函数，同样 keyword-only、无 `db`）。
FROZEN_TRACE_PARAMS = ["order_id", "user_id", "agent_trace"]


async def _call_trace(**overrides):
    """按路由补写的调法调一次服务层。"""
    kwargs = {
        "order_id": 1,
        "user_id": MOCK_USER_ID,
        "agent_trace": [
            {"step": 1, "result": "解析需求", "timestamp": "2026-01-01 09:00:00"}
        ],
    }
    kwargs.update(overrides)
    return await order_service.update_agent_trace(**kwargs)


def test_update_trace_frozen_signature_is_keyword_only():
    """补写函数与 `create_order` 同规格冻结，四个属性一次锁死。

    `user_id` **必须**在签名里：它是归属校验的唯一输入（`§5.1`）。少了它，任何拿到
    `order_id` 的调用方都能改别人的 trace，这个函数就变成了越权写入口。
    """
    params = list(signature(order_service.update_agent_trace).parameters.values())

    assert [p.name for p in params] == FROZEN_TRACE_PARAMS
    assert all(p.kind is Parameter.KEYWORD_ONLY for p in params), "全部参数必须 keyword-only"
    assert "db" not in {p.name for p in params}, "签名里不得出现 db（会话自管）"
    for p in params:
        assert p.annotation is not Parameter.empty, f"{p.name} 缺类型标注"
        assert p.default is Parameter.empty, f"{p.name} 是必填，不应有默认值"


async def test_update_trace_result_keys_match_create_order():
    """返回字段集与 `create_order` 完全一致 —— 调用方一处取值逻辑两处通用。"""
    order_id = (await _call())["orderId"]

    ok = await _call_trace(order_id=order_id)
    bad = await _call_trace(order_id=999999)

    assert set(ok) == FROZEN_RESULT_KEYS
    assert set(bad) == FROZEN_RESULT_KEYS
    assert ok["ok"] is True and ok["orderId"] == order_id and ok["conflictType"] is None
    assert bad["ok"] is False and bad["orderId"] is None
    assert bad["conflictType"] == "not_found"


async def test_create_then_update_trace_is_the_agent_chain():
    """AGENT-C-01 的完整链路：创建时 trace 为 `None`（尚未生成）→ Agent 跑完补写。

    这正是「缺了 create_order 真实实现就只能走到跳过分支」所指的那条链路。
    """
    order_id = (await _call(agent_request="明天上午要个会议室"))["orderId"]

    async with AsyncSessionLocal() as db:
        assert (await db.get(ReserveOrder, order_id)).agent_trace is None, (
            "创建时不得落残缺 trace —— 必须是 None，语义为「尚未生成」"
        )

    trace = [
        {"step": 1, "result": "解析需求", "timestamp": "2026-01-01 09:00:00"},
        {"step": 2, "result": "生成方案", "timestamp": "2026-01-01 09:00:03"},
    ]
    assert (await _call_trace(order_id=order_id, agent_trace=trace))["ok"] is True

    async with AsyncSessionLocal() as db:
        assert (await db.get(ReserveOrder, order_id)).agent_trace == trace


async def test_update_trace_is_idempotent_on_identical_write():
    """同一份 trace 补写两次都要返回 `ok`。

    这条是给 MySQL 的 `affected_rows` 立的护栏：它默认只数**真正发生变化**的行，若实现
    被"简化"成单条 `UPDATE`，第二次补写会返回 0 行、被误判成 `not_found`。SQLite 上两种
    写法都能过，所以必须在**返回值**层面钉住，光看库里最终对不对是抓不到的。
    """
    order_id = (await _call())["orderId"]
    trace = [{"step": 1, "result": "解析需求", "timestamp": "2026-01-01 09:00:00"}]

    first = await _call_trace(order_id=order_id, agent_trace=trace)
    second = await _call_trace(order_id=order_id, agent_trace=trace)

    assert first["ok"] is True and second["ok"] is True
    assert second["conflictType"] is None


async def test_update_trace_rejects_other_users_order():
    """越权：别人的单与不存在的单**同一处理**，既不泄露存在性，也不得改动内容。"""
    order_id = (await _call())["orderId"]  # 归 MOCK_USER_ID
    original = [{"step": 1, "result": "原始链路", "timestamp": "2026-01-01 09:00:00"}]
    assert (await _call_trace(order_id=order_id, agent_trace=original))["ok"] is True

    stolen = [{"step": 1, "result": "篡改", "timestamp": "2026-01-01 09:00:00"}]
    r = await _call_trace(order_id=order_id, user_id=OTHER_USER_ID, agent_trace=stolen)

    assert r["ok"] is False and r["conflictType"] == "not_found"
    assert r["reason"] == "预约不存在", "越权与不存在必须同一个说法（403 会泄露存在性）"

    async with AsyncSessionLocal() as db:
        assert (await db.get(ReserveOrder, order_id)).agent_trace == original


async def test_update_trace_rejects_empty_and_non_list():
    """空数组与非数组一律 `invalid_param`，且被拒的调用不得动库里已有的值。

    空数组拒绝是刻意的：它在库里与 `NULL`（尚未生成）区分不开，写进去只会让前端把
    「没跑出东西」渲染成一条空链路。
    """
    order_id = (await _call())["orderId"]

    empty = await _call_trace(order_id=order_id, agent_trace=[])
    assert empty["ok"] is False and empty["conflictType"] == "invalid_param"
    assert "空" in empty["reason"]

    for bad_value in ({"step": 1}, "[]", None, 1):
        r = await _call_trace(order_id=order_id, agent_trace=bad_value)
        assert r["ok"] is False and r["conflictType"] == "invalid_param"

    async with AsyncSessionLocal() as db:
        assert (await db.get(ReserveOrder, order_id)).agent_trace is None


async def test_update_trace_requires_user_id_and_valid_order_id():
    """`user_id` 忘传（Agent 侧最容易漏的一环）与非法 `order_id` 都要在入库前挡住。"""
    for missing in (None, 0, -1, "abc"):
        r = await _call_trace(user_id=missing)
        assert r["ok"] is False and r["conflictType"] == "invalid_param"
        assert "user_id" in r["reason"]

    for bad_id in (None, 0, -1, "abc"):
        r = await _call_trace(order_id=bad_id)
        assert r["ok"] is False and r["conflictType"] == "invalid_param"


def test_services_package_reexports_are_the_same_object():
    """`app.services` 的两个别名必须与定义处是**同一个函数对象**。

    `services/__init__.py` 里的 re-export 是给 Tool 层用的稳定入口（§4.3）；写成
    `from .order_service import X` 之外的任何形式（比如重新赋值、包装一层）都会让
    「别名」和「权威定义」在某次改动后悄悄分家，而那种分家不会报错。
    """
    from app.services import create_order as alias_create
    from app.services import update_agent_trace as alias_update

    assert alias_create is create_order
    assert alias_update is order_service.update_agent_trace
