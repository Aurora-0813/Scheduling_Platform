"""端到端调度的用例：`AGENT-S-01~06`（决策场景）、`AGENT-E-01~04`（异常与降级）、
`AGENT-I-01~05`（接口）。

## 假模型在这里扮演什么角色，以及它证明不了什么

用例把 `builder.build_model` 换成 `ScriptedChatModel`，**其余全是真的**：
真的 `create_agent` 组装、真的 ToolNode、真的工具查开发库、真的 trace 提取、
真的统一响应体。所以「系统把模型的意图变成合规响应」这一段是真验证。

**它证明不了模型的选择质量。**「800 元该不该把双投影降成单投影」「40 人该不该拆场地」
是模型的判断，假模型只是把这个判断**当作输入喂进来**。因此 `AGENT-S-01~06` 断言的是
**透传与形状**：模型给出的理由、备选方案、修改建议要一字不少地到达用户，不能在中途
被吞掉或被改名。各条场景的**前提**（种子数据里确实存在「预算卡在场地价上」
「会议室没有 40 人的」「直播设备只剩一台可借」这些约束）单独用
`test_seed_supports_the_five_scenarios` 与 `test_seed_supports_the_degradation_case`
对着真库验——那部分是真的，不依赖模型。

决策质量的验证卡在**未配置 LLM**（`backend/.env` 缺 `LLM_MODEL_NAME` / `LLM_API_KEY` /
`LLM_BASE_URL`），见 `docs/test.md` §3.3 的未闭环清单。

## 为什么每个脚本序列都以一条**纯文本 AIMessage** 收尾

`create_agent` 的循环是「模型返回带 `tool_calls` → 执行工具 → 再问模型」，
只有模型返回**不带** `tool_calls` 的消息时图才结束。`ScriptedChatModel` 在响应耗尽后
会重复最后一条，所以末尾必须是纯文本——否则会一直重复最后一次工具调用直到
撞上 `AGENT_RECURSION_LIMIT`，用例表现为「无端降级」。
"""
from __future__ import annotations

import asyncio
import importlib
import json
import re

import pytest
from langchain_core.messages import AIMessage

from app.agent.chains import builder
from app.core.config import settings
from app.core.response import CODE_OK
from app.schemas.agent import ScheduleData

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------
# 构造脚本序列的小工具
# --------------------------------------------------------------------------
def _call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id}


def _ai(text: str = "", calls: list[dict] | None = None) -> AIMessage:
    """一条模型消息。`calls` 为空即纯文本，图在此终止。"""
    kwargs: dict = {"content": text}
    if calls:
        kwargs["tool_calls"] = calls
    return AIMessage(**kwargs)


def _spaces_call(capacity: int, space_type: int, slots: dict, call_id: str = "c-spaces") -> AIMessage:
    start, end = slots["free"]
    return _ai(
        f"先查 {capacity} 人的场地。",
        [_call("query_spaces", {
            "capacity": capacity, "space_type": space_type,
            "start_time": start, "end_time": end,
        }, call_id)],
    )


def _devices_call(device_type: str, call_id: str = "c-devices") -> AIMessage:
    return _ai(f"查一下{device_type}。", [_call("query_devices", {"device_type": device_type}, call_id)])


def _lock_call(space_id: int, device_ids: list[int], slots: dict, call_id: str = "c-lock") -> AIMessage:
    start, end = slots["free"]
    return _ai(
        "锁定资源。",
        [_call("lock_resources", {
            "space_id": space_id, "device_ids": device_ids,
            "start_time": start, "end_time": end,
        }, call_id)],
    )


def _submit_call(plan: dict, *, backup: dict | None = None, reason: str = "",
                 call_id: str = "c-submit") -> AIMessage:
    args: dict = {"plan": plan, "reason": reason}
    if backup is not None:
        args["backup_plan"] = backup
    return _ai("方案已定，提交。", [_call("submit_plan", args, call_id)])


def _plan(space_id: int, name: str, devices: list[int], slots: dict, reason: str) -> dict:
    start, end = slots["free"]
    return {
        "spaceId": space_id, "spaceName": name, "deviceIds": devices,
        "startTime": start, "endTime": end, "reason": reason,
    }


def _stub_outcome(message: str = "操作成功", *, success: bool = False) -> builder.AgentOutcome:
    """一个最小可用的 `AgentOutcome`。

    给「截住 `run_schedule` 只看实参」的用例当返回值：那些用例的断言对象是**实参**，
    但对外的 HTTP 行为仍要走完整条路由（埋点、响应组装），所以不能靠抛异常来短路
    ——`register_exception_handlers` 会把异常转成 500，用例就变成在验异常处理器了。
    """
    return builder.AgentOutcome(
        data=ScheduleData(plan=None, backupPlan=None, trace=[], needConfirm=True),
        message=message,
        success=success,
        degraded=not success,
        latency_ms=0,
    )


