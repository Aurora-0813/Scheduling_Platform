"""Tool 层用例：`AGENT-U-01` / `AGENT-U-02` / `AGENT-U-03` + 契约护栏。

后三个是**护栏用例**（不在阶段 7 的编号表里，但少了它们，三处「两处必须同时改」
的注释就只是注释）：`lock_resources` 的 `conflictType` 枚举、`submit_plan` 的字段集、
`/api/v1/tools/*` 的存在性。它们各自守着一条**跨文件的一致性**，靠人读注释守不住。
"""
from __future__ import annotations

import importlib
import inspect

from app.agent.context import agent_run_context
from app.agent.tools import AGENT_TOOLS
from app.agent.tools.generate_notification import OrderInfo, generate_notification
from app.agent.tools.lock_resources import LockResourcesArgs, lock_resources
from app.agent.tools.query_devices import query_devices
from app.agent.tools.query_spaces import SPACE_TYPE_LABELS, query_spaces
from app.agent.tools.submit_plan import PlanPayload


# ==========================================================================
# AGENT-U-01：query_spaces 参数异常 → 业务错误，不抛未捕获异常
# ==========================================================================
async def test_u01_query_spaces_rejects_zero_capacity() -> None:
    """容量为 0：返回业务失败，不是异常。

    两层防护都在：`QuerySpacesArgs.capacity` 的 `gt=0`（Pydantic 层）与本函数内的
    显式判断。用例直接用 `.coroutine()` 绕过 Pydantic 层，验的是**函数内那一层**
    ——模型给的数字不保证合理，函数自己也得挡。
    """
    result = await query_spaces.coroutine(
        capacity=0, space_type=2,
        start_time="2026-10-15 09:00:00", end_time="2026-10-15 11:00:00",
    )

    assert result["ok"] is False
    assert "capacity" in result["reason"]
    # 失败时也必须带空集：模型侧读 result["spaces"] 不能 KeyError
    assert result["spaces"] == []
    assert result["count"] == 0


async def test_u01_query_spaces_rejects_reversed_time() -> None:
    """时段倒置：结束早于开始。"""
    result = await query_spaces.coroutine(
        capacity=40, space_type=2,
        start_time="2026-10-15 16:00:00", end_time="2026-10-15 11:00:00",
    )

    assert result["ok"] is False
    assert "时段倒置" in result["reason"]
    assert result["spaces"] == []


async def test_u01_query_spaces_rejects_unparsable_time() -> None:
    """时间格式无法解析。模型给的格式不保证唯一，解不出要明确说，不要猜。"""
    result = await query_spaces.coroutine(
        capacity=40, space_type=2,
        start_time="下周五下午", end_time="2026-10-15 17:00:00",
    )

    assert result["ok"] is False
    assert "无法解析" in result["reason"]


async def test_u01_query_spaces_rejects_out_of_range_space_type() -> None:
    """`space_type=9` 不在 1~4，返回失败而不是静默查空。"""
    result = await query_spaces.coroutine(
        capacity=40, space_type=9,
        start_time="2026-10-15 09:00:00", end_time="2026-10-15 11:00:00",
    )

    assert result["ok"] is False
    assert "space_type" in result["reason"]


async def test_u01_query_spaces_bad_inputs_never_raise(seed: dict) -> None:
    """把一批坏输入全跑一遍，断言**一条异常都没抛出来**。

    单条断言只能证明「这一种坏输入不炸」；阶段 4 的完成判定原文是
    「返回业务错误而非抛异常」，那是个**全称**命题，得用一组输入去逼。
    """
    bad_cases = [
        {"capacity": 0, "space_type": 2, "start_time": "2026-10-15 09:00:00", "end_time": "2026-10-15 11:00:00"},
        {"capacity": -5, "space_type": 2, "start_time": "2026-10-15 09:00:00", "end_time": "2026-10-15 11:00:00"},
        {"capacity": 40, "space_type": 0, "start_time": "2026-10-15 09:00:00", "end_time": "2026-10-15 11:00:00"},
        {"capacity": 40, "space_type": 5, "start_time": "2026-10-15 09:00:00", "end_time": "2026-10-15 11:00:00"},
        {"capacity": 40, "space_type": 2, "start_time": "", "end_time": ""},
        {"capacity": 40, "space_type": 2, "start_time": "not-a-time", "end_time": "also-not"},
        {"capacity": 40, "space_type": 2, "start_time": "2026-10-15 12:00:00", "end_time": "2026-10-15 12:00:00"},
    ]
    for case in bad_cases:
        result = await query_spaces.coroutine(**case)  # 抛异常则用例失败
        assert result["ok"] is False, f"这组参数本该失败：{case}"


