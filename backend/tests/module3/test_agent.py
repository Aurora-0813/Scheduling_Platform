"""Agent 联动与语音/图像占位入口（docs/模块3-test.md TC-23 ~ TC-28）。

⚠️ **2026-09-28 两处改写**（原因见各用例 docstring）：
  1. TC-27 / TC-28 由「断言占位端点能用」改为「断言它们**不存在**（404）」——
     该模块从未注册，原断言在验一个不可达的端点；
  2. 四条需要**真实大模型**才能产出 plan 的用例加 `_NEEDS_LLM` 跳过标记
     —— 没有 key 时 `/agent/schedule` 返回 503 是**设计如此**，不是缺陷。
"""

import pytest

from app.core.config import settings
from app.core.error_codes import ErrorCode

from .helpers import MOCK_USER_ID, time_str

#: 需要真实大模型才能出方案的用例标记。
#:
#: 这些用例断言的是 **Agent 产出的 plan 内容**（`spaceName` / `startTime` / `deviceIds`…）。
#: 没有可用 LLM 时 `POST /api/v1/agent/schedule` 会返回 **503 + code 41003**
#: （`AgentUnavailableError` —— 服务端配置缺失，属**设计如此**的显式暴露，
#: 见 `app/api/v1/agent.py` 的说明），拿不到 plan，后续断言必然崩。
#:
#: **为什么不塞假模型**：那样证明的是「假模型能跑通」，不是「Agent 能出方案」。
#: `docs/spec/done/README.md` 里 `AGENT-S-01~06` 已经吃过这个亏
#: （当初「只验了透传与形状，决策质量需真实 LLM」）。
#: `docs/test.md` §10.2 也要求「真实 API 只做一次冒烟验证」——
#: 这类断言天然属于冒烟范畴。模式与 `tests/test_live_smoke.py` / `test_image_smoke.py` 一致。
#:
#: ⚠️ **2026-09-29 补 `pytest.mark.smoke`（原来漏了）**
#:
#: 上面写着「与 test_live_smoke.py 一致」，但**只抄了 skipif、没抄 smoke 标记** ——
#: 而 `pytest.ini` 的 addopts 里是 `-m "not smoke and not live"`，
#: 真正让那两个文件默认不跑的是 **smoke 标记**，不是 skipif。
#:
#: 后果：`backend/.env` 一配好 LLM key，`llm_configured` 变 True，
#: 这 4 条立刻从 skip 变成**真跑并真调 DashScope**，然后全红（实测 2026-09-29）。
#: 它们跑不通的原因是**环境错配**，不是被测实现有问题：
#:   · 本文件用 `client` 夹具 → 临时 SQLite + 模块 3 的迷你种子（2 场地 / 2 设备）；
#:   · 而真实模型是照着**完整 §6.9 种子**（8 场地 / 15 设备）来规划的。
#: 喂给模型一张 2 行的小表，它给不出合格方案（`data` 为 null），
#: 勉强给出的时段又会与种子里既有的单冲突（`/orders/create` 409）。
#: 这类断言**只能在云库上跑**（且 tc25 还要真写入，离线守卫会拦）。
#:
#: 因此：默认跳过（smoke），需要时显式 `pytest -m smoke -v` 跑，
#: 并清楚它会真消耗 API 额度、且大概率仍不通过 —— 那条属于云库联调范畴。
_NEEDS_LLM = pytest.mark.skipif(
    not settings.llm_configured,
    reason=(
        "未配置 LLM（backend/.env 缺 LLM_MODEL_NAME / LLM_API_KEY / LLM_BASE_URL）；"
        "/agent/schedule 会按设计返回 503 降级，拿不到 plan。配置后本用例自动参与。"
    ),
)


