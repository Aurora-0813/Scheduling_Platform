"""Agent 联动与语音/图像占位入口（docs/test.md TC-23 ~ TC-28）。"""
from .helpers import MOCK_USER_ID, time_str


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
    assert set(d["plan"]) >= {
        "spaceId", "spaceName", "deviceIds", "startTime", "endTime", "reason"
    }
    assert d["plan"]["spaceName"]                      # 场地名不能为空（前端直接渲染）
    assert d["backupPlan"]["startTime"]

    # §5.3：trace 必须是**对象数组**，元素为 TraceStep
    assert isinstance(d["trace"], list) and d["trace"]
    step = d["trace"][0]
    assert set(step) >= {
        "step", "result", "timestamp", "thought", "action", "actionInput", "observation"
    }
    assert step["result"].startswith("解析需求")

    # 各步 timestamp 互不相同且递增，共用于时间轴回放
    stamps = [s["timestamp"] for s in d["trace"]]
    assert stamps == sorted(stamps)
    assert len(set(stamps)) == len(stamps)
    # step 从 1 递增
    assert [s["step"] for s in d["trace"]] == list(range(1, len(stamps) + 1))


async def test_tc24_empty_requirement_rejected(client):
    """TC-24 空需求 → 422。"""
    r = await client.post("/api/v1/agent/schedule", json={"text": ""})
    assert r.status_code == 422

    r = await client.post("/api/v1/agent/schedule", json={})
    assert r.status_code == 422


async def test_mock_schedule_avoids_occupied_slots(client):
    """mock 调度器应避让已占用时段（Agent 只调 Tool 查真实数据，§9.3）。"""
    occupied_start = time_str(1, 9)
    occupied_end = time_str(1, 11)
    await client.post(
        "/api/v1/orders/create",
        json={"spaceId": 1, "deviceIds": [], "startTime": occupied_start,
              "endTime": occupied_end},
    )

    plan = (await client.post("/api/v1/agent/schedule",
                              json={"text": "明天上午要个会议室"})).json()["data"]["plan"]
    # 主方案不应落在已占用时段内
    assert not (plan["startTime"] < occupied_end and plan["endTime"] > occupied_start)


async def test_tc25_confirm_plan_persists_order(client):
    """TC-25 方案确认落库：前端取 plan 调 orders/create。"""
    plan = (await client.post("/api/v1/agent/schedule",
                              json={"text": "明天上午要个会议室"})).json()["data"]["plan"]

    r = await client.post("/api/v1/orders/create", json={
        "spaceId": plan["spaceId"],
        "deviceIds": plan["deviceIds"],
        "startTime": plan["startTime"],
        "endTime": plan["endTime"],
        "agentRequest": "明天上午要个会议室",
        "agentTrace": [
            {"step": 1, "result": "解析需求：明天上午要个会议室",
             "timestamp": "2026-01-01 09:00:00"},
            {"step": 2, "result": "生成主方案与备方案",
             "timestamp": "2026-01-01 09:00:03"},
        ],
    })
    assert r.status_code == 200
    assert r.json()["data"]["orderStatus"] == 1


async def test_tc26_agent_request_and_trace_persisted(client):
    """TC-26 agentRequest / agentTrace 完整落库，供溯源与前端可视化。

    agentTrace 的元素是 TraceStep 对象（团队冻结契约），落库为 JSON 数组、原样取回。
    """
    trace = [
        {"step": 1, "result": "解析需求：40人展厅带双投影",
         "timestamp": "2026-01-01 09:00:00", "thought": "先确认人数与预算约束",
         "action": None, "actionInput": None, "observation": None},
        {"step": 2, "result": "查询可用场地与设备资源",
         "timestamp": "2026-01-01 09:00:03", "thought": "按 40 人容量检索",
         "action": "query_spaces",
         "actionInput": {"capacity": 40}, "observation": {"spaces": []}},
        {"step": 3, "result": "检测时段冲突，进行方案权衡",
         "timestamp": "2026-01-01 09:00:06", "thought": None,
         "action": "check_conflict", "actionInput": None, "observation": None},
        {"step": 4, "result": "生成主方案与备方案",
         "timestamp": "2026-01-01 09:00:09", "thought": None,
         "action": None, "actionInput": None, "observation": None},
    ]
    r = await client.post("/api/v1/orders/create", json={
        "spaceId": 1, "deviceIds": [1],
        "startTime": time_str(1, 9), "endTime": time_str(1, 10),
        "agentRequest": "40人展厅带双投影，预算1000内",
        "agentTrace": trace,
    })
    oid = r.json()["data"]["orderId"]

    d = (await client.get(f"/api/v1/orders/{oid}")).json()["data"]
    assert d["agentRequest"] == "40人展厅带双投影，预算1000内"
    assert d["agentTrace"] == trace          # 数组原样落库
    assert len(d["agentTrace"]) == 4
    # 落库后仍是对象数组，前端可按字段取
    assert d["agentTrace"][0]["result"].startswith("解析需求")
    assert d["agentTrace"][1]["action"] == "query_spaces"


async def test_tc27_transcribe_placeholder(client):
    """TC-27 语音转写占位：返回占位文本（真实 ASR 由队友模块接入）。"""
    r = await client.post(
        "/api/v1/agent/transcribe",
        files={"file": ("voice.mp3", b"fake-audio-bytes", "audio/mpeg")},
    )
    assert r.status_code == 200
    assert r.json()["data"]["text"]


async def test_tc28_recognize_placeholder(client):
    """TC-28 图像识别占位：返回占位文本（真实识别由队友模块接入）。"""
    r = await client.post(
        "/api/v1/agent/recognize",
        files={"file": ("room.jpg", b"fake-image-bytes", "image/jpeg")},
    )
    assert r.status_code == 200
    assert r.json()["data"]["text"]


async def test_agent_flow_end_to_end(client):
    """Agent 闭环：提交需求 → 取方案 → 落库 → 列表可见 → 溯源完整。"""
    r = await client.post("/api/v1/agent/schedule", json={"text": "周五下午要个40人展厅"})
    body = r.json()["data"]
    plan, trace = body["plan"], body["trace"]

    created = await client.post("/api/v1/orders/create", json={
        "spaceId": plan["spaceId"], "deviceIds": plan["deviceIds"],
        "startTime": plan["startTime"], "endTime": plan["endTime"],
        "agentRequest": "周五下午要个40人展厅", "agentTrace": trace,
    })
    assert created.status_code == 200

    oid = created.json()["data"]["orderId"]
    my = (await client.get("/api/v1/orders/my")).json()["data"]
    assert [o["orderId"] for o in my] == [oid]
    assert my[0]["agentTrace"] == trace
    assert my[0]["userId"] == MOCK_USER_ID
