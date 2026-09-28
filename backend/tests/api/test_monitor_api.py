"""
监控接口与 Agent 埋点中间件的测试（模块 10）

本文件覆盖三件事，每一件都对应一条设计约束：

1. **契约形状**：`GET /monitor/agent` 在任何情况下都返回
   `totalCalls` / `successRate` / `avgLatency` 三个字段（无流量时是 `0 / 100.0 / 0.0`），
   `?detail=true` 才追加明细。理由是前端面板要不做判空就能渲染。

2. **单位**：`successRate` 是 0~100 的**百分比**、`avgLatency` 是**秒**。
   换算只在 `app/services/monitor_service.py` 做一处，所以这里直接对接口断言
   （`96.1` 而不是 `0.961`、`3.2` 而不是 `3200`）—— 一旦有人把换算挪到别处
   或漏了乘 100，本文件立刻失败。

3. **埋点绝不影响业务**：埋点存储抛异常时，业务接口必须照常返回 200、
   监控接口必须照常返回数据。这两条由 `_ExplodingMetricStore` 强制触发。

关于「探针路由」
----------------
模块 4 的 `/api/v1/agent/*` 尚未实现，因此本文件在运行时用
`_attach_probe()` 往 on-the-fly 的应用实例上挂一个临时路由。
中间件只看路径，因此这足以真实地走完「请求 → 中间件计时 → 统计」的全过程，
比直接调 `record_agent_call()` 更有说服力。**生产代码不参与**这件事。
"""

from __future__ import annotations

import pytest
from fastapi import Response
from fastapi.responses import JSONResponse

from app.core.error_codes import ErrorCode
from app.core.metrics import MetricStore, configure_metric_store
from app.core.response import error_payload, ok

pytestmark = pytest.mark.api

MONITOR_PATH = "/api/v1/monitor/agent"
DEGRADED_HEADER = "X-Agent-Degraded"

# 文档 5.3 约定的三字段（无论是否有流量都必须返回）
CONTRACT_FIELDS = frozenset({"totalCalls", "successRate", "avgLatency"})


# ==========================================================================
# 辅助
# ==========================================================================
def _attach_probe(app, path: str, *, status: int = 200, degraded: str | None = None) -> None:
    """
    给应用挂一个 Agent 探针路由。

    :param status: 返回的 HTTP 状态码。>=400 时用统一错误信封，模拟真实失败。
    :param degraded: 非 None 时设置 `X-Agent-Degraded` 响应头。
    """

    @app.get(path, name=f"probe_{path.strip('/').replace('/', '_')}")
    async def _probe(response: Response):
        # 不写返回类型注解：FastAPI 会把注解当作 response_model，
        # 而本函数可能返回两种不同的响应对象。
        if degraded is not None:
            response.headers[DEGRADED_HEADER] = degraded
        if status >= 400:
            return JSONResponse(
                status_code=status,
                content=error_payload(ErrorCode.INTERNAL_ERROR),
            )
        return ok({"probe": True})


async def _read_metrics(client, *, detail: bool = True) -> dict:
    """读一次 `/monitor/agent` 的 data。"""
    response = await client.get(MONITOR_PATH, params={"detail": "true"} if detail else None)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == ErrorCode.SUCCESS, body
    return body["data"]


class _ExplodingMetricStore(MetricStore):
    """
    每个方法都抛异常的指标存储。

    `app/middlewares/agent_metrics.py` 与 `app/services/monitor_service.py`
    都承诺「埋点故障不影响业务」，本类是这两条承诺的触发装置。
    """

    def __init__(self, *, record: bool = True, snapshot: bool = True, reset: bool = True) -> None:
        self._fail_record = record
        self._fail_snapshot = snapshot
        self._fail_reset = reset
        self.record_attempts = 0

    async def record_agent_call(self, **_kwargs: object) -> None:
        self.record_attempts += 1
        if self._fail_record:
            raise RuntimeError("模拟埋点存储故障")

    async def snapshot(self):
        if self._fail_snapshot:
            raise RuntimeError("模拟埋点存储故障")
        raise AssertionError("本类不支持正常快照")

    async def reset(self) -> None:
        if self._fail_reset:
            raise RuntimeError("模拟埋点存储故障")


# ==========================================================================
# 契约形状
# ==========================================================================
async def test_monitor_agent_returns_three_contract_fields_when_idle(client) -> None:
    """无任何 Agent 流量时也必须返回三个契约字段，而不是空对象或报错。"""
    data = await _read_metrics(client, detail=False)

    assert set(data) == CONTRACT_FIELDS
    # 无调用时成功率按 100% 展示（0% 会让人以为全挂了），耗时 0
    assert data == {"totalCalls": 0, "successRate": 100.0, "avgLatency": 0.0}