@pytest.mark.smoke
@_NEEDS_LLM
async def test_tc23_schedule_returns_structured_plan(client):
    """TC-23 文本调度返回 plan / backupPlan / trace / needConfirm。

    契约来源：团队 `docs/api.md` 模块 4（**已冻结**）。本用例把冻结字段集与
    「各步 timestamp 互不相同且递增」这两条固化成断言——前端按 TraceStep 逐字段
    渲染时间轴，字段或时间顺序一变，演示就崩。
    """
    r = await client.post(
        "/api/v1/agent/schedule",
        json={"text": "帮我预约明天上午的会议室", "imageContext": {}},
    )
    assert r.status_code == 200
    d = r.json()["data"]

    assert d["needConfirm"] is True
    # plan / backupPlan 的冻结字段集
    assert set(d["plan"]) >= {"spaceId", "spaceName", "deviceIds", "startTime", "endTime", "reason"}
    assert d["plan"]["spaceName"]  # 场地名不能为空（前端直接渲染）
    assert d["backupPlan"]["startTime"]

    # §5.3：trace 必须是**对象数组**，元素为 TraceStep
    assert isinstance(d["trace"], list) and d["trace"]
    step = d["trace"][0]
    assert set(step) >= {
        "step",
        "result",
        "timestamp",
        "thought",
        "action",
        "actionInput",
        "observation",
    }
    assert step["result"].startswith("解析需求")

    # 各步 timestamp 互不相同且递增，共用于时间轴回放
    stamps = [s["timestamp"] for s in d["trace"]]
    assert stamps == sorted(stamps)
    assert len(set(stamps)) == len(stamps)
    # step 从 1 递增
    assert [s["step"] for s in d["trace"]] == list(range(1, len(stamps) + 1))


async def test_tc24_empty_requirement_rejected(client):
    """TC-24 空需求 → 400 / 40001（团队基线，见 `docs/api.md` §1.4）。

    `ScheduleRequest.text` 的 `min_length=1` 由 Pydantic 触发，走团队异常处理器
    的 `RequestValidationError` 分支：HTTP 400、业务码 40001，FastAPI 默认的 422
    已被显式改掉。空串与缺字段两条路径都覆盖。
    """
    r = await client.post("/api/v1/agent/schedule", json={"text": ""})
    assert r.status_code == 400
    assert r.json()["code"] == ErrorCode.PARAM_INVALID

    r = await client.post("/api/v1/agent/schedule", json={})
    assert r.status_code == 400
    assert r.json()["code"] == ErrorCode.PARAM_INVALID


@pytest.mark.smoke
@_NEEDS_LLM
async def test_mock_schedule_avoids_occupied_slots(client):
    """mock 调度器应避让已占用时段（Agent 只调 Tool 查真实数据，§9.3）。"""
    occupied_start = time_str(1, 9)
    occupied_end = time_str(1, 11)
    await client.post(
        "/api/v1/orders/create",
        json={"spaceId": 1, "deviceIds": [], "startTime": occupied_start, "endTime": occupied_end},
    )

    plan = (
        await client.post("/api/v1/agent/schedule", json={"text": "明天上午要个会议室"})
    ).json()["data"]["plan"]
    # 主方案不应落在已占用时段内
    assert not (plan["startTime"] < occupied_end and plan["endTime"] > occupied_start)


@pytest.mark.smoke
@_NEEDS_LLM
async def test_tc25_confirm_plan_persists_order(client):
    """TC-25 方案确认落库：前端取 plan 调 orders/create。"""
    plan = (
        await client.post("/api/v1/agent/schedule", json={"text": "明天上午要个会议室"})
    ).json()["data"]["plan"]

    r = await client.post(
        "/api/v1/orders/create",
        json={
            "spaceId": plan["spaceId"],
            "deviceIds": plan["deviceIds"],
            "startTime": plan["startTime"],
            "endTime": plan["endTime"],
            "agentRequest": "明天上午要个会议室",
            "agentTrace": [
                {
                    "step": 1,
                    "result": "解析需求：明天上午要个会议室",
                    "timestamp": "2026-01-01 09:00:00",
                },
                {"step": 2, "result": "生成主方案与备方案", "timestamp": "2026-01-01 09:00:03"},
            ],
        },
    )
    assert r.status_code == 200
    assert r.json()["data"]["orderStatus"] == 1