@pytest.fixture
def use_model(monkeypatch):  # noqa: ANN001, ANN201
    """把假模型接到流水线上。

    只换 `build_model`，**不换 `run_schedule`**——换后者等于把被测的那一段（工具执行、
    trace 提取、降级判定）整个跳过，用例会变成「我调了一个假函数，它返回了我预设的值」。
    """
    def _use(model) -> None:  # noqa: ANN001
        monkeypatch.setattr(builder, "build_model", lambda: model)

    return _use


# --------------------------------------------------------------------------
# 五条场景的**前提**：对着真库验，不依赖模型
# --------------------------------------------------------------------------
async def test_seed_supports_the_five_scenarios(seed: dict, slots: dict) -> None:
    """A~E 五条场景之所以成立，靠的是种子数据里真实存在的这几个约束。

    这些前提单独验而不是混在场景用例里：种子数据一变，这条会**指名道姓地**
    说「场景 B 的前提没了」，而场景用例自己只会表现为「模型怎么选都对」的假绿。
    """
    from app.agent.tools import query_devices, query_spaces

    start, end = slots["free"]
    window = {"start_time": start, "end_time": end}

    # A「预算降级」的前提：40 人展厅存在，且它恰好卡在 800 元预算线上
    halls = await query_spaces.ainvoke({"capacity": 40, "space_type": 2, **window})
    assert halls["count"] >= 1, "40 人展厅没了，场景 A 无从谈起"
    cheap = [s for s in halls["spaces"] if s["id"] == seed["space_hall_40"]]
    assert cheap and cheap[0]["budget"] == 800.0, "A栋3楼展厅的预算不是 800，场景 A 的降级动因消失了"

    # A 的前提之二：投影仪可借（模型才有「从两台降到一台」这个选项）
    projectors = await query_devices.ainvoke({"device_type": "投影仪"})
    assert projectors["count"] >= 2, "可借投影仪不足 2 台，场景 A 的「降级」无从谈起"

    # B「场地拆分」的前提：40 人的会议室**不存在**，但 20 人的有两间以上
    big_rooms = await query_spaces.ainvoke({"capacity": 40, "space_type": 1, **window})
    assert big_rooms["count"] == 0, "存在 40 人会议室，场景 B 的拆分动因消失了"
    small_rooms = await query_spaces.ainvoke({"capacity": 20, "space_type": 1, **window})
    assert small_rooms["count"] >= 2, "20 人会议室不足两间，拆不出 40 人"

    # C「设备替代」的前提：替代类型确实有货
    screens = await query_devices.ainvoke({"device_type": "显示屏"})
    assert screens["count"] >= 1, "显示屏不可借，场景 C 的替代路径断了"


async def test_seed_supports_the_degradation_case(seed: dict) -> None:
    """`AGENT-S-06` 的前提：**「直播设备只有 1 台可借」是算出来的，不是编出来的。**

    与上面那条同样的理由单列：种子一改，这里会指名道姓地说「降级前提没了」，
    而 `AGENT-S-06` 自己只会表现为「模型怎么选都对」的假绿。

    依据是种子注释里那两个**互相独立**的见证者（`docs/seed.sql` 第 4 节 b 条）：
    id=15 直播设备02 是 `status=1` 但 `available_count=0`，**只被「可用数」分支筛掉**；
    id=13 无人机02 是 `available_count=1` 但 `status=2`，**只被「状态」分支筛掉**。
    本条用前者当降级动因，顺带用后者证明两个分支各自真的在起作用——
    若 Tool 的过滤条件漏写任一条，下面的断言会失败而不是「碰巧」通过。
    """
    from app.agent.tools import query_devices

    live = await query_devices.ainvoke({"device_type": "直播设备"})
    live_ids = [d["id"] for d in live["devices"]]
    assert live["count"] == 1, f"直播设备可借数不是 1（{live_ids}），场景六的降级动因消失了"
    assert live_ids == [seed["live_ok"]], "可借的不是直播设备01"
    assert seed["live_exhausted"] not in live_ids, "available_count=0 的设备没被滤掉——「可用数」分支失效"

    # 用户要两台 → 库里只有一台能借，这是**真降级**，不依赖任何时段或扣减口径。
    assert live["count"] < 2, "能借满两台，降级就无从谈起"

    # 另一条独立见证者：状态分支。无人机01 有 2 台可借，无人机02 因损坏被滤掉。
    drones = await query_devices.ainvoke({"device_type": "无人机"})
    drone_ids = [d["id"] for d in drones["devices"]]
    assert drone_ids == [seed["drone_ok"]], "device_status=2 的设备没被滤掉——「状态」分支失效"
    assert drones["devices"][0]["availableCount"] == 2, "无人机01 的可借数不是 2，见证者前提变了"


