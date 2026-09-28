"""
Agent 工具：generate_notification

开发流程.md 9.3 的两条硬约束在这里被当成断言来守：
- 工具签名里不得出现 AsyncSession（会话由 services 层自建）
- 内部 Tool 不得注册为公开 HTTP 端点

另外，工具失败时必须返回可读 JSON 而不是抛异常 ——
抛异常会直接打断与用户的对话。
"""
from __future__ import annotations

import inspect
import json

import pytest

from app.agent.chains.notify_chain import NotifyDraft
from app.agent.prompts.notify_templates import ROLE_OWNER
from app.agent.tools import notify_tools
from app.agent.tools.notify_tools import NOTIFY_TOOLS, generate_notification
from app.services.notify_service import DispatchResult


class Recorder:
    def __init__(self, result: DispatchResult | None = None, error: Exception | None = None):
        self.calls: list[dict] = []
        self._result = result if result is not None else DispatchResult()
        self._error = error

    async def __call__(self, **kwargs) -> DispatchResult:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._result


OK_RESULT = DispatchResult(
    created=2,
    skipped=1,
    drafts={ROLE_OWNER: NotifyDraft("【预约提醒】A栋3楼展厅 14:00", "正文内容。", "ai_json")},
)


@pytest.fixture
def recorder(monkeypatch) -> Recorder:
    record = Recorder(OK_RESULT)
    monkeypatch.setattr(notify_tools, "dispatch_order_notification", record)
    return record


async def _invoke(**payload) -> dict:
    """走真实的工具调用链路（StructuredTool.ainvoke），而不是直接调函数"""
    raw = await generate_notification.ainvoke(payload)
    return json.loads(raw) if isinstance(raw, str) else raw


# ---------- 工具契约 ----------


def test_tool_is_named_as_the_contract_requires():
    assert generate_notification.name == "generate_notification"


def test_tool_has_a_description_for_the_model():
    assert generate_notification.description
    assert "order_id" in generate_notification.description


def test_tool_exposes_order_id_as_a_required_argument():
    schema = generate_notification.args_schema.model_json_schema()
    assert "order_id" in schema["properties"]
    assert "order_id" in schema.get("required", [])


def test_tool_signature_has_no_database_session():
    """
    ★ 开发流程.md 9.3：Tool 内禁止直接使用 AsyncSession，
    因此签名里不能出现任何会话对象。
    """
    signature = inspect.signature(generate_notification.coroutine)
    rendered = str(signature)
    assert "AsyncSession" not in rendered
    assert "session" not in signature.parameters


def test_tool_is_exported_for_the_main_agent():
    assert generate_notification in NOTIFY_TOOLS


# 已对模块 4（徐川的主调度 Agent）公开并冻结的签名。改动即跨模块接口变更。
FROZEN_SIGNATURE_PARAMS = ("order_id", "notify_type", "reason")


def test_tool_signature_is_frozen():
    """
    ★ 本签名已对模块 4 公开并冻结，不得再改。

    参数名、顺序、默认值、必填项都是跨模块契约的一部分：改动会让模块 4 的
    工具注册与提示词失效。确需变更时须同步知会模块 4，并更新
    docs/api.md「供给模块 4 的工具签名」一节。
    """
    params = inspect.signature(generate_notification.coroutine).parameters

    assert tuple(params) == FROZEN_SIGNATURE_PARAMS, "参数名或顺序变了"
    assert params["order_id"].default is inspect.Parameter.empty, "order_id 必须仍是必填"
    assert params["notify_type"].default == "提醒", "notify_type 的默认语气变了"
    assert params["reason"].default == "", "reason 的默认值变了"

    schema = generate_notification.args_schema.model_json_schema()
    assert sorted(schema["properties"]) == ["notify_type", "order_id", "reason"]
    assert schema.get("required") == ["order_id"], "必填项变了"
    assert generate_notification.name == "generate_notification"


def test_tool_is_not_registered_as_a_public_endpoint():
    """★ 开发流程.md：内部 Tool 禁止注册为公开 HTTP 端点"""
    from app.main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    assert not any("notify_tools" in path for path in paths)
    assert not any("generate_notification" in path for path in paths)


# ---------- 正常路径 ----------


async def test_success_returns_title_and_content(recorder):
    body = await _invoke(order_id=101, notify_type="提醒")

    assert body["code"] == 200
    assert body["title"] == "【预约提醒】A栋3楼展厅 14:00"
    assert body["content"] == "正文内容。"
    assert body["receivers"] == 3  # created 2 + skipped 1


async def test_defaults_are_sent_to_the_service(recorder):
    await _invoke(order_id=101)

    assert recorder.calls[0]["order_id"] == 101
    assert recorder.calls[0]["notify_type"] == "提醒"
    assert recorder.calls[0]["source"] == "agent"


async def test_empty_reason_becomes_none(recorder):
    await _invoke(order_id=101, reason="")

    assert recorder.calls[0]["reason"] is None


async def test_reason_is_forwarded(recorder):
    await _invoke(order_id=101, notify_type="延期致歉", reason="设备检修")

    assert recorder.calls[0]["reason"] == "设备检修"


# ---------- 失败路径 ----------


async def test_missing_order_returns_a_readable_error(monkeypatch):
    monkeypatch.setattr(
        notify_tools, "dispatch_order_notification", Recorder(DispatchResult())
    )

    body = await _invoke(order_id=999999)

    assert body["code"] == 404
    assert "999999" in body["message"]


@pytest.mark.parametrize("bad", [0, -1])
async def test_non_positive_order_id_is_rejected(monkeypatch, bad):
    record = Recorder(OK_RESULT)
    monkeypatch.setattr(notify_tools, "dispatch_order_notification", record)

    body = await _invoke(order_id=bad)

    assert body["code"] == 400
    assert record.calls == [], "参数不合法时不应打到底层服务"


async def test_service_failure_returns_an_error_instead_of_raising(monkeypatch):
    """★ 工具抛异常会打断对话，必须转成模型能读懂的 JSON"""
    monkeypatch.setattr(
        notify_tools,
        "dispatch_order_notification",
        Recorder(error=RuntimeError("模拟通知服务故障")),
    )

    body = await _invoke(order_id=101)

    assert body["code"] == 500
    assert body["message"]


async def test_error_payload_is_valid_json():
    """工具返回值会被模型直接读，格式必须稳定"""
    body = await _invoke(order_id=0)
    assert set(body) == {"code", "message"}
