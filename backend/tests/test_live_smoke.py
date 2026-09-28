"""
真实大模型 API 冒烟

开发流程.md 10.2：真实 API 只做一次冒烟验证，日常测试一律用假 LLM 夹具。
因此本文件默认全部跳过，必须显式启用：

    cd backend
    set RUN_LIVE_LLM=1            # PowerShell: $env:RUN_LIVE_LLM="1"
    pytest -m live -v

前置条件（缺一即跳过，不报错）：
- .env 里配好 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
- AI_ENABLED=true 且 AI_USE_FAKE_LLM=false（否则测的是假模型，冒烟没有意义）

失败了要看什么：断言会直接给出降级原因（timeout / api_error / json_parse_failed），
那是排查密钥、网络与模型名的最快入口。
"""
from __future__ import annotations

import os

import pytest

from app.agent.chains.extract_chain import extract_attendee_count
from app.agent.chains.llm import build_llm
from app.agent.chains.notify_chain import generate_notify_content
from app.core.config import settings

pytestmark = pytest.mark.live

FACTS = {
    "order_id": 1001,
    "space_name": "A栋3楼展厅",
    "user_name": "张三",
    "start_time": "2026-09-25 14:00",
    "end_time": "2026-09-25 16:00",
    "start_hm": "14:00",
    "date": "2026-09-25",
    "capacity": 40,
}

_live_reason: str | None = None
if os.getenv("RUN_LIVE_LLM", "").strip().lower() not in {"1", "true", "yes"}:
    _live_reason = "未设置 RUN_LIVE_LLM=1"
elif not settings.LLM_API_KEY:
    _live_reason = ".env 未配置 LLM_API_KEY"
elif not settings.AI_ENABLED:
    _live_reason = "AI_ENABLED=false，会走模板而不是真实 API"
elif settings.AI_USE_FAKE_LLM:
    _live_reason = "AI_USE_FAKE_LLM=true，测的是假模型"

requires_live = pytest.mark.skipif(_live_reason is not None, reason=_live_reason or "")


@requires_live
async def test_live_llm_produces_a_notification():
    """真实调用一次：必须拿到可用文案，且**不是**模板兜底"""
    draft = await generate_notify_content(
        notify_type="延期致歉",
        facts=FACTS,
        recipient_role="预约人",
        reason="场地临时被占用",
        llm=build_llm(),
    )

    assert draft.source != "template", (
        f"真实 API 未成功，降级原因：{draft.degraded_reason}"
    )
    assert draft.degraded_reason is None
    assert draft.title.strip()
    assert draft.content.strip()
    # 长度必须落在数据库列宽之内（title VARCHAR(255) / content TEXT）
    assert len(draft.title) <= 255


@requires_live
async def test_live_llm_output_is_grounded_in_the_facts():
    """
    冒烟不只验证「能返回」，还要验证「没胡编」：

    关掉 AI 时模板必定含场地名，这里要求真实模型也把场地名写进文案。
    若模型开始编造别的场地，说明 Prompt 里的输出约束失效了。
    """
    draft = await generate_notify_content(
        notify_type="提醒",
        facts=FACTS,
        recipient_role="预约人",
        llm=build_llm(),
    )

    assert draft.source != "template", f"降级原因：{draft.degraded_reason}"
    assert "A栋3楼展厅" in f"{draft.title}{draft.content}"


@requires_live
async def test_live_extraction_reads_the_attendee_count():
    """抽取链的真实 API 冒烟：需求原文里的人数必须被读出来"""
    count = await extract_attendee_count(
        "下周三下午办一场技术分享会，预计 18 人参加，需要投影和麦克风。",
        llm=build_llm(),
    )

    assert count == 18