# ==========================================================================
# AGENT-U-02：query_devices 过滤可用性
# ==========================================================================
async def test_u02_service_returns_the_bad_devices(seed: dict) -> None:
    """**先立见证者**：service 桩必须把坏设备也返回，否则下面的过滤用例是假绿。

    这是本用例存在的唯一理由。若哪天有人「顺手」把过滤下沉到 service，
    结果里再也见不到 id 13 / 15，这里会先红——而此时正确结论是**回退那次下沉**，
    不是删掉本用例。
    """
    from app.services import query_devices as service_query_devices

    drones = await service_query_devices(device_type="无人机")
    lives = await service_query_devices(device_type="直播设备")

    assert seed["drone_broken"] in [d["id"] for d in drones["devices"]], (
        "service 桩把损坏设备滤掉了——过滤必须留在 Tool 层，见 query_devices.py 顶部说明"
    )
    assert seed["live_exhausted"] in [d["id"] for d in lives["devices"]], (
        "service 桩把零库存设备滤掉了——同上"
    )


async def test_u02_tool_filters_damaged_device(seed: dict) -> None:
    """`device_status != 1` 必须被滤掉：id=13 无人机02 是损坏状态。"""
    result = await query_devices.coroutine(device_type="无人机")

    ids = [d["id"] for d in result["devices"]]
    assert seed["drone_broken"] not in ids, "损坏设备（deviceStatus=2）泄漏给了模型"
    assert seed["drone_ok"] in ids
    assert all(d["deviceStatus"] == 1 for d in result["devices"])


async def test_u02_tool_filters_exhausted_device(seed: dict) -> None:
    """`available_count <= 0` 必须被滤掉：id=15 直播设备02 库存为 0。"""
    result = await query_devices.coroutine(device_type="直播设备")

    ids = [d["id"] for d in result["devices"]]
    assert seed["live_exhausted"] not in ids, "零库存设备（availableCount=0）泄漏给了模型"
    assert seed["live_ok"] in ids
    assert all(d["availableCount"] > 0 for d in result["devices"])


async def test_u02_filters_are_witnessed_independently(seed: dict) -> None:
    """两个坏样本各由**一个不同的**条件筛掉，才能分辨是哪条过滤在起作用。

    若两个样本都被同一个条件筛掉，改错另一条也看不出来。
    - id 13：status=2 但 available=1 → **只**该被状态条件筛掉
    - id 15：status=1 但 available=0 → **只**该被数量条件筛掉
    """
    from app.services import query_devices as service_query_devices

    raw = {d["id"]: d for d in (await service_query_devices(device_type="无人机"))["devices"]}
    assert raw[seed["drone_broken"]]["deviceStatus"] == 2
    assert raw[seed["drone_broken"]]["availableCount"] > 0

    raw = {d["id"]: d for d in (await service_query_devices(device_type="直播设备"))["devices"]}
    assert raw[seed["live_exhausted"]]["deviceStatus"] == 1
    assert raw[seed["live_exhausted"]]["availableCount"] == 0


async def test_u02_all_unavailable_gets_a_different_message(seed: dict) -> None:
    """「类型存在但全不可借」与「类型名不存在」要给**不同**的 reason。

    模型与用户在这两种情况下的下一步动作不同（前者该换类型或改期，后者该换词重查）。
    返回同一个空洞会让模型无从选择。
    """
    unknown = await query_devices.coroutine(device_type="投影幕布")

    assert unknown["ok"] is False
    assert "未找到类型" in unknown["reason"]
    # 把可用类型列出来，模型才能自我纠正
    assert "投影仪" in unknown["reason"]