async def test_tc26_agent_request_and_trace_persisted(client):
    """TC-26 agentRequest / agentTrace 完整落库，供溯源与前端可视化。

    agentTrace 的元素是 TraceStep 对象（团队冻结契约），落库为 JSON 数组、原样取回。
    """
    trace = [
        {
            "step": 1,
            "result": "解析需求：40人展厅带双投影",
            "timestamp": "2026-01-01 09:00:00",
            "thought": "先确认人数与预算约束",
            "action": None,
            "actionInput": None,
            "observation": None,
        },
        {
            "step": 2,
            "result": "查询可用场地与设备资源",
            "timestamp": "2026-01-01 09:00:03",
            "thought": "按 40 人容量检索",
            "action": "query_spaces",
            "actionInput": {"capacity": 40},
            "observation": {"spaces": []},
        },
        {
            "step": 3,
            "result": "检测时段冲突，进行方案权衡",
            "timestamp": "2026-01-01 09:00:06",
            "thought": None,
            "action": "check_conflict",
            "actionInput": None,
            "observation": None,
        },
        {
            "step": 4,
            "result": "生成主方案与备方案",
            "timestamp": "2026-01-01 09:00:09",
            "thought": None,
            "action": None,
            "actionInput": None,
            "observation": None,
        },
    ]
    r = await client.post(
        "/api/v1/orders/create",
        json={
            "spaceId": 1,
            "deviceIds": [1],
            "startTime": time_str(1, 9),
            "endTime": time_str(1, 10),
            "agentRequest": "40人展厅带双投影，预算1000内",
            "agentTrace": trace,
        },
    )
    oid = r.json()["data"]["orderId"]

    d = (await client.get(f"/api/v1/orders/{oid}")).json()["data"]
    assert d["agentRequest"] == "40人展厅带双投影，预算1000内"
    assert d["agentTrace"] == trace  # 数组原样落库
    assert len(d["agentTrace"]) == 4
    # 落库后仍是对象数组，前端可按字段取
    assert d["agentTrace"][0]["result"].startswith("解析需求")
    assert d["agentTrace"][1]["action"] == "query_spaces"


async def test_tc27_transcribe_placeholder_is_not_registered(client):
    """TC-27 **改写**：占位端点必须**不存在**（HTTP 404），而不是「返回占位文本」。

    ⚠️ **2026-09-28 改写。** 原文断言 `status_code == 200` 且 `data["text"]` 非空，
    但这两个端点所在的模块 `app/api/agent.py` **从未注册进应用**
    —— `backend/app/api/v1/__init__.py` 的注册区注释写得明确：

        模块 3 的 `app/api/agent.py` **不注册**：其 `/agent/schedule` 与模块 4 的
        `app/api/v1/agent.py` 路径重复（后者是走 LangChain 的真实调度实现），
        其 `/agent/transcribe`、`/agent/recognize` 是文件内自述的占位实现，
        已由 `/api/v1/voice/asr` 与 `/api/v1/image/analyze` 取代。

    所以「返回占位文本」在线上**根本不可达**，原断言等于在验一个不存在的端点。

    改成**反向护栏**：一旦有人把该模块加进注册区，两个同路径的 `/agent/schedule`
    会打架，本用例立刻报警。真能力由 `/api/v1/voice/asr`（模块 1）提供。
    """
    r = await client.post(
        "/api/v1/agent/transcribe",
        files={"file": ("voice.mp3", b"fake-audio-bytes", "audio/mpeg")},
    )

    assert r.status_code == 404, "模块 3 的 /agent/transcribe 不应被注册（已被 /voice/asr 取代）"
    assert r.json()["code"] == ErrorCode.NOT_FOUND


async def test_tc28_recognize_placeholder_is_not_registered(client):
    """TC-28 **改写**：占位端点必须**不存在**（HTTP 404）。

    理由与 TC-27 完全对称，见上一个用例的 docstring。
    真能力由 `/api/v1/image/analyze`（模块 2）提供。
    """
    r = await client.post(
        "/api/v1/agent/recognize",
        files={"file": ("room.jpg", b"fake-image-bytes", "image/jpeg")},
    )

    assert r.status_code == 404, "模块 3 的 /agent/recognize 不应被注册（已被 /image/analyze 取代）"
    assert r.json()["code"] == ErrorCode.NOT_FOUND


@pytest.mark.smoke
@_NEEDS_LLM
async def test_agent_flow_end_to_end(client):
    """Agent 闭环：提交需求 → 取方案 → 落库 → 列表可见 → 溯源完整。"""
    r = await client.post("/api/v1/agent/schedule", json={"text": "周五下午要个40人展厅"})
    body = r.json()["data"]
    plan, trace = body["plan"], body["trace"]

    created = await client.post(
        "/api/v1/orders/create",
        json={
            "spaceId": plan["spaceId"],
            "deviceIds": plan["deviceIds"],
            "startTime": plan["startTime"],
            "endTime": plan["endTime"],
            "agentRequest": "周五下午要个40人展厅",
            "agentTrace": trace,
        },
    )
    assert created.status_code == 200

    oid = created.json()["data"]["orderId"]
    my = (await client.get("/api/v1/orders/my")).json()["data"]
    assert [o["orderId"] for o in my] == [oid]
    assert my[0]["agentTrace"] == trace
    assert my[0]["userId"] == MOCK_USER_ID