# --------------------------------------------------------------------------
# AGENT-S：五个决策场景
# --------------------------------------------------------------------------
async def test_s01_budget_keeps_space_and_explains_no_downgrade(use_model, scripted, slots) -> None:  # noqa: ANN001
    """A 预算 / 设备（800 元 / 40 人 + 双投影）→ **保住场地，并说明为何无需降级**。

    ## 标准为什么从「设备降级为单投影」改成这一条

    原标准的前提**算不出来**：`device_resource` 没有价格字段，设备不占预算科目，
    而 800 元预算正好等于 A栋3楼展厅的场地费。也就是说「双投影 → 单投影」这个降级
    在数据上没有任何动因，模型据此给出降级理由只能靠编。经项目群裁定改为 A+C：
    预期改成本条（保场地 + 说明无需降级），另补一条前提真成立的降级用例 `AGENT-S-06`。
    属**验收标准偏离**，已记入 `docs/spec/done/stage-05-completion.md`。

    **验**：`plan` 非空、`spaceId` 命中 40 人展厅、`reason` 非空且说明了「无需降级」；
    两台投影**都在** `deviceIds` 里（没被削成一台）；备选方案走 `backup_plan`
    （snake_case 入参）也能正确落到 `backupPlan`——这条路径最容易静默变成 None。
    **不验**：该不该降级——那是模型的判断，本用例只验透传与形状。
    """
    no_downgrade_reason = (
        "场地与设备均在预算内，**无需降级**：A栋3楼展厅 800 元正好等于预算上限，"
        "投影仪属库存借用、不占预算科目，两台均可保留，方案不做任何削减。"
    )
    main = _plan(4, "A栋3楼展厅", [1, 2], slots, no_downgrade_reason)
    backup = _plan(5, "C栋1楼展厅", [2], slots, "备选：35 人展厅，预算再省 200 元。")

    use_model(scripted([
        _spaces_call(40, 2, slots),
        _devices_call("投影仪"),
        _submit_call(main, backup=backup, reason="预算内保场地，设备无需降级。"),
        _ai("已提交方案。"),
    ]))

    outcome = await builder.run_schedule(text="40人展厅，预算800，要两台投影", user_id=1)

    assert outcome.success and not outcome.degraded
    assert outcome.data.plan is not None, "保住了场地却没有方案"
    assert outcome.data.plan.spaceId == 4, "40 人场地的落点不是 A栋3楼展厅"
    assert outcome.data.plan.deviceIds == [1, 2], "无需降级时设备清单被削减了"
    assert outcome.data.plan.reason, "reason 为空——用户看不出为什么没降级"
    assert "无需降级" in outcome.data.plan.reason, "reason 没有说明为何无需降级"
    assert outcome.data.backupPlan is not None, "backup_plan 没落到 backupPlan（字段名抹平失败）"
    assert outcome.data.backupPlan.spaceId == 5
    assert outcome.data.needConfirm is True


async def test_s02_split_request_is_carried_through(use_model, scripted, slots) -> None:
    """B 场地拆分（无 40 人场地 → 拆两个小的）。

    **验**：两次 `lock_resources` 分别占两个场地时，trace 里是两步、两个不同的 spaceId；
    主方案与备选方案承载两个半场。**不验**：模型是否想到要拆。
    """
    main = _plan(6, "综合楼大礼堂", [], slots, "拆分为两个时段对齐的场地。")
    backup = _plan(7, "综合楼小多功能厅", [], slots, "备用半场。")

    use_model(scripted([
        _spaces_call(40, 1, slots, "c1"),
        _lock_call(6, [], slots, "c2"),
        _lock_call(7, [], slots, "c3"),
        _submit_call(main, backup=backup, reason="拆成两场，分两批入场。"),
        _ai("已提交拆分方案。"),
    ]))

    outcome = await builder.run_schedule(text="40人，两间会议室也行", user_id=1)

    assert outcome.success
    locks = [s for s in outcome.data.trace if s.action == "lock_resources"]
    assert len(locks) == 2, "两次锁定没有各自成步"
    assert locks[0].actionInput["space_id"] != locks[1].actionInput["space_id"], "两次锁的是同一场地"
    assert outcome.data.backupPlan.spaceId == 7


async def test_s03_device_substitution_replaces_type(use_model, scripted, slots) -> None:
    """C 设备替代（投影仪借不到 → 换 LED 显示屏一类的替代类型）。

    **验**：替代类型的查询过程在 trace 里留有一步（可溯源「为什么换成了这个」），
    且方案里的 `deviceIds` 就是替代设备的 ID，没有被替换回原类型。
    **不验**：该不该替代、替代得合不合理。
    """
    substitute_reason = "投影仪已全数占用，改推荐显示屏 9，可满足放映需求。"

    use_model(scripted([
        _devices_call("投影仪", "c1"),
        _devices_call("显示屏", "c2"),
        _submit_call(_plan(4, "A栋3楼展厅", [9], slots, substitute_reason),
                     reason="设备替代。"),
        _ai("已提交替代方案。"),
    ]))

    outcome = await builder.run_schedule(text="要投影仪", user_id=1)

    assert outcome.success
    queried = [s.actionInput["device_type"] for s in outcome.data.trace if s.action == "query_devices"]
    assert queried == ["投影仪", "显示屏"], f"替代路径没留痕：{queried}"
    assert outcome.data.plan.deviceIds == [9]
    assert outcome.data.plan.reason == substitute_reason