async def test_u02_empty_device_type_rejected() -> None:
    result = await query_devices.coroutine(device_type="   ")
    assert result["ok"] is False
    assert result["devices"] == []


# ==========================================================================
# AGENT-U-03：space_type 映射（「展厅」→ 2）
# ==========================================================================
def test_u03_int_dictionary_is_exactly_the_6_3_table() -> None:
    """INT 字典与主文档 6.3 表 4 逐项一致。

    这是 Prompt 与 Tool 共用的那一份对照表；错一个数字，模型会把「展厅」传到
    会议室上去，而查询本身不会报错——只是返回错的东西。
    """
    assert SPACE_TYPE_LABELS == {1: "会议室", 2: "展厅", 3: "多功能厅", 4: "户外场地"}


def test_u03_prompt_carries_the_dictionary() -> None:
    """对照表必须出现在 Prompt 里。

    模型收到的是自然语言「展厅」，Tool 收的是 `2`。**不给对照表就指望模型猜数字**，
    场景 A/B 会大面积失败——而失败方式是「查不到场地」，看不出是映射错了。
    """
    from app.agent.prompts.scheduler import build_scheduler_prompt

    prompt = build_scheduler_prompt()
    for number, label in SPACE_TYPE_LABELS.items():
        assert label in prompt, f"Prompt 缺少场地类型「{label}」"
        assert str(number) in prompt, f"Prompt 缺少场地类型编号 {number}"


async def test_u03_hall_maps_to_type_2_end_to_end(seed: dict) -> None:
    """「展厅」对应的 `space_type=2` 真的只返回展厅。

    验的是端到端一致：字典说展厅是 2 → 传 2 → 返回的 `spaceType` 全是 2。
    若哪天种子数据把某场地的 `space_type` 写错，这里会红。

    容量取 35 而不是 40：**两个展厅都要进结果**（cap 50 与 cap 35），这条才验得到「映射」；
    若取 40，cap=35 的那个会被下界滤掉，断言的集合里只剩一个元素，
    「返回的是不是展厅」这件事就只剩一个样本。容量下界本身由
    `test_u03_capacity_is_a_lower_bound` 单独验。
    """
    # 反向查字典：「展厅」这个名字对应的编号。**不写死 2**——写死的话，字典改了这条用例
    # 会一起错过去，而它恰恰是验映射的。
    space_type_no = {label: no for no, label in SPACE_TYPE_LABELS.items()}["展厅"]
    assert space_type_no == 2

    result = await query_spaces.coroutine(
        capacity=35, space_type=space_type_no,
        start_time="2026-10-15 09:00:00", end_time="2026-10-15 11:00:00",
    )

    assert result["ok"] is True
    assert result["count"] >= 1
    assert all(s["spaceType"] == 2 for s in result["spaces"])
    assert {s["id"] for s in result["spaces"]} == {seed["space_hall_40"], seed["space_hall_35"]}


async def test_u03_capacity_is_a_lower_bound(seed: dict) -> None:
    """容量取「≥」：要 40 人的展厅，50 人的那个要在结果里。"""
    result = await query_spaces.coroutine(
        capacity=40, space_type=2,
        start_time="2026-10-15 09:00:00", end_time="2026-10-15 11:00:00",
    )
    ids = {s["id"] for s in result["spaces"]}
    assert seed["space_hall_40"] in ids          # cap=50 ≥ 40
    assert seed["space_hall_35"] not in ids      # cap=35 < 40

    result = await query_spaces.coroutine(
        capacity=30, space_type=2,
        start_time="2026-10-15 09:00:00", end_time="2026-10-15 11:00:00",
    )
    assert {s["id"] for s in result["spaces"]} == {seed["space_hall_40"], seed["space_hall_35"]}