async def test_monitor_agent_detail_adds_breakdown_fields(client) -> None:
    """`?detail=true` 追加明细，并给出数据来源。"""
    data = await _read_metrics(client, detail=True)

    assert set(data) == CONTRACT_FIELDS | {
        "successCalls",
        "errorCalls",
        "degradedCalls",
        "degradedRate",
        "source",
    }
    assert data["successCalls"] == 0
    assert data["errorCalls"] == 0
    assert data["degradedCalls"] == 0
    assert data["degradedRate"] == 0.0
    # 测试环境 REDIS_ENABLED=false（见 tests/conftest.py），走进程内实现
    assert data["source"] == "memory"


async def test_monitor_agent_rejects_invalid_detail_param(client) -> None:
    """`detail` 不是布尔值时走统一参数校验错误，而不是 500。"""
    response = await client.get(MONITOR_PATH, params={"detail": "maybe"})

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == ErrorCode.PARAM_INVALID
    assert body["data"]["errors"][0]["field"] == "detail"


async def test_monitor_endpoint_does_not_count_itself(client) -> None:
    """`/monitor/agent` 自己不属于 `/agent/*`，反复调用不应改变统计值。"""
    for _ in range(3):
        await client.get(MONITOR_PATH)

    assert (await _read_metrics(client))["totalCalls"] == 0


# ==========================================================================
# 单位换算（0~1 → 百分比、毫秒 → 秒）
# ==========================================================================
async def test_units_are_percent_and_seconds(client, metric_store) -> None:
    """
    10 次调用、1 次失败、2 次降级、每次 3200ms。

    期望：`successRate=90.0`（不是 0.9）、`avgLatency=3.2`（不是 3200）。
    """
    for index in range(10):
        await metric_store.record_agent_call(
            latency_ms=3200.0,
            success=index >= 1,
            degraded=index < 2,
        )

    data = await _read_metrics(client)

    assert data["totalCalls"] == 10
    assert data["successRate"] == 90.0
    assert data["avgLatency"] == 3.2
    assert data["successCalls"] == 9
    assert data["errorCalls"] == 1
    assert data["degradedCalls"] == 2
    assert data["degradedRate"] == 20.0


async def test_success_rate_rounds_to_one_decimal(client, metric_store) -> None:
    """3 次调用里 2 次成功 → 66.7，而不是 66 或 66.66666666666666。"""
    for index in range(3):
        await metric_store.record_agent_call(latency_ms=0.0, success=index < 2)

    assert (await _read_metrics(client))["successRate"] == 66.7


# ==========================================================================
# 埋点中间件：路径匹配与成功/降级判定
# ==========================================================================
async def test_agent_request_is_counted(application, client) -> None:
    """真实走一次 `/api/v1/agent/*` 请求，统计值必须是 1。"""
    _attach_probe(application, "/api/v1/agent/probe")

    response = await client.get("/api/v1/agent/probe")
    assert response.status_code == 200
    assert response.json() == {"code": 200, "message": "操作成功", "data": {"probe": True}}

    data = await _read_metrics(client)
    assert data["totalCalls"] == 1
    assert data["successCalls"] == 1
    assert data["successRate"] == 100.0


async def test_unmapped_agent_path_is_still_counted(client) -> None:
    """
    未注册的 `/agent/*` 路径（404）也要被计入。

    这条断言证明中间件在**路由之外**：请求还没找到路由就被计了一次。
    若哪天有人把埋点挪进路由依赖里，模块 4 上线前的 404 就会被漏计。
    """
    response = await client.get("/api/v1/agent/not-implemented-yet")
    assert response.status_code == 404

    data = await _read_metrics(client)
    assert data["totalCalls"] == 1
    assert data["successRate"] == 0.0
    assert data["errorCalls"] == 1


async def test_paths_outside_agent_prefix_are_not_counted(client) -> None:
    """
    前缀边界必须带 `/`：`/api/v1/agentx` 不算 Agent 接口。

    同时确认健康检查、登录等常见路径都不会污染统计值。
    """
    await client.get("/api/v1/health")
    await client.get("/api/v1/agentx")
    await client.post("/api/v1/auth/login", json={"username": "nobody", "password": "whatever"})

    assert (await _read_metrics(client))["totalCalls"] == 0


async def test_failed_status_code_counts_as_error(application, client) -> None:
    """HTTP 500 记为失败；判定只看状态码，不解析响应体。"""
    _attach_probe(application, "/api/v1/agent/fail", status=500)

    response = await client.get("/api/v1/agent/fail")
    assert response.status_code == 500
    assert response.json()["code"] == ErrorCode.INTERNAL_ERROR

    data = await _read_metrics(client)
    assert data["totalCalls"] == 1
    assert data["errorCalls"] == 1
    assert data["successRate"] == 0.0


