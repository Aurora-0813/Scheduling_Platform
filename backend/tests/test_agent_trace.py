"""思考链提取用例：`AGENT-U-04` / `AGENT-U-05`。

这两条是本模块契约里最容易被「看起来对」蒙过去的部分：`TraceStep` 的七个字段
只要有一个填错，前端屏 3 的渲染就崩或者缺东西，而**后端不会报任何错**。
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agent.chains import trace as trace_mod
from app.agent.chains.trace import (
    TIMESTAMP_FORMAT,
    build_trace,
    collect_stamped_messages,
    parse_observation,
)


def _ai(text: str = "", calls: list[dict] | None = None, msg_id: str = "m") -> AIMessage:
    kwargs: dict = {"content": text, "id": msg_id}
    if calls:
        kwargs["tool_calls"] = calls
    return AIMessage(**kwargs)


def _tool(content: str, name: str = "query_spaces", call_id: str = "c1", msg_id: str = "t") -> ToolMessage:
    return ToolMessage(content=content, name=name, tool_call_id=call_id, id=msg_id)


def _call(name: str, args: dict, call_id: str = "c1") -> dict:
    return {"name": name, "args": args, "id": call_id}


# ==========================================================================
# AGENT-U-04：messages → TraceStep 映射
# ==========================================================================
def test_u04_ai_and_tool_merge_into_one_step() -> None:
    """`AIMessage`（带 tool_calls）与其后的 `ToolMessage` **合并成一步**。

    拆成两步的话，前端时间轴节点翻倍，且每步都缺一半要素——渲染出来是一串
    「只有动作没有结果」的卡片。
    """
    stamped = [
        (_ai("先查展厅。", [_call("query_spaces", {"capacity": 40, "space_type": 2})]), "2026-09-25 14:00:00"),
        (_tool('{"ok": true, "count": 2, "spaces": []}'), "2026-09-25 14:00:04"),
    ]

    steps = build_trace(stamped)

    assert len(steps) == 1, "一条 AIMessage + 一条 ToolMessage 必须是 1 步，不是 2 步"
    step = steps[0]
    assert step.step == 1
    assert step.thought == "先查展厅。"
    assert step.action == "query_spaces"
    assert step.actionInput == {"capacity": 40, "space_type": 2}
    assert step.observation == {"ok": True, "count": 2, "spaces": []}
    assert step.result                                    # 中文结论非空
    assert step.timestamp == "2026-09-25 14:00:00"        # 打点时刻取**发起**那一步


def test_u04_step_numbers_start_at_one_and_are_dense() -> None:
    """`step` 从 1 开始、连续无空缺。前端按它排序与显示「第 N 步」。"""
    stamped = []
    for index in range(4):
        stamped.append((
            _ai(f"第{index}步", [_call(f"tool_{index}", {}, f"c{index}")], f"m{index}"),
            f"2026-09-25 14:00:0{index}",
        ))
        stamped.append((_tool("{}", f"tool_{index}", f"c{index}", f"t{index}"), f"2026-09-25 14:00:1{index}"))

    steps = build_trace(stamped)

    assert [s.step for s in steps] == [1, 2, 3, 4]


def test_u04_every_step_has_non_empty_result(seed: dict) -> None:
    """`result` 是主文档 5.3 明文要求的必需项，**任何一步都不能空**。"""
    for action in ("query_spaces", "query_devices", "lock_resources",
                   "generate_notification", "submit_plan"):
        steps = build_trace([(_ai("想", [_call(action, {})]), "2026-09-25 14:00:00")])
        assert steps[0].result, f"{action} 这一步的 result 为空"


def test_u04_pure_reasoning_step_has_no_action() -> None:
    """不带 `tool_calls` 的 `AIMessage` 是纯推理步：有 thought、无 action。"""
    steps = build_trace([(_ai("用户要 40 人展厅，先算预算。"), "2026-09-25 14:00:00")])

    assert len(steps) == 1
    assert steps[0].action is None
    assert steps[0].actionInput is None
    assert steps[0].observation is None
    assert steps[0].result == "用户要 40 人展厅，先算预算。", "纯推理步的 result 用 thought 兜底"


def test_u04_parallel_tool_calls_each_become_a_step() -> None:
    """一条 AIMessage 里带多个 `tool_calls` → 每个各起一步。

    模型完全可能一轮里同时查场地和查设备；合并成一步会让其中一次调用的
    actionInput / observation 丢失。
    """
    stamped = [
        (_ai("同时查场地和设备。", [
            _call("query_spaces", {"capacity": 40}, "c1"),
            _call("query_devices", {"device_type": "投影仪"}, "c2"),
        ]), "2026-09-25 14:00:00"),
        (_tool('{"ok": true, "count": 1}', "query_spaces", "c1", "t1"), "2026-09-25 14:00:01"),
        (_tool('{"ok": true, "count": 4}', "query_devices", "c2", "t2"), "2026-09-25 14:00:02"),
    ]

    steps = build_trace(stamped)

    assert [s.action for s in steps] == ["query_spaces", "query_devices"]
    assert steps[0].observation == {"ok": True, "count": 1}
    assert steps[1].observation == {"ok": True, "count": 4}


def test_u04_input_messages_are_not_part_of_trace() -> None:
    """`HumanMessage` / `SystemMessage` 不进 trace——它们是输入，不是思考过程。"""
    stamped = [
        (HumanMessage(content="40 人展厅"), "2026-09-25 14:00:00"),
        (SystemMessage(content="你是调度助手"), "2026-09-25 14:00:00"),
        (_ai("开始推理。"), "2026-09-25 14:00:01"),
    ]

    steps = build_trace(stamped)

    assert len(steps) == 1
    assert steps[0].thought == "开始推理。"


def test_u04_labels_are_chinese() -> None:
    """`result` 是给用户看的中文结论，不能出现英文工具名。"""
    labels = {
        "query_spaces": "查询场地",
        "query_devices": "查询设备",
        "lock_resources": "锁定资源",
        "generate_notification": "生成通知文案",
        "submit_plan": "提交方案",
    }
    for action, label in labels.items():
        steps = build_trace([(_ai("想", [_call(action, {})]), "2026-09-25 14:00:00")])
        assert label in steps[0].result, f"{action} 的 result 没走中文标签：{steps[0].result}"


def test_u04_generate_notification_failure_is_not_silently_labeled_success() -> None:
    """通知生成失败时，`result` 必须写明失败——**不能只显示标签**。

    这是一个真实踩过的坑：`notifyType="活动通知"` 不在 6.3 字典内，service 返回
    `ok=False`，而 `_summarize` 早期只认 `title`，取不到就退回标签「生成通知文案」，
    看 trace 完全看不出这一步其实失败了。
    """
    failed = _tool('{"ok": false, "title": null, "content": null, "reason": "未知的通知类型"}',
                   "generate_notification")
    steps = build_trace([(_ai("发通知", [_call("generate_notification", {})]), "2026-09-25 14:00:00"), (failed, "2026-09-25 14:00:01")])

    assert "失败" in steps[0].result
    assert "未知的通知类型" in steps[0].result

    ok = _tool('{"ok": true, "title": "预约成功提醒"}', "generate_notification")
    steps = build_trace([(_ai("发通知", [_call("generate_notification", {})]), "2026-09-25 14:00:00"), (ok, "2026-09-25 14:00:01")])
    assert "预约成功提醒" in steps[0].result


def test_u04_lock_resources_distinguishes_persisted_from_stub() -> None:
    """有订单号与没落库要能一眼分辨（桩期 `orderId` 恒为 None）。"""
    persisted = _tool('{"ok": true, "orderId": 12}', "lock_resources")
    steps = build_trace([(_ai("锁定", [_call("lock_resources", {})]), "2026-09-25 14:00:00"), (persisted, "2026-09-25 14:00:01")])
    assert "订单 12" in steps[0].result

    stub = _tool('{"ok": true, "orderId": null}', "lock_resources")
    steps = build_trace([(_ai("锁定", [_call("lock_resources", {})]), "2026-09-25 14:00:00"), (stub, "2026-09-25 14:00:01")])
    assert "未落库" in steps[0].result, "桩期必须自证未落库，否则看不出这是假预约"

    conflicted = _tool('{"ok": false, "conflictType": "time_conflict"}', "lock_resources")
    steps = build_trace([(_ai("锁定", [_call("lock_resources", {})]), "2026-09-25 14:00:00"), (conflicted, "2026-09-25 14:00:01")])
    assert "time_conflict" in steps[0].result


def test_u04_result_is_clipped() -> None:
    """`result` 有长度上限——前端卡片放不下长文本。"""
    long_reason = "很长的原因" * 40
    steps = build_trace([(
        _ai("想", [_call("query_spaces", {})]),
        "2026-09-25 14:00:00",
    ), (_tool(f'{{"ok": false, "reason": "{long_reason}"}}'), "2026-09-25 14:00:01")])

    assert len(steps[0].result) <= trace_mod._RESULT_MAX_LEN


def test_u04_pending_observation_is_marked_as_such() -> None:
    """工具已发起、结果还没回来时（如超时中断），要写明「尚未返回结果」。"""
    steps = build_trace([(_ai("查场地", [_call("query_spaces", {})]), "2026-09-25 14:00:00")])

    assert steps[0].observation is None
    assert "尚未返回结果" in steps[0].result


# ==========================================================================
# AGENT-U-05：timestamp 唯一且严格递增
# ==========================================================================
def test_u05_timestamps_are_unique_and_strictly_increasing() -> None:
    """冻结契约的明文承诺：各步 `timestamp` **互不相同且递增**，可直接用于时间轴回放。

    这里刻意喂**同一秒**的多个步骤（假模型下必然发生，真实调用下也可能）
    ——按原值输出就违反契约，前端回放会出现两节点重叠。
    """
    stamped = [
        (_ai("第一步", [_call("query_spaces", {})]), "2026-09-25 14:00:00"),
        (_tool("{}", "query_spaces"), "2026-09-25 14:00:00"),
        (_ai("第二步", [_call("query_devices", {})]), "2026-09-25 14:00:00"),
        (_tool("{}", "query_devices"), "2026-09-25 14:00:00"),
        (_ai("第三步", [_call("lock_resources", {})]), "2026-09-25 14:00:00"),
    ]

    steps = build_trace(stamped)
    stamps = [s.timestamp for s in steps]

    assert len(stamps) == 3
    assert len(set(stamps)) == len(stamps), f"时间戳有重复：{stamps}"

    parsed = [datetime.strptime(s, TIMESTAMP_FORMAT) for s in stamps]
    assert parsed == sorted(parsed) and len(set(parsed)) == len(parsed), f"时间戳未严格递增：{stamps}"


def test_u05_out_of_order_timestamps_are_forced_forward() -> None:
    """后一步的时刻早于前一步时，顺延到前一步之后，**不原地回退**。

    时钟回拨或并发打点错序都可能造出这种输入。
    """
    stamped = [
        (_ai("A", [_call("query_spaces", {})]), "2026-09-25 14:00:10"),
        (_ai("B", [_call("query_devices", {})]), "2026-09-25 14:00:05"),
    ]

    steps = build_trace(stamped)

    assert steps[0].timestamp == "2026-09-25 14:00:10"
    assert steps[1].timestamp == "2026-09-25 14:00:11", "乱序必须被推后，不能被原样保留"


def test_u05_unparsable_timestamp_is_left_alone() -> None:
    """解析不了的时刻**原样保留**，不猜一个值往下推。

    顺延的前提是能比较；宁可让异常值暴露，也不要拿猜的时间继续推——
    那会把一个数据问题伪装成一串看起来正常的时刻。
    """
    stamped = [
        (_ai("A", [_call("query_spaces", {})]), "不是时间"),
        (_ai("B", [_call("query_devices", {})]), "2026-09-25 14:00:00"),
    ]

    steps = build_trace(stamped)

    assert steps[0].timestamp == "不是时间"
    assert steps[1].timestamp == "2026-09-25 14:00:00"


def test_u05_every_step_matches_the_frozen_format() -> None:
    """格式必须是 `YYYY-MM-DD HH:mm:ss`——前端按它 `new Date()` 解析。"""
    stamped = [
        (_ai("A", [_call("query_spaces", {})]), "2026-09-25 14:00:00"),
        (_ai("B", [_call("query_devices", {})]), "2026-09-25 14:00:01"),
    ]

    for step in build_trace(stamped):
        datetime.strptime(step.timestamp, TIMESTAMP_FORMAT)  # 格式不符即抛


# ==========================================================================
# parse_observation：ToolMessage.content 是字符串
# ==========================================================================
@pytest.mark.parametrize(
    "content",
    [
        '{"ok": true, "count": 2}',              # json.dumps（双引号）
        "{'ok': True, 'count': 2}",              # str()（Python 字面量、单引号、True 大写）
    ],
)
def test_observation_parses_both_serialization_styles(content: str) -> None:
    """框架序列化 Tool 返回值的方式不保证唯一，两种都得认。

    只认一种的话，另一种会静默退回 `{"text": ...}`，前端屏 3 的工具结果卡片
    就变成一整坨字符串而不是结构化字段。
    """
    assert parse_observation(content) == {"ok": True, "count": 2}


def test_observation_never_drops_the_field() -> None:
    """解析不出也要保留原文，**不允许因为解析不了就丢字段**。"""
    assert parse_observation("这是一段普通文本") == {"text": "这是一段普通文本"}
    assert parse_observation("") is None
    assert parse_observation(None) is None
    assert parse_observation({"already": "dict"}) == {"already": "dict"}
    assert parse_observation([1, 2]) == {"content": [1, 2]}
    # 非 JSON 的标量统一进 `text`（**不是** `value`）：Tool 返回裸数字/布尔的情形极少，
    # 给它单独一个键会让前端多写一条分支，而 `text` 这条分支本来就有。
    assert parse_observation(42) == {"text": "42"}


# ==========================================================================
# collect_stamped_messages：边收边打点，以及退路
# ==========================================================================
class _FakeAgent:
    """`collect_stamped_messages` 的最小替身：只实现它用到的两个方法。"""

    def __init__(self, chunks: list | None = None, *, raise_type_error: bool = False,
                 result: dict | None = None) -> None:
        self._chunks = chunks or []
        self._raise = raise_type_error
        self._result = result or {"messages": []}
        self.astream_called = False
        self.ainvoke_called = False

    async def astream(self, inputs, stream_mode=None, config=None):  # noqa: ANN001, ANN201
        self.astream_called = True
        if self._raise:
            raise TypeError("stream_mode 'updates' 不被支持")
        for chunk in self._chunks:
            yield chunk

    async def ainvoke(self, inputs, config=None):  # noqa: ANN001, ANN201
        self.ainvoke_called = True
        return self._result


async def test_collect_uses_astream_and_stamps_each_message(monkeypatch) -> None:  # noqa: ANN001
    """正常路径走 `astream(stream_mode="updates")`，**每条消息收到时就地打点**。

    这是「时间轴是真的」的全部机制。若某天退化成「跑完统一打点」，
    40 秒的思考过程会在前端变成一个瞬间——而用例不会红，因为字段都还在。
    所以这里用一个会**按序推进时钟**的 `now_str` 替身把机制验出来。
    """
    ticks = iter([f"2026-09-25 14:00:0{i}" for i in range(10)])
    monkeypatch.setattr(trace_mod, "now_str", lambda: next(ticks))

    agent = _FakeAgent([
        {"model": {"messages": [_ai("第一步", [_call("query_spaces", {})], "m1")]}},
        {"tools": {"messages": [_tool("{}", "query_spaces", "c1", "t1")]}},
        {"model": {"messages": [_ai("第二步", [_call("query_devices", {})], "m2")]}},
    ])

    stamped = await collect_stamped_messages(agent, {"messages": []})

    assert agent.astream_called and not agent.ainvoke_called
    assert [ts for _, ts in stamped] == [
        "2026-09-25 14:00:00", "2026-09-25 14:00:01", "2026-09-25 14:00:02",
    ], "打点必须是「收到那一刻」，不是事后统一"
    assert len(build_trace(stamped)) == 2


async def test_collect_deduplicates_replayed_messages(monkeypatch) -> None:  # noqa: ANN001
    """同一对象被重放（部分 LangGraph 小版本在流式收尾时会重放最后一条 state）→ 只记一次。

    不去重的话 trace 尾部会出现重复步骤，前端时间轴多出两个节点。
    """
    monkeypatch.setattr(trace_mod, "now_str", lambda: "2026-09-25 14:00:00")

    first = _ai("第一步", [_call("query_spaces", {})], "m1")
    agent = _FakeAgent([
        {"model": {"messages": [first]}},
        {"model": {"messages": [first]}},   # 同一条被重放
        {"model": {"messages": [first]}},
    ])

    stamped = await collect_stamped_messages(agent, {"messages": []})

    assert len(stamped) == 1
    assert len(build_trace(stamped)) == 1


async def test_collect_falls_back_to_ainvoke_on_type_error(monkeypatch) -> None:  # noqa: ANN001
    """`updates` 形状不被支持时退回 `ainvoke()`，**但时间标签退化成保序顺延**。

    这是**有意接受的降级**：宁可「时间轴被拉开」，也不要静默地全部同秒。
    本条用例把这条退路钉住——退路本身要能出结果，且结果要过严格递增那一关。
    """
    monkeypatch.setattr(trace_mod, "now_str", lambda: "2026-09-25 14:00:00")

    agent = _FakeAgent(
        raise_type_error=True,
        result={"messages": [
            _ai("第一步", [_call("query_spaces", {})], "m1"),
            _tool("{}", "query_spaces", "c1", "t1"),
            _ai("第二步", [_call("query_devices", {"device_type": "投影仪"})], "m2"),
        ]},
    )

    stamped = await collect_stamped_messages(agent, {"messages": []})

    assert agent.ainvoke_called
    assert len(stamped) == 3
    # 三条消息同一秒进来（now_str 被钉死），靠严格递增拉开成两步两个时刻
    steps = build_trace(stamped)
    assert [s.action for s in steps] == ["query_spaces", "query_devices"]
    assert [s.timestamp for s in steps] == ["2026-09-25 14:00:00", "2026-09-25 14:00:01"]


async def test_collect_keeps_existing_sink_content_on_fallback(monkeypatch) -> None:  # noqa: ANN001
    """退回 `ainvoke` 时，sink 里**已有的**步骤不能被重复一遍。

    超时路径会带着一个已经装了几步的 sink 进来；不清理本次尝试新增的部分再重来，
    前面几步会在 trace 里出现两次。
    """
    monkeypatch.setattr(trace_mod, "now_str", lambda: "2026-09-25 14:00:00")

    existing = _ai("已经跑过的一步", [_call("query_spaces", {})], "old")
    sink = [(existing, "2026-09-25 13:59:59")]

    agent = _FakeAgent(
        chunks=[{"model": {"messages": [_ai("半截", [_call("query_devices", {})], "half")]}}],
        raise_type_error=False,
    )
    # 让 astream 先吐一条、再抛 TypeError，模拟「流到一半形状不对」
    async def _astream(inputs, stream_mode=None, config=None):  # noqa: ANN001, ANN201
        yield {"model": {"messages": [_ai("半截", [_call("query_devices", {})], "half")]}}
        raise TypeError("流中途形状不对")

    agent.astream = _astream  # type: ignore[method-assign]

    stamped = await collect_stamped_messages(agent, {"messages": []}, sink=sink)

    assert stamped[0][0] is existing, "sink 里原有的一步必须保留"
    ids = [id(m) for m, _ in stamped]
    assert len(ids) == len(set(ids)), "同一条消息不能出现两次"


async def test_collect_returns_the_same_sink_object() -> None:
    """传了 `sink` 就**原地追加并返回同一个列表**。

    超时（`wait_for` 取消协程）时返回值根本拿不到，调用方只能靠这个引用
    拿到「已经思考到第几步」——列表对象不是同一个，这条就断了。
    """
    sink: list = []
    agent = _FakeAgent([{"model": {"messages": [_ai("一步", [_call("query_spaces", {})])]}}])

    returned = await collect_stamped_messages(agent, {"messages": []}, sink=sink)

    assert returned is sink
    assert len(sink) == 1


def test_now_str_matches_contract_format() -> None:
    datetime.strptime(trace_mod.now_str(), TIMESTAMP_FORMAT)