# ==========================================================================
# lock_resources：冲突路径（阶段 4 §3.3 要求失败必须结构化，模型才能转备选方案）
# ==========================================================================
async def test_lock_resources_fails_closed_without_identity() -> None:
    """没有调用上下文（=读不到身份）时必须失败，**绝不编造一个 user_id 顶上**。

    这是越权防线的最后一道：`get_agent_user_id()` 默认 None，若这里写个兜底值，
    任何绕过 API 层直接调 Tool 的路径都能替人下单。
    """
    result = await lock_resources.coroutine(
        space_id=4, device_ids=[],
        start_time="2026-10-15 09:00:00", end_time="2026-10-15 11:00:00",
    )

    assert result["ok"] is False
    assert result["conflictType"] == "invalid_param"
    assert result["retryable"] is False
    assert result["actionHint"] is None


async def test_lock_resources_time_conflict_is_retryable(seed: dict, slots: dict) -> None:
    """`AGENT-S-04` / 场景 B 成立的前提：时段冲突要**可重试**且给出下一步动作。

    `reserve_order` id=9 在 space 4 的这个时段上（`order_status=1` 待确认，
    按 `OCCUPYING_STATUS=(1,2)` 占位）。模型收到 `retryable=true` 才会去想
    「换个场地或拆成两场」；收到 `retryable=false` 只能宣布失败。
    """
    start, end = slots["occupied"]
    with agent_run_context(user_id=1, raw_request="测试：时段冲突"):
        result = await lock_resources.coroutine(
            space_id=seed["space_hall_40"], device_ids=[], start_time=start, end_time=end,
        )

    assert result["ok"] is False
    assert result["conflictType"] == "time_conflict"
    assert result["retryable"] is True
    assert result["actionHint"], "冲突必须给模型下一步动作，否则它只能原地重试"
    # conflictDetail 要能被前端屏 3 直接渲染
    assert result["conflictDetail"]["spaceId"] == seed["space_hall_40"]


async def test_lock_resources_device_not_found_is_retryable(seed: dict) -> None:
    with agent_run_context(user_id=1, raw_request="测试：设备不存在"):
        result = await lock_resources.coroutine(
            space_id=seed["space_hall_40"], device_ids=[999_999],
            start_time="2026-10-15 09:00:00", end_time="2026-10-15 11:00:00",
        )

    assert result["ok"] is False
    assert result["conflictType"] == "not_found"
    assert result["retryable"] is True


async def test_lock_resources_damaged_device_is_device_conflict(seed: dict) -> None:
    """借损坏设备（id=13）：`device_conflict`，且 `reason` 能区分是哪一种。

    对齐后的口径：设备类的两种情形**共用** `device_conflict`，
    靠 `conflictDetail.conflicts[].reason` 区分 `status` 与 `exhausted`。
    """
    with agent_run_context(user_id=1, raw_request="测试：损坏设备"):
        result = await lock_resources.coroutine(
            space_id=seed["space_hall_40"], device_ids=[seed["drone_broken"]],
            start_time="2026-10-15 09:00:00", end_time="2026-10-15 11:00:00",
        )

    assert result["ok"] is False
    assert result["conflictType"] == "device_conflict"
    assert result["conflictDetail"]["conflicts"][0]["reason"] == "status"


async def test_lock_resources_exhausted_device_is_device_conflict(seed: dict) -> None:
    """借零库存设备（id=15）：同 `device_conflict`，但 reason 是 `exhausted`。"""
    with agent_run_context(user_id=1, raw_request="测试：零库存设备"):
        result = await lock_resources.coroutine(
            space_id=seed["space_hall_40"], device_ids=[seed["live_exhausted"]],
            start_time="2026-10-15 09:00:00", end_time="2026-10-15 11:00:00",
        )

    assert result["ok"] is False
    assert result["conflictType"] == "device_conflict"
    assert result["conflictDetail"]["conflicts"][0]["reason"] == "exhausted"


async def test_lock_resources_reversed_time_is_not_retryable(seed: dict) -> None:
    """参数本身非法 → `retryable=false`，因为「原样重发」不可能变好。"""
    with agent_run_context(user_id=1, raw_request="测试：时段倒置"):
        result = await lock_resources.coroutine(
            space_id=seed["space_hall_40"], device_ids=[],
            start_time="2026-10-15 17:00:00", end_time="2026-10-15 13:00:00",
        )

    assert result["ok"] is False
    assert result["conflictType"] == "invalid_param"
    assert result["retryable"] is False


