"""
Mock 路由的测试（模块 10，文档 8.8）

Mock 路由的价值在于**让前端与小程序在后端接口还没写出来时就能开工**，
因此两份契约必须稳定：

1. 每个 Mock 接口都返回 200 + 统一响应体 + **camelCase 字段**；
2. Mock 只在 `DEBUG=true` 时存在，`DEBUG=false` 时连路径都应该是 404。

第 2 条不是洁癖：Mock 里全是假数据，线上漏出会让人以为系统里有数据
（更糟的是前端照着假数据画出来的图被认为「已经联调通过」）。

第 1 条里 camelCase 那一项**必须**在这里测：`app/api/v1/mock_data.py` 里的
示例数据是**手写 dict**，不经过 Pydantic，因此 `alias_generator=to_camel`
对它们完全无效 —— 漏写一个驼峰不会有任何报错，但前端取 `item.spaceId`
会得到 `undefined`。本文件用递归检查兜住这个盲区。

本文件里的 `application` 夹具是**有意覆盖** conftest 的同名夹具：
Mock 路由在 `create_app()` 里按 `settings.DEBUG` 决定注不注册，
所以必须先改配置、再建应用。
"""

from __future__ import annotations

import re

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import settings
from app.core.error_codes import ErrorCode
from tests.conftest import make_application

pytestmark = pytest.mark.api

MOCK_PREFIX = "/api/v1/mock"
SIMULATE_PATH = f"{MOCK_PREFIX}/monitor/simulate"

_IMAGE = ("shot.jpg", b"\xff\xd8\xff\xe0mock-jpeg", "image/jpeg")
_AUDIO = ("voice.wav", b"RIFFmock-wav", "audio/wav")

# (method, path, httpx 请求参数)。路径用**注册时的模板**写（含 `{orderId}`），
# 这样它既能直接和 `app.routes` 的 path 比对，也能经 `_concrete()` 变成可请求的 URL。
#
# 这张表就是 Mock 接口的**清单**：模块 1~8 的负责人照着它开发，
# 前端照着它联调。少写一行就会有人来问「这个接口的 mock 呢」。
MOCK_CALLS: list[tuple[str, str, dict]] = [
    # 模块 1：语音交互
    ("POST", f"{MOCK_PREFIX}/voice/asr", {"files": {"file": _AUDIO}}),
    ("POST", f"{MOCK_PREFIX}/voice/format", {"json": {"text": "明天下午两点开会"}}),
    # 模块 2：图像识别
    ("POST", f"{MOCK_PREFIX}/image/analyze", {"files": {"file": _IMAGE}}),
    ("POST", f"{MOCK_PREFIX}/image/sketch", {"files": {"file": _IMAGE}}),
    # 模块 3：预约与消息
    (
        "POST",
        f"{MOCK_PREFIX}/orders/create",
        {"json": {"spaceId": 1, "startTime": "2026-10-01 09:00:00"}},
    ),
    ("GET", f"{MOCK_PREFIX}/orders/my", {}),
    ("PUT", f"{MOCK_PREFIX}/orders/{{orderId}}/cancel", {"json": {}}),
    ("GET", f"{MOCK_PREFIX}/messages/unread", {}),
    # 模块 4：核心调度 Agent
    ("POST", f"{MOCK_PREFIX}/agent/schedule", {"json": {"requirement": "安排一场 10 人会议"}}),
    # 模块 5：资源与设备
    ("GET", f"{MOCK_PREFIX}/resources/spaces", {}),
    ("POST", f"{MOCK_PREFIX}/resources/spaces", {"json": {"name": "会议室 A"}}),
    ("GET", f"{MOCK_PREFIX}/resources/devices", {}),
    ("PUT", f"{MOCK_PREFIX}/resources/devices/{{deviceId}}", {"json": {"status": 1}}),
    # 模块 6：巡检与工单
    (
        "POST",
        f"{MOCK_PREFIX}/inspect/submit",
        {"files": {"file": _IMAGE}, "data": {"spaceId": "1"}},
    ),
    ("GET", f"{MOCK_PREFIX}/tickets/list", {}),
    ("PUT", f"{MOCK_PREFIX}/tickets/{{ticketId}}/status", {"json": {"status": 2}}),
    # 模块 7：冲突与通知
    ("GET", f"{MOCK_PREFIX}/conflicts/scan", {}),
    ("POST", f"{MOCK_PREFIX}/notify/generate", {"json": {"type": "order_remind"}}),
    # 模块 8：数据洞察
    ("GET", f"{MOCK_PREFIX}/dashboard/stats", {}),
    ("GET", f"{MOCK_PREFIX}/dashboard/report", {}),
    # 模块 10：演示用的埋点灌数据工具（不在前端契约里，但属于 Mock 路由）
    ("POST", SIMULATE_PATH, {}),
]