async def test_s04_contradictory_request_returns_null_plan_with_suggestions(use_model, scripted, slots) -> None:  # noqa: ANN001
    """D 需求矛盾（40 人 / 500 元）→ `plan=null`，`message` 含至少 3 条修改建议。

    **验**：模型判为矛盾、不调 `submit_plan` 时，系统**不编造方案**（`plan` 与
    `backupPlan` 都为 `None`），且把模型写的建议**一条不少**地透传给用户
    （主文档 10.2 与契约里「大模型输出格式错乱」一栏要求的正是这条）。
    **不验**：模型想不想得出这三条建议——它是本用例的输入，不是结论。
    """
    advice = (
        "这个需求在现有资源下无法同时满足，建议：\n"
        "1. 把人数放宽到 30 人以内，可选的会议室会多出一间；\n"
        "2. 或者把预算提高到 600 元以上，A栋3楼展厅即可满足；\n"
        "3. 也可以改用户外场地（100 人容量，预算更低），但需自备设备；\n"
        "4. 若接受拆成两个场地，请告知是否需要同步直播。"
    )

    use_model(scripted([_spaces_call(40, 2, slots), _ai(advice)]))

    outcome = await builder.run_schedule(text="40人，预算500", user_id=1)

    assert outcome.data.plan is None, "需求矛盾时给出了方案——这属于编造"
    assert outcome.data.backupPlan is None
    assert outcome.data.needConfirm is True
    assert outcome.message == advice, "模型的修改建议没有原样透传"
    assert len(re.findall(r"(?m)^\s*\d+[.、)]", outcome.message)) >= 3
    assert outcome.degraded, "无方案必须计入降级，否则成功率虚高"


async def test_s05_merged_activity_keeps_the_saving_in_reason(use_model, scripted, slots) -> None:
    """E 活动合并（同团队连续两场）→ 合并建议 + 节省说明。

    **验**：节省说明写在 `reason` 里并原样到达用户；合并后只锁**一个**场地。
    **不验**：合并是不是比拆开好。
    """
    saving = "两场合并为一场，节省一个场地与 2 小时时段，投影仪由 4 台减为 2 台。"

    use_model(scripted([
        _spaces_call(30, 3, slots, "c1"),
        _lock_call(6, [1, 2], slots, "c2"),
        _submit_call(_plan(6, "综合楼大礼堂", [1, 2], slots, saving), reason="合并两场。"),
        _ai("已提交合并方案。"),
    ]))

    outcome = await builder.run_schedule(text="上午下午各一场，同一个团队", user_id=1)

    assert outcome.success
    assert outcome.data.plan.reason == saving
    locks = [s for s in outcome.data.trace if s.action == "lock_resources"]
    assert len(locks) == 1, "合并后仍锁了多个场地"


async def test_s06_insufficient_devices_degrades_to_what_is_available(use_model, scripted, slots) -> None:
    """`AGENT-S-06` 设备**数量不足**（要两台直播设备，库里只有 1 台可借）→ 降级为可借数。

    ## 与 `AGENT-S-01` 的分工

    S-01 验「不需要降级时要说清楚为什么」；本条验「真需要降级时降得住、且理由透传」。
    两条合起来才是完整的降级语义，缺一条都只覆盖一半。

    ## 前提为什么是真的

    `docs/seed.sql` 的 `直播设备×2` 里，id=15 是 `status=1` 但 `available_count=0`
    （完好、全部借出）。`query_devices` 的可用性过滤把它滤掉，于是这个类型**只剩
    id=14 一台**。用户要两台 → 只能给一台。这条链路**不需要时段参数、也不依赖
    尚未定论的扣减口径**，今天就能算出来——这正是它比「投影仪在某时段被占满」
    更适合当降级用例的原因（后者受 `query_devices` 无时段参数所限，进不了主链路）。
    前提由 `test_seed_supports_the_degradation_case` 对着真库单独验。

    **验**：`deviceIds` 就是可借的那**一台**（不能被系统补齐成两台，也不能改成坏设备
    id=15）；降级理由原样透传；`trace` 里留有查询这一步，用户能溯源「为什么只给一台」。
    **不验**：该不该降级、该不该改用替代类型——那是模型的判断。
    """
    degrade_reason = (
        "直播设备当前仅有 1 台可借（另一台已全部借出），本次按 1 台满足；"
        "若必须两台，建议改用无人机或调整使用日期。"
    )

    use_model(scripted([
        _devices_call("直播设备", "c1"),
        _submit_call(_plan(8, "中心广场", [14], slots, degrade_reason), reason="设备数量不足，按可借数降级。"),
        _ai("已提交降级方案。"),
    ]))

    outcome = await builder.run_schedule(text="户外活动，要两台直播设备", user_id=1)

    assert outcome.success, "数量不足是契约内降级，不该整单失败"
    assert outcome.data.plan is not None, "降级后应该仍有方案，不是无方案"
    assert outcome.data.plan.deviceIds == [14], "降级后的设备清单不是可借的那一台"
    assert len(outcome.data.plan.deviceIds) == 1, "要两台却给回了两台——降级没发生"
    assert outcome.data.plan.reason == degrade_reason, "降级理由没有原样透传"

    # 可溯源：用户要能看出「为什么只给一台」，所以查询这一步必须在 trace 里。
    queried = [s.actionInput["device_type"] for s in outcome.data.trace if s.action == "query_devices"]
    assert queried == ["直播设备"], f"降级依据没留痕：{queried}"
    assert outcome.data.needConfirm is True


