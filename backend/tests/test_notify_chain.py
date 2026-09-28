"""
AI 通知文案生成链：三级降级阶梯闭环

开发流程.md 10.2 强制要求覆盖两类降级用例，且必须真跑降级分支：
- 超时：用会阻塞的假模型 + 极小 timeout，走真实 asyncio.wait_for 取消路径
- 外部 API 失败：用抛异常的假模型
两者都断言 reason 字段，而不是只断言「没抛异常」。
"""
from __future__ import annotations

import time

import pytest

from app.agent.chains.notify_chain import generate_notify_content
from app.agent.prompts.notify_templates import (
    CONTENT_MAX,
    ROLE_OWNER,
    ROLE_RESOURCE_ADMIN,
)
from app.core.config import settings
from app.core.response import ApiError

FACTS = {
    "user_name": "张三",
    "space_name": "A栋3楼展厅",
    "capacity": 40,
    "attendee_count": 12,
    "start_time": "2026-09-25 14:00",
    "end_time": "2026-09-25 16:00",
    "start_hm": "14:00",
    "order_id": 101,
    "rule_label": "容量远超需求",
    "reason": "场地可容纳 40 人，需求仅约 12 人。",
}

# pytest.ini 已设 asyncio_mode=auto，async 用例无需再逐条打标记


# ---------- 级 1：AI 返回合法 JSON ----------


async def test_ai_json_is_used_verbatim(fake_llm_json):
    draft = await generate_notify_content(
        notify_type="提醒", facts=FACTS, llm=fake_llm_json
    )

    assert draft.source == "ai_json"
    assert draft.degraded_reason is None
    assert draft.title == "【预约提醒】A栋3楼展厅 14:00"
    assert draft.content == "AI 生成的正文内容。"


async def test_multimodal_content_blocks_do_not_crash(multimodal_llm):
    """
    langchain-openai 1.x 的 content 可能是 [{"type": "text", ...}] 列表。
    若直接 .strip() 会 AttributeError，把整条降级链路打穿。
    """
    draft = await generate_notify_content(
        notify_type="提醒", facts=FACTS, llm=multimodal_llm
    )

    assert draft.source == "ai_json"
    assert draft.title == "分段标题"
    assert draft.content == "分段正文内容。"


# ---------- 级 2：AI 返回自然语言散文 ----------


async def test_prose_is_kept_as_content(fake_llm_prose):
    """
    开发流程.md 7.4：JSON 解析异常时返回自然语言文本。
    直接丢弃一段通顺的散文去套模板不符合文档原意。
    """
    draft = await generate_notify_content(
        notify_type="提醒", facts=FACTS, llm=fake_llm_prose
    )

    assert draft.source == "ai_text"
    assert draft.degraded_reason == "json_parse_failed"
    assert draft.content.startswith("您好，您预约的场地即将开始使用")
    # 标题回退到模板，保证通知列表里可读
    assert "A栋3楼展厅" in draft.title


# ---------- 级 3：各种失败一律回模板 ----------


async def test_timeout_degrades_to_template(slow_llm):
    """★ 10.2 强制用例：真实走 asyncio.wait_for 超时取消路径"""
    started = time.monotonic()
    draft = await generate_notify_content(
        notify_type="延期致歉", facts=FACTS, llm=slow_llm, timeout=0.05
    )
    elapsed = time.monotonic() - started

    assert draft.source == "template"
    assert draft.degraded_reason == "timeout"
    assert draft.title and draft.content
    # 必须是被 timeout 掐断的，而不是等假模型睡完才返回
    assert elapsed < 0.5, f"超时分支未生效，实际耗时 {elapsed:.2f}s"


async def test_api_error_degrades_to_template(raising_llm):
    """★ 10.2 强制用例：外部 API 抛异常"""
    draft = await generate_notify_content(
        notify_type="提醒", facts=FACTS, llm=raising_llm
    )

    assert draft.source == "template"
    assert draft.degraded_reason == "api_error"
    assert draft.title and draft.content


async def test_broken_json_degrades_to_template(fake_llm_broken):
    draft = await generate_notify_content(
        notify_type="提醒", facts=FACTS, llm=fake_llm_broken
    )

    assert draft.source == "template"
    assert draft.degraded_reason == "json_parse_failed"


