"""
大模型构建器

`build_llm` 是全模块唯一的 LLM 出口，3.3 要求「全部走云端 API」，
13.1 要求「API 欠费时一键切假 LLM」。

这里构造的是**真实的** ChatOpenAI 对象（构造不发网络请求），
从而验证参数确实被 SDK 接受 —— 用假对象替身只能证明我们传了什么，
证明不了这些参数名是对的。
"""
from __future__ import annotations

import pytest

from app.agent.chains.llm import build_fake_llm, build_llm
from app.core.config import settings


@pytest.fixture
def live_llm_settings(monkeypatch):
    """打开真实 LLM 分支：既没被 AI 总开关关掉，也没被应急预案切成假 LLM"""
    monkeypatch.setattr(settings, "AI_ENABLED", True)
    monkeypatch.setattr(settings, "AI_USE_FAKE_LLM", False)
    return settings


def test_real_branch_builds_a_chat_openai_client(live_llm_settings):
    """★ 真分支必须构造出 ChatOpenAI —— 3.3 要求云端 API，不能悄悄退回本地模型"""
    from langchain_openai import ChatOpenAI

    llm = build_llm()

    assert isinstance(llm, ChatOpenAI)


def test_client_carries_the_configured_model(live_llm_settings):
    assert build_llm().model_name == settings.LLM_MODEL


def test_client_carries_the_configured_base_url(live_llm_settings):
    """项目用的是自建网关地址，不能被 SDK 默认值悄悄改写"""
    llm = build_llm()

    if settings.LLM_BASE_URL:
        assert llm.openai_api_base == settings.LLM_BASE_URL


def test_client_does_not_retry_aggressively(live_llm_settings):
    """
    ★ 成本护栏：max_retries 固定为 1。

    超时 20 秒的重试若交给 SDK 默认值（2 次），一次调用最坏会拖到 60 秒，
    而调用方是「持有连接时也照样调」的通知链路 —— 2 核 2G 上会把连接池占死。
    """
    assert build_llm().max_retries == 1


def test_timeout_defaults_to_the_configured_value(live_llm_settings):
    assert build_llm().request_timeout == settings.LLM_TIMEOUT_SECONDS


def test_an_explicit_timeout_wins(live_llm_settings):
    """接口层可对单次调用收紧超时，不被全局配置覆盖"""
    assert build_llm(timeout=0.05).request_timeout == 0.05


def test_temperature_is_configurable(live_llm_settings):
    assert build_llm(temperature=0.0).temperature == 0.0


def test_a_missing_api_key_does_not_break_construction(live_llm_settings, monkeypatch):
    """
    ★ 未配置 Key 时必须构造成功。

    故意传占位值而不是抛异常：让失败发生在**调用**时，从而落到统一的
    降级链路（模板兜底）上，而不是在构造期抛出一个没人处理的异常。
    """
    monkeypatch.setattr(settings, "LLM_API_KEY", "")

    assert build_llm() is not None


def test_ai_disabled_returns_the_fake_instead_of_a_real_client(monkeypatch):
    """13.1 应急预案：AI 总开关关闭时不能再去连真实 API"""
    from langchain_openai import ChatOpenAI

    monkeypatch.setattr(settings, "AI_ENABLED", False)
    monkeypatch.setattr(settings, "AI_USE_FAKE_LLM", False)

    assert not isinstance(build_llm(), ChatOpenAI)


def test_the_fake_switch_returns_the_fake_even_when_ai_is_enabled(monkeypatch):
    monkeypatch.setattr(settings, "AI_ENABLED", True)
    monkeypatch.setattr(settings, "AI_USE_FAKE_LLM", True)

    from langchain_openai import ChatOpenAI

    assert not isinstance(build_llm(), ChatOpenAI)


def test_the_fake_does_not_exhaust_after_repeated_calls():
    """
    ★ 夹具要经得起连打。

    一轮扫描可能对多个订单连续富化，若响应列表只备一份，
    第二次调用就会 IndexError —— 那会让「离线可跑」变成「只能跑一次」。
    """
    import asyncio

    llm = build_fake_llm(responses=["第一份", "第二份"])

    async def call_times(n: int) -> list[str]:
        out = []
        for _ in range(n):
            msg = await llm.ainvoke("给我一份文案")
            out.append(msg.content)
        return out

    contents = asyncio.run(call_times(5))

    assert contents[0] == "第一份"
    assert contents[1] == "第二份"
    assert len(contents) == 5, "夹具耗尽会让连打的用例随机失败"


def test_the_fake_defaults_to_a_parseable_notification():
    """默认响应必须是一份**能解析出 title/content** 的合法 JSON，
    否则依赖「AI 成功」的用例会全都悄悄落到模板分支上。"""
    from app.agent.chains.json_utils import parse_llm_json

    parsed = parse_llm_json(build_fake_llm().responses[0].content)

    assert parsed is not None
    assert parsed.get("title")
    assert parsed.get("content")