# --------------------------------------------------------------------------
# AGENT-E：异常与降级（全部返回 HTTP 200）
# --------------------------------------------------------------------------
async def test_e01_non_json_reply_degrades_with_model_text(use_model, scripted, dev_client, auth) -> None:  # noqa: ANN001
    """`AGENT-E-01` 模型返回非 JSON：200、`plan=null`、`needConfirm=true`、
    `message` 为模型原文（主文档 10.2 明文要求）。"""
    prose = "抱歉，我暂时无法给出方案，请补充日期与预算后重试。"

    use_model(scripted([_ai(prose)]))

    resp = await dev_client.post("/api/v1/agent/schedule", json={"text": "帮我排一下"}, headers=auth)

    assert resp.status_code == 200, "契约内降级不是异常，不能给非 200"
    body = resp.json()
    assert body["data"]["plan"] is None
    assert body["data"]["needConfirm"] is True
    assert body["message"] == prose


async def test_e01_fenced_json_in_text_is_salvaged(use_model, scripted, slots, dev_client, auth) -> None:  # noqa: ANN001
    """主文档 7.4 的 JSON 解析容错：模型不调工具、但正文里贴了 JSON → **捞出来当成方案**。

    这条与上一条合起来才是完整的 E-01：容错**优先**，容错也失败才降级。
    """
    start, end = slots["free"]
    fenced = (
        "这是我的方案：\n```json\n"
        + json.dumps({
            "plan": {"spaceId": 4, "spaceName": "A栋3楼展厅", "deviceIds": [1],
                     "startTime": start, "endTime": end, "reason": "预算内方案"},
            "reason": "正文 JSON 提交",
        }, ensure_ascii=False)
        + "\n```\n请确认。"
    )

    use_model(scripted([_ai(fenced)]))

    resp = await dev_client.post("/api/v1/agent/schedule", json={"text": "安排一下"}, headers=auth)

    body = resp.json()
    assert resp.status_code == 200
    assert body["data"]["plan"]["spaceId"] == 4, "正文里的 JSON 方案没被捞出来"


async def test_e02_slow_model_degrades_on_timeout(use_model, scripted, dev_client, auth, monkeypatch) -> None:  # noqa: ANN001
    """`AGENT-E-02` 模型调用超时：200 + 友好提示（不是 500、不是挂住）。

    超时阈值改为 0.05 秒、模型延迟 0.3 秒——**不改阈值的话本用例要跑满 30 秒**。
    """
    monkeypatch.setattr(settings, "AGENT_TIMEOUT", 0.05)
    use_model(scripted([_ai("想很久……")], delay=0.3))

    resp = await dev_client.post("/api/v1/agent/schedule", json={"text": "慢慢想"}, headers=auth)

    body = resp.json()
    assert resp.status_code == 200
    assert body["data"]["plan"] is None
    assert "超时" in body["message"]
    assert body["data"]["needConfirm"] is True


async def test_e02_timeout_keeps_the_steps_already_collected(monkeypatch, use_model, scripted) -> None:  # noqa: ANN001
    """超时时 **trace 保留中断前的步骤**，且提示里报出「已思考到第几步」。

    这正是 `run_schedule` 把 `stamped` 提在 `wait_for` 外面、以 sink 形式传进去的
    全部理由：`wait_for` 取消协程后**返回值根本拿不到**，只剩这个列表。

    这里替换 `collect_stamped_messages` 而不是用慢模型：慢模型在第一次模型调用就卡住，
    一步都不会被打点，验不出「保留」这件事。
    """
    from langchain_core.messages import ToolMessage

    monkeypatch.setattr(settings, "AGENT_TIMEOUT", 0.05)
    use_model(scripted([_ai("占位")]))

    async def _sink_then_hang(agent, inputs, *, config=None, sink=None):  # noqa: ANN001, ANN202
        # 三步 = **两步** trace（带 tool_calls 的 AIMessage 与其 ToolMessage 合并成一步，
        # 这是契约要求的形状）。所以要凑出「第 2 步」得放三条。
        sink.append((AIMessage(content="第一步", tool_calls=[_call("query_spaces", {}, "x1")]),
                     "2026-09-25 14:00:00"))
        sink.append((ToolMessage(content="{}", name="query_spaces", tool_call_id="x1"),
                     "2026-09-25 14:00:01"))
        sink.append((AIMessage(content="第二步", tool_calls=[_call("query_devices", {}, "x2")]),
                     "2026-09-25 14:00:02"))
        await asyncio.sleep(5)

    monkeypatch.setattr(builder, "collect_stamped_messages", _sink_then_hang)

    outcome = await builder.run_schedule(text="随便", user_id=1)

    assert outcome.degraded and outcome.degraded_reason == "timeout"
    assert len(outcome.data.trace) == 2, "中断前已完成的步骤被丢掉了"
    assert outcome.steps == 2
    assert "已思考到第 2 步" in outcome.message