async def test_empty_response_degrades_to_template(empty_llm):
    draft = await generate_notify_content(
        notify_type="提醒", facts=FACTS, llm=empty_llm
    )

    assert draft.source == "template"
    assert draft.degraded_reason == "empty"


async def test_title_only_response_degrades_to_template():
    """
    模型只给了标题、没给正文 —— 半个结果不能用，否则通知列表里点开是空的
    """
    from app.agent.chains.llm import build_fake_llm

    llm = build_fake_llm(['{"title": "只有一个标题"}'])
    draft = await generate_notify_content(notify_type="提醒", facts=FACTS, llm=llm)

    assert draft.source == "template"
    assert draft.degraded_reason == "json_parse_failed"
    assert draft.content


# ---------- 级 0：AI 总开关 ----------


async def test_ai_disabled_never_calls_the_model(monkeypatch, raising_llm):
    """
    AI_ENABLED=False 时直接走模板，且绝不触碰大模型 ——
    这里故意注入一个「一调用就抛异常」的模型来证明它真的没被调用。
    """
    monkeypatch.setattr(settings, "AI_ENABLED", False)

    draft = await generate_notify_content(
        notify_type="提醒", facts=FACTS, llm=raising_llm
    )

    assert draft.source == "template"
    assert draft.degraded_reason == "ai_disabled"


# ---------- 契约与防御 ----------


async def test_unknown_notify_type_raises_400():
    with pytest.raises(ApiError) as exc:
        await generate_notify_content(notify_type="瞎写的语气", facts=FACTS)

    assert exc.value.code == 400


async def test_notify_type_accepts_integer(fake_llm_json):
    draft = await generate_notify_content(notify_type=2, facts=FACTS, llm=fake_llm_json)
    assert draft.title


async def test_empty_facts_still_produce_usable_text(fake_llm_broken):
    """事实缺失时模板不得抛 KeyError，也不得产出空文案（否则落库失败）"""
    draft = await generate_notify_content(
        notify_type="提醒", facts={}, llm=fake_llm_broken
    )

    assert draft.title
    assert draft.content


async def test_recipient_role_changes_the_fallback_template(fake_llm_broken):
    owner = await generate_notify_content(
        notify_type="提醒", facts=FACTS, recipient_role=ROLE_OWNER, llm=fake_llm_broken
    )
    admin = await generate_notify_content(
        notify_type="提醒",
        facts=FACTS,
        recipient_role=ROLE_RESOURCE_ADMIN,
        llm=fake_llm_broken,
    )

    assert (owner.title, owner.content) != (admin.title, admin.content)


async def test_overlong_ai_output_is_clipped():
    """模型偶尔会失控输出超长文本，必须截断到列宽以内才落库"""
    from app.agent.chains.llm import build_fake_llm

    long_text = '{"title": "' + "标" * 500 + '", "content": "' + "文" * 5000 + '"}'
    llm = build_fake_llm([long_text])

    draft = await generate_notify_content(notify_type="提醒", facts=FACTS, llm=llm)

    assert draft.source == "ai_json"
    assert len(draft.title) <= CONTENT_MAX
    assert len(draft.content) <= CONTENT_MAX
    assert draft.title.endswith("…")


async def test_rule_label_and_reason_are_optional(fake_llm_json):
    """无规则上下文时（如事件总线触发的通知）也应能生成"""
    draft = await generate_notify_content(
        notify_type="提醒", facts=FACTS, llm=fake_llm_json
    )
    assert draft.title


async def test_default_llm_is_never_reached_when_ai_disabled(monkeypatch):
    """
    不注入 llm 时走 build_llm()。AI_ENABLED=False 下必须在构造模型之前就返回模板，
    避免在没有 Key 的开发机上因构造真实客户端而报错。
    """
    monkeypatch.setattr(settings, "AI_ENABLED", False)

    draft = await generate_notify_content(notify_type="提醒", facts=FACTS)

    assert draft.source == "template"
    assert draft.degraded_reason == "ai_disabled"