# 注册后应当出现的全部 Mock 路径（去重，因为 /resources/spaces 同时有 GET 与 POST）
EXPECTED_PATHS = {path for _, path, _ in MOCK_CALLS}

_CALL_IDS = [f"{method}-{path.replace(MOCK_PREFIX, '')}" for method, path, _ in MOCK_CALLS]

_PATH_PARAM = re.compile(r"\{[^}]+\}")


def _concrete(path: str) -> str:
    """把 `/orders/{orderId}/cancel` 变成可请求的 `/orders/1/cancel`。"""
    return _PATH_PARAM.sub("1", path)


# ==========================================================================
# 夹具（覆盖 conftest 的同名夹具，见模块 docstring）
# ==========================================================================
@pytest.fixture
async def application(engine, token_store, metric_store, _reset_global_singletons, monkeypatch):
    """强制 `DEBUG=true` 后再建应用，使 Mock 路由一定被注册。"""
    monkeypatch.setattr(settings, "DEBUG", True)
    instance = make_application(engine, token_store)
    yield instance
    instance.dependency_overrides.clear()


# ==========================================================================
# 注册状态：DEBUG 开 / 关
# ==========================================================================
def _mock_paths(app: FastAPI) -> set[str]:
    return {
        route.path for route in app.routes if getattr(route, "path", "").startswith(MOCK_PREFIX)
    }


def test_mock_routes_are_registered_when_debug_is_on(monkeypatch) -> None:
    from app.main import create_app

    monkeypatch.setattr(settings, "DEBUG", True)

    paths = _mock_paths(create_app())
    assert paths == EXPECTED_PATHS, (
        "注册的 Mock 路径与本文件的 MOCK_CALLS 表不一致。"
        f"只在代码里: {sorted(paths - EXPECTED_PATHS)}；"
        f"只在测试表里: {sorted(EXPECTED_PATHS - paths)}"
    )


def test_mock_routes_are_absent_when_debug_is_off(monkeypatch) -> None:
    """`DEBUG=false` 时连注册都不发生，路径应当整体消失。"""
    from app.main import create_app

    monkeypatch.setattr(settings, "DEBUG", False)

    assert _mock_paths(create_app()) == set()


async def test_mock_paths_are_404_when_debug_is_off(
    monkeypatch, engine, token_store, metric_store, _reset_global_singletons
) -> None:
    """HTTP 层面确认：不是换了前缀，而是真的不存在。"""
    monkeypatch.setattr(settings, "DEBUG", False)
    instance = make_application(engine, token_store)

    transport = httpx.ASGITransport(app=instance)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as prod:
        response = await prod.get(f"{MOCK_PREFIX}/dashboard/stats")

    assert response.status_code == 404
    assert response.json()["code"] == ErrorCode.NOT_FOUND


# ==========================================================================
# 契约：全部 Mock 接口
# ==========================================================================
@pytest.mark.parametrize(("method", "path", "kwargs"), MOCK_CALLS, ids=_CALL_IDS)
async def test_mock_call_returns_envelope(client, method: str, path: str, kwargs: dict) -> None:
    """每个 Mock 接口都返回 200 + 统一响应体 + 非空 data。"""
    response = await client.request(method, _concrete(path), **kwargs)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"code", "message", "data"}, body
    assert body["code"] == ErrorCode.SUCCESS
    assert body["data"] not in (None, {}, []), f"{method} {path} 返回了空 data"


@pytest.mark.parametrize(("method", "path", "kwargs"), MOCK_CALLS, ids=_CALL_IDS)
async def test_mock_response_keys_are_camel_case(
    client, method: str, path: str, kwargs: dict
) -> None:
    """
    递归检查响应里的**键**不含下划线。

    手写 dict 不经过 Pydantic，`alias_generator` 对它们无效（见模块 docstring），
    因此这是唯一能拦住 `space_id` / `start_time` 这类漏网的检查。

    豁免 `actionInput` 与 `observation` 两棵子树，理由见 `_OPAQUE_SUBTREES`。
    """
    response = await client.request(method, _concrete(path), **kwargs)

    offenders = _underscore_keys(response.json()["data"])
    assert not offenders, f"{method} {path} 返回了 snake_case 字段: {offenders}"