async def test_e03_empty_query_result_yields_no_plan(use_model, scripted, dev_client, auth, slots) -> None:  # noqa: ANN001
    """`AGENT-E-03` 无可用资源：`plan` 与 `backupPlan` 都为 `null`，并明确说明无方案。

    用 10000 人的户外场地当「必然查不到」的需求——上限是 `QuerySpacesArgs` 的 `le=10000`，
    不是随手拍的数字。
    """
    start, end = slots["free"]

    use_model(scripted([
        _ai("查一下超大户外场地。", [_call("query_spaces", {
            "capacity": 10000, "space_type": 4, "start_time": start, "end_time": end,
        }, "c1")]),
        _ai("当前没有能容纳 10000 人的场地，无法生成方案。建议降低人数或改为线上举办。"),
    ]))

    resp = await dev_client.post("/api/v1/agent/schedule", json={"text": "一万人户外"}, headers=auth)

    body = resp.json()
    assert resp.status_code == 200
    assert body["data"]["plan"] is None
    assert body["data"]["backupPlan"] is None
    assert "无法生成方案" in body["message"]


async def test_e04_tool_exception_is_not_a_500(monkeypatch, use_model, scripted, dev_client, auth, slots) -> None:  # noqa: ANN001
    """`AGENT-E-04` 工具抛异常：不 500，走降级提示。

    这里让 `query_spaces` 的 service 抛错。**LangGraph 的 ToolNode 默认会把工具异常
    包成 `ToolMessage` 回给模型**（`handle_tool_errors`），所以请求不会崩，
    模型会收到「这个工具报错了」并自行改道——本例里假模型直接放弃，于是走降级。
    这条与下面那条（流本身抛错）合起来覆盖 `run_schedule` 的两层兜底。
    """
    def _boom(**kwargs):  # noqa: ANN003, ANN202
        raise RuntimeError("service 桩爆炸")

    # ⚠️ 目标必须取**模块本体**。写字符串路径 `"app.agent.tools.query_spaces._query_spaces_service"`
    # 会先取包属性 `app.agent.tools.query_spaces`——而包 `__init__` 里
    # `from app.agent.tools.query_spaces import query_spaces` 把它覆盖成了**工具对象**，
    # 于是 monkeypatch 报 "StructuredTool object has no attribute ..."。
    # 另外要打的是**工具模块里的那个别名**（`_query_spaces_service`），不是
    # `app.services.query_spaces`：工具在 import 时就绑好了引用，改 service 模块没用。
    spaces_mod = importlib.import_module("app.agent.tools.query_spaces")
    monkeypatch.setattr(spaces_mod, "_query_spaces_service", _boom)

    use_model(scripted([
        _spaces_call(40, 2, slots),
        _ai("查询场地时出错，本次无法给出方案，请稍后重试。"),
    ]))

    resp = await dev_client.post("/api/v1/agent/schedule", json={"text": "排一下"}, headers=auth)

    assert resp.status_code == 200, "工具异常穿透成了 5xx"
    body = resp.json()
    assert body["data"]["plan"] is None
    assert "错误" in body["message"] or "重试" in body["message"]


async def test_e04_runtime_error_in_the_stream_degrades_not_500(monkeypatch, use_model, scripted) -> None:  # noqa: ANN001
    """整条流自己抛错时也不许穿透成 500。

    `run_schedule` 里那个宽 `except Exception` 是**刻意宽**的：LangGraph 会把工具内的
    异常包成不同层级的类型，逐个枚举必然漏，漏掉的那一种就是演示当天的 500。
    """
    use_model(scripted([_ai("占位")]))

    async def _boom(agent, inputs, *, config=None, sink=None):  # noqa: ANN001, ANN202
        raise RuntimeError("流炸了")

    monkeypatch.setattr(builder, "collect_stamped_messages", _boom)

    outcome = await builder.run_schedule(text="随便", user_id=1)

    assert outcome.degraded and not outcome.success
    assert outcome.data.plan is None
    assert outcome.degraded_reason.startswith("RuntimeError")
    assert "异常" in outcome.message


