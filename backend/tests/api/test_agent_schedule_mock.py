"""Mock 思考链的「唯一真源」契约（模块 4）。

背景
----
`POST /api/v1/mock/agent/schedule` 的思考链是**一份数据三处用**：

    ① 前端屏 3 的思考链渲染
    ② 演示的 40 秒回放
    ③ 主文档 13.1 应急预案的预置 trace

原先代码里另写着一份 4 步 / 间隔 1 秒的常量，与
`docs/mock/agent_schedule.json` 的 7 步 / 39 秒各说各话。这类不一致**不报错**：
两边都能正常返回、前端也都能渲染，只有到演示现场才发现回放节奏和预置 trace
对不上，而那时已经没有排查时间了。

现在 json 是唯一真源（读法见 `app/api/v1/mock_data.py` 里 `AGENT_SCHEDULE`
上方的说明），本文件把它钉在三件事上：

    1. 数据确实来自那份 json，而不是代码里另抄的一份；
    2. 7 步、时间戳严格递增且首尾跨 39 秒 —— 「40 秒回放」的前提；
    3. 形状能过 `ScheduleData`。json 顶部自己写着「改这里必须同步改
       app/schemas/agent.py」，在这之前没有任何东西在执行这句告诫。

路径解析不在这里重写一遍，而是复用 `mock_data.AGENT_SCHEDULE_JSON_PATH`：
两处各写一份候选列表，正是本文件要防的那类漂移。
"""

from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest

from app.api.v1 import mock_data
from app.core.config import settings
from app.schemas.agent import ScheduleData
from tests.conftest import make_application

pytestmark = pytest.mark.api

SCHEDULE_PATH = "/api/v1/mock/agent/schedule"

#: json 的**约定位置**：仓库根 docs/mock/。模块 4 原实现按
#: `parents[4] / "docs" / "mock"` 找它，前端、演示回放、应急预案也都认这个路径。
REPO_ROOT_JSON = settings.backend_dir.parent.joinpath("docs", "mock", "agent_schedule.json")


# ==========================================================================
# 夹具（覆盖 conftest 的同名夹具，理由同 tests/api/test_mock_routes.py）
# ==========================================================================
@pytest.fixture
async def application(engine, token_store, metric_store, _reset_global_singletons, monkeypatch):
    """强制 `DEBUG=true` 后再建应用，使 Mock 路由一定被注册。"""
    monkeypatch.setattr(settings, "DEBUG", True)
    instance = make_application(engine, token_store)
    yield instance
    instance.dependency_overrides.clear()


# ==========================================================================
# 数据来源
# ==========================================================================
def test_schedule_json_is_present() -> None:
    """必须有数据文件被读到 —— 读不到时 mock_data 只会打日志并退化。

    这是本项目里唯一一条「文件没读到就报错」的检查：`_load_agent_schedule`
    刻意不抛异常（一个演示数据文件不该让整个应用起不来），代价是缺文件时
    接口会安静地返回空 data。那个代价由本用例补上。
    """
    assert mock_data.AGENT_SCHEDULE_JSON_PATH is not None, (
        "找不到思考链数据文件，候选路径："
        + " 或 ".join(str(path) for path in mock_data._AGENT_SCHEDULE_CANDIDATES)
        + "。该文件是前端屏 3 渲染、40 秒回放、13.1 应急预案三处共用，"
        "必须随仓库一同检出。"
    )


def test_repo_layout_reads_the_repo_root_copy() -> None:
    """仓库布局下必须命中**仓库根** `docs/mock/`，而不是 backend 内的副本。

    `backend/` 独立检出时（没有 <repo>/docs/）这条跳过 —— 那种布局下没有
    仓库根可言，位置本身不构成约束。
    """
    if not REPO_ROOT_JSON.is_file():
        pytest.skip(f"当前不是仓库布局（{REPO_ROOT_JSON} 不存在）")

    assert mock_data.AGENT_SCHEDULE_JSON_PATH == REPO_ROOT_JSON


def test_mock_data_is_loaded_from_the_json_file() -> None:
    """`mock_data.AGENT_SCHEDULE` 必须与 json 的 `data` 段逐字段一致。

    这条就是「不要再漂移」的闸门：若有人在代码里另写一份、或改了 json 忘了
    同步，这里立刻红。
    """
    assert mock_data.AGENT_SCHEDULE_JSON_PATH is not None
    payload = json.loads(mock_data.AGENT_SCHEDULE_JSON_PATH.read_text(encoding="utf-8"))

    assert payload["data"]  # 空 data 会让前端屏 3 白屏
    assert mock_data.AGENT_SCHEDULE == payload["data"]


async def test_endpoint_serves_the_json_data(client: httpx.AsyncClient) -> None:
    """接口对外返回的 data，就是 json 里那一份（HTTP 200 + 统一响应体）。"""
    response = await client.post(SCHEDULE_PATH, json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"code", "message", "data"}
    assert body["data"] == mock_data.AGENT_SCHEDULE


# ==========================================================================
# 40 秒回放的前提
# ==========================================================================
def test_trace_has_seven_steps() -> None:
    """7 步：解析 → 查场地 → 查投影仪 → 查音响 → 锁定 → 通知 → 交方案。"""
    trace = mock_data.AGENT_SCHEDULE["trace"]

    assert [step["step"] for step in trace] == [1, 2, 3, 4, 5, 6, 7]
    assert [step["action"] for step in trace] == [
        None,
        "query_spaces",
        "query_devices",
        "query_devices",
        "lock_resources",
        "generate_notification",
        "submit_plan",
    ]


def test_timestamps_are_strictly_increasing_and_span_39_seconds() -> None:
    """时间戳严格递增、互不相同，首尾相差 39 秒。

    「严格递增」不能被理解成「互不相同」就够 —— 前端按时间轴回放时，相同或
    倒退的时间戳会让两步挤在同一时刻出现，节奏就塌了。以前那份 4 步常量里
    第 2、3 步都写着 15:04:06，正是这种塌陷；这里连「相邻差值 > 0」一起断言。
    """
    stamps = [
        datetime.strptime(step["timestamp"], "%Y-%m-%d %H:%M:%S")
        for step in mock_data.AGENT_SCHEDULE["trace"]
    ]

    gaps = [
        (later - earlier).total_seconds()
        for earlier, later in zip(stamps, stamps[1:], strict=False)
    ]
    assert all(gap > 0 for gap in gaps), f"时间戳非严格递增，相邻间隔：{gaps}"
    assert (stamps[-1] - stamps[0]).total_seconds() == 39


# ==========================================================================
# 形状契约
# ==========================================================================
def test_trace_matches_schedule_data_schema() -> None:
    """形状必须能过 `ScheduleData` —— 它与模块 4 真实接口共用同一份契约。

    json 顶部写着「字段与阶段 2 冻结的 TraceStep / Plan / ScheduleData 逐一对应，
    改这里必须同步改 app/schemas/agent.py」，本用例就是那句告诫的执行者：
    schema 加了必填字段、或 json 写错了字段名，都在这里暴露，而不是等前端
    拿到一个渲染不出思考链的响应。
    """
    data = ScheduleData.model_validate(mock_data.AGENT_SCHEDULE)

    assert data.plan is not None and data.plan.spaceName == "A栋3楼展厅"
    assert data.backupPlan is not None
    assert data.needConfirm is True
    assert len(data.trace) == 7
    # 每一步都得有 Thought 可渲染（主文档 5.3 + 7.4），不能只有 result
    assert all(step.thought for step in data.trace)