async def test_lock_resources_free_slot_passes_validation(seed: dict, slots: dict) -> None:
    """空时段 + 完好设备 → 走到桩的成功分支。

    ⚠️ 断言里**刻意不断言 `orderId` 是整数**：桩不落库，`orderId` 恒为 `None`。
    断言 `stub is True` 是**桩期临时代码**——真实 `create_order` 落地后这一行要删
    （`order_service.py` 顶部明文要求：「任何断言 `stub` 的代码都是桩期临时代码」）。
    """
    start, end = slots["free"]
    with agent_run_context(user_id=1, raw_request="测试：空时段成功"):
        result = await lock_resources.coroutine(
            space_id=seed["space_hall_40"], device_ids=seed["projectors"][:2],
            start_time=start, end_time=end,
        )

    assert result["ok"] is True
    assert result["orderId"] is None          # 桩不落库
    assert result["stub"] is True             # ← 桩期临时断言，替换真实实现时删除


async def test_lock_resources_rejects_string_device_ids(seed: dict) -> None:
    """`device_ids="1"` 必须被**拒绝**，不能静默变成 `[1]`。

    `for x in "1"` 会逐字符迭代，结果恰好是 `[1]`——错得无声无息，比报错危险得多。
    这条在 `order_service` 里挡，用例在 Tool 这一层验，两边都不能漏。
    """
    with agent_run_context(user_id=1, raw_request="测试：字符串设备 ID"):
        result = await lock_resources.coroutine(
            space_id=seed["space_hall_40"], device_ids="1",  # type: ignore[arg-type]
            start_time="2026-10-15 09:00:00", end_time="2026-10-15 11:00:00",
        )

    assert result["ok"] is False
    assert result["conflictType"] == "invalid_param"
    assert "数组" in result["reason"]


# ==========================================================================
# generate_notification
# ==========================================================================
async def test_generate_notification_mapped_type_succeeds() -> None:
    # 传 `OrderInfo` 实例而不是裸 dict：`args_schema` 把模型交来的参数**转成模型**
    # 之后才调本函数（Agent 路径实测如此），所以这里必须按生产形状传，
    # 否则用例在验一个生产上不存在的调用方式。
    result = await generate_notification.coroutine(order_info=OrderInfo(
        notifyType="预约提醒", spaceName="A栋3楼展厅",
        startTime="2026-10-15 09:00:00", endTime="2026-10-15 11:00:00",
    ))

    assert result["ok"] is True
    assert result["notifyType"] == 1
    assert result["title"]
    assert "A栋3楼展厅" in result["content"], "场地名要落进正文，否则文案没有信息量"


async def test_generate_notification_unmapped_type_fails_closed() -> None:
    """「延期致歉」在 6.3 的 INT 字典内没有值 → `ok=false`，**不擅自映射**。

    未决 #6（黄嵩 + 集成组）。映射到 2(变更致歉) 会让落库类型与前端文案错配；
    新增 4 要先改字典。所以这里必须**失败并说明原因**，不能猜一个数字顶上。
    等未决 #6 拍板后，本用例的期望值要跟着改。
    """
    result = await generate_notification.coroutine(order_info=OrderInfo(notifyType="延期致歉"))

    assert result["ok"] is False
    assert "无对应 INT 值" in result["reason"]
    assert result["title"] is None


async def test_generate_notification_unknown_type_lists_valid_ones() -> None:
    result = await generate_notification.coroutine(order_info=OrderInfo(notifyType="活动通知"))

    assert result["ok"] is False
    assert "预约提醒" in result["reason"], "要告诉模型合法取值，否则它只能反复猜"