# --------------------------------------------------------------------------
# AGENT-I：接口
# --------------------------------------------------------------------------
async def test_i01_normal_call_returns_full_unified_body(use_model, scripted, slots, dev_client, auth) -> None:  # noqa: ANN001
    """`AGENT-I-01` 正常调用：200、统一响应体、`data.trace` 非空且字段齐全。"""
    use_model(scripted([
        _spaces_call(40, 2, slots, "c1"),
        _devices_call("投影仪", "c2"),
        _submit_call(_plan(4, "A栋3楼展厅", [1, 2], slots, "满足 40 人与双投影。"), reason="直接满足。"),
        _ai("已完成。"),
    ]))

    resp = await dev_client.post("/api/v1/agent/schedule", json={"text": "40人展厅+双投影"}, headers=auth)

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"code", "message", "data"}, "响应体不是主文档 5.2 的三段式"
    assert body["code"] == CODE_OK
    assert body["message"] == "操作成功"

    data = body["data"]
    assert set(data) == {"plan", "backupPlan", "orderId", "trace", "needConfirm"}
    assert data["trace"], "trace 为空——屏 3 没有东西可回放"
    for step in data["trace"]:
        assert set(step) == {"step", "result", "timestamp", "thought", "action",
                             "actionInput", "observation"}
        assert step["step"] >= 1 and step["result"] and step["timestamp"]
    assert data["trace"][0]["action"] == "query_spaces"
    assert data["trace"][0]["observation"] is not None, "工具结果没进 observation"


async def test_i02_missing_authorization_is_401(dev_client) -> None:  # noqa: ANN001
    """`AGENT-I-02` 无 `Authorization` 头：401，且响应体仍是统一结构。"""
    resp = await dev_client.post("/api/v1/agent/schedule", json={"text": "排一下"})

    assert resp.status_code == 401
    body = resp.json()
    assert set(body) == {"code", "message", "data"}, "401 也必须是统一响应体"


async def test_i03_empty_text_is_rejected_without_calling_the_model(dev_client, auth, monkeypatch) -> None:  # noqa: ANN001
    """`AGENT-I-03` `text` 为空串：被参数校验挡下，**且不空跑模型**（`min_length=1` 生效）。

    ⚠️ 口径是 **HTTP 200 + `code=400`**，不是 422。

    全局 `RequestValidationError` 处理器（`core/exceptions.py`）把框架默认的
    「422 + 字段级报错」统一收敛成 `code=400` + 一句人话，与模块 1/2 的用例口径一致
    （它们断言 `body["code"] == 400`）。两套口径不可兼得，模块 4 让出 422：
    `docs/api.md` 原先写的 422 已按此改正。**契约冻结后因跨模块统一响应体改口径**，
    记在 stage-02 完成文档的偏离表。
    """
    called = False

    async def _spy(**kwargs):  # noqa: ANN003, ANN202
        nonlocal called
        called = True
        return _stub_outcome()

    monkeypatch.setattr("app.api.v1.agent.run_schedule", _spy)

    resp = await dev_client.post("/api/v1/agent/schedule", json={"text": ""}, headers=auth)

    assert resp.status_code == 200, "统一响应体的约定是 HTTP 恒 200，错误码只放 body.code"
    assert resp.json()["code"] == 400
    assert not called, "空文本仍然跑了一遍模型"


@pytest.mark.parametrize("payload", [
    {"text": "排一下", "userId": 999},
    {"text": "排一下", "user_id": 999},
    {"text": "排一下", "userId": 999, "role": "admin"},
])
async def test_i04_identity_comes_only_from_jwt(payload, dev_client, auth, monkeypatch) -> None:  # noqa: ANN001
    """`AGENT-I-04` 请求体夹带 `userId` / `role`：被**忽略**，实际用 JWT 里的用户。

    观察点不是「返回了 200」——那证明不了用的是谁。这里截住 `run_schedule` 的实参：
    `user_id` 必须是 token 里的 `1`，任何来自请求体的值都不许进来。
    """
    seen: dict = {}

    async def _spy(*, text, user_id, image_context=None):  # noqa: ANN001, ANN202
        seen["user_id"] = user_id
        seen["text"] = text
        return _stub_outcome()

    monkeypatch.setattr("app.api.v1.agent.run_schedule", _spy)

    resp = await dev_client.post("/api/v1/agent/schedule", json=payload, headers=auth)

    assert resp.status_code == 200, "夹带 userId 应当是「被忽略」，不是校验失败也不是 500"
    assert seen["user_id"] == 1, f"身份不是从 JWT 取的：{seen.get('user_id')}"
    assert "userId" not in seen["text"] and "user_id" not in seen["text"], "请求体的身份字段混进了需求原文"


async def test_i05_response_carries_no_secrets(use_model, scripted, slots, dev_client, auth) -> None:  # noqa: ANN001
    """`AGENT-I-05` 响应体不含敏感信息（主文档 9.2）。"""
    secrets = {
        "LLM_API_KEY": settings.LLM_API_KEY,
        "DB_PASSWORD": settings.DB_PASSWORD,
        "JWT_SECRET_KEY": settings.JWT_SECRET_KEY,
    }

    use_model(scripted([
        _submit_call(_plan(4, "A栋3楼展厅", [1], slots, "方案"), reason="直接满足。"),
        _ai("完成。"),
    ]))

    resp = await dev_client.post("/api/v1/agent/schedule", json={"text": "排一下"}, headers=auth)
    text = resp.text

    for name, value in secrets.items():
        if not value:
            continue  # 本机没配的项跳过；配了的**必须**验
        assert value not in text, f"响应体里出现了 {name} 的值"