# 这两棵子树里的键名**不归后端定**，因此不参与 camelCase 检查：
#
#   actionInput —— 模型的 Tool 调用入参，键名就是 `app/agent/tools/*.py` 里
#                  LangChain 工具的形参名（`space_type`、`device_ids`、
#                  `start_time`… 见 query_spaces / lock_resources 的签名）；
#   observation —— 被调工具的**原样**返回。
#
# 把 Mock 里的它们改成驼峰，看起来是「更规范」，实际是让 Mock 与模块 4 的真实
# 返回长得不一样 —— 恰好踩中本文件 docstring 第 1 条要防的事（拿 Mock 调通的
# 前端，切真实接口时崩）。真正该是驼峰的是工具**内部**再返回给前端的部分
# （`spaceName`、`orderId`、`deviceName`），那些在子树里仍然是驼峰。
_OPAQUE_SUBTREES = frozenset({"actionInput", "observation"})


def _underscore_keys(
    value: object, prefix: str = "data", opaque: frozenset[str] = _OPAQUE_SUBTREES
) -> list[str]:
    """递归找出所有含下划线的键，返回可读路径便于定位。

    `opaque` 里的键：**记它自己**（键名本身仍是驼峰，仍要检查），但不往下走。
    """
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if "_" in str(key):
                found.append(f"{prefix}.{key}")
            if key in opaque:
                continue
            found.extend(_underscore_keys(item, f"{prefix}.{key}", opaque))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_underscore_keys(item, f"{prefix}[{index}]", opaque))
    return found


async def test_mock_inspect_submit_requires_space_id(client) -> None:
    """FormData 接口的必填项缺失时给出可读的参数错误（不是 500）。"""
    response = await client.post(f"{MOCK_PREFIX}/inspect/submit", files={"file": _IMAGE})

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == ErrorCode.PARAM_INVALID
    assert body["data"]["errors"][0]["field"] == "spaceId"


# ==========================================================================
# 模块 4 的降级约定
# ==========================================================================
async def test_agent_schedule_marks_degraded_on_demand(client) -> None:
    """`?degraded=true` 必须带上响应头，供埋点中间件统计降级次数。"""
    response = await client.post(
        f"{MOCK_PREFIX}/agent/schedule", json={}, params={"degraded": "true"}
    )

    assert response.status_code == 200
    assert response.headers["X-Agent-Degraded"] == "1"


async def test_agent_schedule_has_no_degraded_header_by_default(client) -> None:
    response = await client.post(f"{MOCK_PREFIX}/agent/schedule", json={})

    assert "X-Agent-Degraded" not in response.headers


# ==========================================================================
# 与监控埋点的关系
# ==========================================================================
async def test_mock_traffic_is_not_counted_as_agent_traffic(client) -> None:
    """
    Mock 路由与真实 Agent 埋点**互不干扰**。

    `/api/v1/mock/agent/schedule` 的路径里有 "agent"，但它不在
    `/api/v1/agent/` 前缀下，因此不该被计入 —— 否则演示时数字里会混进
    Mock 流量，说不清哪些是真实调用。
    """
    await client.post(f"{MOCK_PREFIX}/agent/schedule", json={})

    data = (await client.get("/api/v1/monitor/agent")).json()["data"]
    assert data["totalCalls"] == 0


async def test_simulate_feeds_the_monitor_endpoint(client) -> None:
    """
    `/mock/monitor/simulate` 灌数据 → `/monitor/agent` 立刻反映出来。

    这条链路是演示用的：模块 4 未完成时，面板靠它才有数据可展示。
    """
    response = await client.post(
        SIMULATE_PATH,
        params={"count": 20, "errorRatio": 0.1, "degradedRatio": 0.25, "latencyMs": 3000},
    )

    assert response.status_code == 200
    assert response.json()["data"]["written"] == 20

    data = (await client.get("/api/v1/monitor/agent", params={"detail": "true"})).json()["data"]
    assert data["totalCalls"] == 20
    assert data["successCalls"] == 18
    assert data["errorCalls"] == 2
    assert data["degradedCalls"] == 5
    assert data["successRate"] == 90.0
    assert data["degradedRate"] == 25.0
    assert data["avgLatency"] == 3.0


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"count": 0}, "count"),
        ({"count": 501}, "count"),
        ({"errorRatio": 1.5}, "errorRatio"),
        ({"latencyMs": -1}, "latencyMs"),
    ],
)
async def test_simulate_validates_its_parameters(client, params: dict, field: str) -> None:
    """灌数据的比例/次数都有上限，越界要报参数错误而不是写出荒谬的统计值。"""
    response = await client.post(SIMULATE_PATH, params=params)

    assert response.status_code == 400
    assert response.json()["data"]["errors"][0]["field"] == field