# ==========================================================================
# 契约护栏
# ==========================================================================
def test_guard_lock_resources_conflict_enum_matches_service() -> None:
    """`lock_resources` 里按字面复制的 `_RETRYABLE` 必须与 `order_service` 的常量一致。

    `lock_resources.py` 顶部解释了为什么不直接 import 常量再比对
    （避免两个模块对同一份枚举产生隐性耦合）。代价就是**改了一边会漏另一边**，
    本用例是那个代价的补偿。
    """
    # ⚠️ **不能**写 `from app.agent.tools import lock_resources as lr`：包 `__init__` 里
    # `from app.agent.tools.lock_resources import lock_resources` 把包属性 `lock_resources`
    # 覆盖成了**工具对象**，这样取到的是 StructuredTool，读 `_RETRYABLE` 会 AttributeError。
    # 取模块要用 `importlib.import_module`（它返回 `sys.modules` 里的模块本体）。
    lr = importlib.import_module("app.agent.tools.lock_resources")
    from app.services import order_service as osvc

    service_types = {
        osvc.CONFLICT_TIME,
        osvc.CONFLICT_DEVICE_MISSING,
        osvc.CONFLICT_DEVICE_UNAVAILABLE,
        osvc.CONFLICT_DEVICE_SHORTAGE,
        osvc.CONFLICT_INVALID_TIME,
    }
    # 模型可自行重试的三种，必须都在 order_service 的枚举里
    assert lr._RETRYABLE <= service_types, "lock_resources 的可重试集合里有 order_service 不认识的取值"
    # 每个取值都要有行动建议，否则模型收到冲突却不知道下一步做什么
    for conflict_type in service_types:
        assert conflict_type in lr._ACTION_HINT, f"{conflict_type} 缺少 actionHint"
    # 命名口径：snake_case（2026-09-27 与蔡玉礼对齐），不是 SCREAMING_SNAKE
    for conflict_type in service_types:
        assert conflict_type == conflict_type.lower(), f"{conflict_type} 不是 snake_case"


def test_guard_submit_plan_payload_matches_response_schema() -> None:
    """`PlanPayload` 与响应契约 `Plan` 的字段集必须逐字相同。

    两处字段名不一样时，模型交出的字段会在响应里**静默消失**——
    `builder._to_plan()` 用 `allowed = set(Plan.model_fields)` 过滤，
    不在 `Plan` 里的键直接丢掉，不报错。
    """
    from app.schemas.agent import Plan

    assert set(PlanPayload.model_fields) == set(Plan.model_fields), (
        "submit_plan.PlanPayload 与 schemas.agent.Plan 字段集不一致，"
        "模型交的字段会在响应里静默丢失"
    )


async def test_guard_no_tools_routes_registered(client) -> None:  # noqa: ANN001
    """`/api/v1/tools/*` 必须 404（主文档 5.3 / 9.3）。

    工具函数的形状（简单入参、返回 dict）**看起来**天然就是个 REST 接口，
    很容易被「顺手」注册成路由——那样任何人都能绕开 JWT 直接锁资源。
    这条守的是 `app/api/v1/__init__.py` 里那段警告。
    """
    for name in ("query_spaces", "query_devices", "lock_resources",
                 "generate_notification", "submit_plan"):
        resp = await client.get(f"/api/v1/tools/{name}")
        assert resp.status_code == 404, f"/api/v1/tools/{name} 存在——越权口子"
        assert set(resp.json()) == {"code", "message", "data"}


def test_guard_all_tools_are_async() -> None:
    """5 个 Tool 必须全是 `async def`（主文档 3.3 / 7.4）。

    同步函数会在 `ToolNode` 里被丢进线程池跑，`ContextVar` 上下文在那边是另一份，
    `lock_resources` 读身份会读到 `None` ——表现是「明明登录了却说缺身份」。
    """
    assert len(AGENT_TOOLS) == 5
    for tool_obj in AGENT_TOOLS:
        assert inspect.iscoroutinefunction(tool_obj.coroutine), f"{tool_obj.name} 不是 async def"
        assert tool_obj.description, f"{tool_obj.name} 缺 docstring——模型靠它决定调不调"


def test_guard_lock_resources_args_have_no_user_id() -> None:
    """冻结签名里**没有** `user_id`，且不能加。

    加了等于把「替谁预约」交给模型决定，与主文档 5.1/9.1 直接冲突。
    """
    assert "user_id" not in LockResourcesArgs.model_fields