async def test_i05_unavailable_llm_returns_503_naming_fields_not_values(dev_client, auth, monkeypatch) -> None:  # noqa: ANN001
    """`.env` 缺 LLM 配置时的唯一非 200 路径：503，且**只报字段名、不回显值**。

    这是「服务端配置问题」与「AI 没想出方案」的分界：后者是 HTTP 200 的契约内降级
    （见 `test_e01`），把它混为一谈会让运维去查用户的输入。
    """
    from app.agent.chains.builder import AgentUnavailableError

    async def _raise(**kwargs):  # noqa: ANN003, ANN202
        raise AgentUnavailableError(
            "大模型未配置：请在 backend/.env 中填好 LLM_MODEL_NAME / LLM_API_KEY / LLM_BASE_URL。"
        )

    monkeypatch.setattr("app.api.v1.agent.run_schedule", _raise)

    resp = await dev_client.post("/api/v1/agent/schedule", json={"text": "排一下"}, headers=auth)

    assert resp.status_code == 503
    body = resp.json()
    assert set(body) == {"code", "message", "data"}
    assert "LLM_MODEL_NAME" in body["message"], "没告诉运维缺哪个字段"
    if settings.LLM_API_KEY:
        assert settings.LLM_API_KEY not in body["message"], "把 Key 的值回显了"


async def test_i05_build_model_gate_and_no_implicit_key(monkeypatch) -> None:  # noqa: ANN001
    """`build_model()` 的两段式行为：缺配置**明确报错**，配齐则**显式传参**。

    第二段是本条的重点：`ChatOpenAI` 会隐式读取环境变量 `OPENAI_API_KEY`，
    不显式传 `api_key` 的话请求可能被静默路由到别人的额度上（`core/config.py` 记了这条）。
    """
    from app.agent.chains.builder import AgentUnavailableError

    monkeypatch.setattr(settings, "LLM_MODEL_NAME", "qwen-plus")
    monkeypatch.setattr(settings, "LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setattr(settings, "LLM_API_KEY", "")
    with pytest.raises(AgentUnavailableError):
        builder.build_model()

    monkeypatch.setattr(settings, "LLM_API_KEY", "sk-测试用假值")
    model = builder.build_model()

    assert model.model_name == "qwen-plus"
    assert model.openai_api_key.get_secret_value() == "sk-测试用假值", "api_key 没显式传，落到了隐式环境变量路径"
    assert str(model.openai_api_base) == "https://example.invalid/v1"


async def test_i05_never_registers_tool_routes(dev_client) -> None:  # noqa: ANN001
    """`/api/v1/tools/*` 全仓不存在（主文档 5.3 / 9.3）。

    工具是给模型用的函数，不是给人用的接口——注册出去等于把「查库 + 锁资源」暴露成
    无鉴权或弱鉴权的 HTTP 端点。
    """
    for name in ("query_spaces", "query_devices", "lock_resources",
                 "generate_notification", "submit_plan"):
        resp = await dev_client.post(f"/api/v1/tools/{name}", json={})
        assert resp.status_code == 404, f"/api/v1/tools/{name} 被注册了"


# --------------------------------------------------------------------------
# 护栏自证：「断网跑通」与「没写正式表」要能被**验**，而不是被声称
# --------------------------------------------------------------------------
# 阶段 7 §3.8 的原话是「断网跑一遍验证这一点，**不要只凭『应该不联网』推断**」，
# 验收清单里也有「无任何用例写 reserve_order 正式表」。两条都是**否定性结论**，
# 只报「跑完了/没报错」证明不了——没报错也可能是因为拦截根本没生效。
# 下面两条主动去触发拦截，把「护栏在场」变成可执行证据。
async def test_guard_offline_is_actually_armed() -> None:
    """任一非回环连接都会被打回。**这是「断网跑通」的证据**。"""
    import socket

    with pytest.raises(AssertionError, match="用例试图联网"):
        socket.socket().connect(("example.com", 80))
    # 回环必须放行——否则连库的用例自己先跑不起来
    sock = socket.socket()
    sock.connect(("127.0.0.1", 3308))
    sock.close()


async def test_guard_db_writes_are_actually_blocked(dev_db_session) -> None:  # noqa: ANN001
    """写语句会被前置拒绝。**这是「没写正式表」的证据**（主文档 6.8 红线）。

    用一条**只改自己**的 UPDATE 来触发：它即使真被执行也几乎不改变数据，
    但拦截必须在**执行前**就抛——这正是它与「事后回滚」的安全性差别。
    """
    from sqlalchemy import text

    with pytest.raises(AssertionError, match="用例试图写库"):
        await dev_db_session.execute(
            text("UPDATE reserve_order SET order_status = order_status WHERE id = 9")
        )