async def test_degraded_header_marks_call_but_keeps_it_successful(application, client) -> None:
    """
    降级由下游响应头标记，且**不压低成功率**。

    大模型降级通常仍返回 200，若并入 successRate，模块 4 大量降级时
    面板会显示成「系统故障」。因此降级单列进 `degradedCalls`。
    """
    _attach_probe(application, "/api/v1/agent/ok")
    _attach_probe(application, "/api/v1/agent/degraded", degraded="1")

    await client.get("/api/v1/agent/ok")
    response = await client.get("/api/v1/agent/degraded")
    # 头是原样透传的，中间件只读取、不修改
    assert response.headers[DEGRADED_HEADER] == "1"

    data = await _read_metrics(client)
    assert data["totalCalls"] == 2
    assert data["degradedCalls"] == 1
    assert data["successCalls"] == 2
    assert data["successRate"] == 100.0


@pytest.mark.parametrize("value", ["1", "TRUE", "true", "Yes", " y "])
async def test_truthy_degraded_values_are_recognised(application, client, value: str) -> None:
    """约定之外的大小写与空白也要认（模块 4 由不同的人实现，写法不会统一）。"""
    _attach_probe(application, "/api/v1/agent/truthy", degraded=value)

    await client.get("/api/v1/agent/truthy")

    assert (await _read_metrics(client))["degradedCalls"] == 1


@pytest.mark.parametrize("value", ["0", "false", "False", "no", ""])
async def test_falsy_degraded_values_are_ignored(application, client, value: str) -> None:
    """显式写 0/false 不能被当成降级 —— 否则统计值会虚高。"""
    _attach_probe(application, "/api/v1/agent/falsy", degraded=value)

    await client.get("/api/v1/agent/falsy")

    data = await _read_metrics(client)
    assert data["totalCalls"] == 1
    assert data["degradedCalls"] == 0


# ==========================================================================
# 故障隔离（决策：埋点绝不影响业务）
# ==========================================================================
async def test_broken_metric_store_does_not_break_business_endpoint(application, client) -> None:
    """
    埋点写入抛异常时，业务接口必须照常返回 200。

    这是「埋点绝不影响业务」的回归测试：中间件的 `_record()` 全包在
    try/except 里，任何异常只记日志。
    """
    store = _ExplodingMetricStore()
    configure_metric_store(store)
    _attach_probe(application, "/api/v1/agent/probe")

    response = await client.get("/api/v1/agent/probe")

    assert response.status_code == 200
    assert response.json()["data"] == {"probe": True}
    # 确认异常路径真的被走到过 —— 否则这条用例可能在「埋点没执行」时假绿
    assert store.record_attempts == 1


async def test_broken_metric_store_does_not_break_monitor_endpoint(client) -> None:
    """指标读取失败时，监控接口返回零值快照而不是 500（面板挂了就没人看得到它了）。"""
    configure_metric_store(_ExplodingMetricStore())

    data = await _read_metrics(client, detail=False)

    assert data == {"totalCalls": 0, "successRate": 100.0, "avgLatency": 0.0}


async def test_metric_store_failure_is_logged(
    client, metric_store, caplog: pytest.LogCaptureFixture
) -> None:
    """
    埋点失败必须留下痕迹。

    完全静默的埋点故障会让面板长期显示 0 而无人察觉 ——
    必须能找到「什么时候开始不记了」。
    """
    configure_metric_store(_ExplodingMetricStore())

    with caplog.at_level("WARNING"):
        assert (await _read_metrics(client))["totalCalls"] == 0

    assert any("指标" in record.getMessage() for record in caplog.records)


# ==========================================================================
# 出参模型的字段裁剪
# ==========================================================================
async def test_detail_false_drops_none_fields(client) -> None:
    """
    `detail=false` 时明细字段必须从 JSON 里消失（而不是变成 null）。

    前端面板对 `degradedRate: null` 做 `toFixed(1)` 会直接报错，
    因此路由上设了 `response_model_exclude_none=True`。
    """
    response = await client.get(MONITOR_PATH)

    assert "successCalls" not in response.text
    assert "null" not in response.text
    assert isinstance(response.json()["data"], dict)


async def test_ok_wrapper_keeps_camel_case(client) -> None:
    """出参字段是 camelCase（`totalCalls` 而非 `total_calls`），契约见文档 5.3。"""
    data = (await client.get(MONITOR_PATH)).json()["data"]

    assert "totalCalls" in data
    assert all("_" not in key for key in data)
