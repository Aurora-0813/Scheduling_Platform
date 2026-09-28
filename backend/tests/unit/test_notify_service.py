"""
通知服务层：角色语气映射、收件人解析、事实优先级、派发与幂等
"""
from __future__ import annotations

from datetime import datetime

import pytest
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage

from app.agent.prompts.notify_templates import (
    ROLE_OWNER,
    ROLE_RESOURCE_ADMIN,
    ROLE_SYSTEM_ADMIN,
)
from app.services import notify_service
from app.services.dedup import MemoryDedup
from app.services.notify_service import (
    OrderSnapshot,
    Recipient,
    build_order_facts,
    generate_and_dispatch,
    is_normal_role,
    pick_draft,
    resolve_recipients,
    role_key_for,
)

VALID_JSON = '{"title": "AI 标题", "content": "AI 正文内容，用于测试。"}'


class CountingLLM(FakeMessagesListChatModel):
    """统计底层生成被调用了几次，用来断言「同角色只调一次模型」"""

    # pydantic 模型不允许随意挂属性，计数器必须声明成字段
    calls: int = 0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        return super()._generate(messages, stop, run_manager, **kwargs)


@pytest.fixture
def counting_llm():
    return CountingLLM(responses=[AIMessage(content=VALID_JSON)] * 6)


class FakeSession:
    """只记录 add/flush 的假会话，不连数据库"""

    def __init__(self, fail_after: int | None = None) -> None:
        self.added: list = []
        self.flush_count = 0
        self._fail_after = fail_after

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1
        if self._fail_after is not None and self.flush_count >= self._fail_after:
            raise RuntimeError("模拟写库失败")


def _snapshot(**overrides) -> OrderSnapshot:
    data = dict(
        id=101,
        user_id=1,
        space_id=2,
        start_time=datetime(2026, 9, 25, 14, 0),
        end_time=datetime(2026, 9, 25, 16, 0),
        order_status=2,
        user_name="张三",
        user_role_name="普通使用者",
        space_name="A栋3楼展厅",
        capacity=40,
    )
    data.update(overrides)
    return OrderSnapshot(**data)


FACTS = {"space_name": "A栋3楼展厅", "user_name": "张三", "order_id": 101}


# ---------- 角色语气映射 ----------


@pytest.mark.parametrize(
    ("role_name", "expected"),
    [
        (None, ROLE_OWNER),
        ("", ROLE_OWNER),
        ("普通使用者", ROLE_OWNER),
        ("普通用户", ROLE_OWNER),
        ("资源管理员", ROLE_RESOURCE_ADMIN),
        ("系统管理员", ROLE_SYSTEM_ADMIN),
        ("运维值班员", ROLE_RESOURCE_ADMIN),
        (" 普通使用者 ", ROLE_OWNER),
    ],
)
def test_role_key_mapping(role_name, expected):
    assert role_key_for(role_name) == expected


def test_is_normal_role_never_guesses():
    """角色缺失时不假定其为管理员，避免对普通用户讲管理口径"""
    assert is_normal_role(None) is False
    assert is_normal_role("") is False
    assert is_normal_role("普通使用者") is True
    assert is_normal_role("资源管理员") is False


# ---------- 事实组装 ----------


def test_facts_come_from_the_database():
    facts = build_order_facts(_snapshot())

    assert facts["space_name"] == "A栋3楼展厅"
    assert facts["user_name"] == "张三"
    assert facts["start_hm"] == "14:00"
    assert facts["date"] == "2026-09-25"
    assert facts["capacity"] == 40


def test_payload_cannot_override_database_facts():
    """请求体不得改写库中已有的场地名等事实 —— 否则 AI 会把错名字写进正式通知"""
    facts = build_order_facts(_snapshot(), {"spaceName": "伪造的场地", "userName": "李四"})
    assert facts["space_name"] == "A栋3楼展厅"
    assert facts["user_name"] == "张三"


def test_payload_can_add_facts_the_database_does_not_have():
    facts = build_order_facts(_snapshot(), {"reason": "设备临时故障", "ruleLabel": "故障告警"})
    assert facts["reason"] == "设备临时故障"
    assert facts["rule_label"] == "故障告警"


@pytest.mark.parametrize(
    "key", ["userId", "user_id", "receiverId", "receiver_id", "notifyType", "type"]
)
def test_identity_keys_in_payload_are_dropped(key):
    """开发流程.md 5.1：身份标识禁止从请求体传入，防止身份伪造"""
    facts = build_order_facts(_snapshot(), {key: 999})
    assert 999 not in facts.values()
    assert key not in facts


def test_none_values_in_payload_are_dropped():
    facts = build_order_facts(_snapshot(), {"reason": None})
    assert "reason" not in facts


def test_facts_without_snapshot_are_payload_only():
    facts = build_order_facts(None, {"spaceName": "临时场地"})
    assert facts == {"space_name": "临时场地"}


def test_facts_fall_back_to_readable_placeholders():
    snapshot = _snapshot(space_name=None, user_name=None, capacity=None)
    facts = build_order_facts(snapshot)
    assert facts["space_name"] == "场地#2"
    assert facts["user_name"] == "用户#1"
    assert "capacity" not in facts


# ---------- 收件人解析 ----------


async def test_resolve_recipients_owner_only(monkeypatch):
    async def fake_recipient(session, user_id):
        return Recipient(user_id=user_id, username="张三", role_key=ROLE_OWNER)

    async def fake_admins(session):
        raise AssertionError("owner-only 受众不应查询管理员")

    monkeypatch.setattr(notify_service, "load_recipient", fake_recipient)
    monkeypatch.setattr(notify_service, "load_admin_recipients", fake_admins)

    from app.services.rules.base import AUDIENCE_OWNER_AND_ADMIN

    recipients = await resolve_recipients(
        None, audience=frozenset({"owner"}), owner_id=1
    )
    assert [r.user_id for r in recipients] == [1]
    assert AUDIENCE_OWNER_AND_ADMIN  # 契约常量可导入


async def test_resolve_recipients_admin_only(monkeypatch):
    async def fake_admins(session):
        return [
            Recipient(user_id=2, username="李管理", role_key=ROLE_RESOURCE_ADMIN),
            Recipient(user_id=3, username="王系统", role_key=ROLE_SYSTEM_ADMIN),
        ]

    monkeypatch.setattr(notify_service, "load_admin_recipients", fake_admins)

    from app.services.rules.base import AUDIENCE_ADMIN_ONLY

    recipients = await resolve_recipients(None, audience=AUDIENCE_ADMIN_ONLY, owner_id=1)
    assert [r.user_id for r in recipients] == [2, 3]


async def test_resolve_recipients_does_not_duplicate_an_admin_owner(monkeypatch):
    """管理员自己预约时，不应收到两遍同一条通知"""

    async def fake_recipient(session, user_id):
        return Recipient(
            user_id=user_id, username="李管理", role_key=ROLE_RESOURCE_ADMIN
        )

    async def fake_admins(session):
        return [
            Recipient(user_id=2, username="李管理", role_key=ROLE_RESOURCE_ADMIN),
            Recipient(user_id=3, username="王系统", role_key=ROLE_SYSTEM_ADMIN),
        ]

    monkeypatch.setattr(notify_service, "load_recipient", fake_recipient)
    monkeypatch.setattr(notify_service, "load_admin_recipients", fake_admins)

    from app.services.rules.base import AUDIENCE_OWNER_AND_ADMIN

    recipients = await resolve_recipients(
        None, audience=AUDIENCE_OWNER_AND_ADMIN, owner_id=2
    )
    assert [r.user_id for r in recipients] == [2, 3]


async def test_resolve_recipients_handles_missing_owner(monkeypatch):
    async def fake_recipient(session, user_id):
        return None

    monkeypatch.setattr(notify_service, "load_recipient", fake_recipient)

    recipients = await resolve_recipients(None, audience=frozenset({"owner"}), owner_id=99)
    assert recipients == []


# ---------- 派发 ----------


async def test_dispatch_writes_one_row_per_recipient(counting_llm):
    session = FakeSession()
    recipients = [
        Recipient(user_id=1, username="张三", role_key=ROLE_OWNER),
        Recipient(user_id=2, username="李管理", role_key=ROLE_OWNER),
    ]

    result = await generate_and_dispatch(
        session=session,
        recipients=recipients,
        dedup=MemoryDedup(),
        notify_type="提醒",
        facts=FACTS,
        rule_code="space_idle",
        llm=counting_llm,
    )

    assert result.created == 2
    assert result.skipped == 0
    assert len(session.added) == 2
    assert counting_llm.calls == 1, "同一语气角色的多个收件人只应调用一次模型"


async def test_dispatch_uses_one_call_per_distinct_role(counting_llm):
    session = FakeSession()
    recipients = [
        Recipient(user_id=1, username="张三", role_key=ROLE_OWNER),
        Recipient(user_id=2, username="李管理", role_key=ROLE_RESOURCE_ADMIN),
        Recipient(user_id=3, username="王系统", role_key=ROLE_SYSTEM_ADMIN),
    ]

    result = await generate_and_dispatch(
        session=session,
        recipients=recipients,
        dedup=MemoryDedup(),
        notify_type="提醒",
        facts=FACTS,
        rule_code="space_idle",
        llm=counting_llm,
    )

    assert result.created == 3
    assert counting_llm.calls == 3


async def test_dispatch_is_idempotent_within_ttl(counting_llm):
    """★ 幂等：第二轮扫描不得重复写库，也不该再白烧一次模型调用"""
    session = FakeSession()
    dedup = MemoryDedup()
    recipients = [Recipient(user_id=1, username="张三", role_key=ROLE_OWNER)]
    kwargs = dict(
        session=session,
        recipients=recipients,
        dedup=dedup,
        notify_type="提醒",
        facts=FACTS,
        rule_code="space_idle",
        llm=counting_llm,
    )

    first = await generate_and_dispatch(**kwargs)
    second = await generate_and_dispatch(**kwargs)

    assert (first.created, first.skipped) == (1, 0)
    assert (second.created, second.skipped) == (0, 1)
    assert len(session.added) == 1
    assert counting_llm.calls == 1, "被去重压掉的轮次不应调用模型"


async def test_dispatch_writes_notify_message_fields(counting_llm):
    session = FakeSession()
    await generate_and_dispatch(
        session=session,
        recipients=[Recipient(user_id=7, username="张三", role_key=ROLE_OWNER)],
        dedup=MemoryDedup(),
        notify_type="延期致歉",
        facts=FACTS,
        rule_code="continuous_activity",
        order_ids=(101, 102),
        space_id=2,
        order_id=101,
        llm=counting_llm,
    )

    message = session.added[0]
    assert message.receiver_id == 7
    assert message.notify_type == 2
    assert message.order_id == 101
    assert message.title == "AI 标题"
    assert message.content == "AI 正文内容，用于测试。"
    assert message.is_read == 0


async def test_dispatch_releases_the_slot_when_insert_fails(counting_llm):
    """
    写库失败必须归还去重名额，否则一次瞬时故障会让该通知被压一整天。
    这里让第一次 flush 抛错，第二次应当能重新写入。
    """
    dedup = MemoryDedup()
    recipients = [Recipient(user_id=1, username="张三", role_key=ROLE_OWNER)]
    kwargs = dict(
        recipients=recipients,
        dedup=dedup,
        notify_type="提醒",
        facts=FACTS,
        rule_code="space_idle",
        llm=counting_llm,
    )

    failing = FakeSession(fail_after=1)
    first = await generate_and_dispatch(session=failing, **kwargs)
    assert first.failed == 1
    assert first.created == 0

    # 关键：名额已归还，换一个健康会话重试应当能正常写入
    healthy = FakeSession()
    second = await generate_and_dispatch(session=healthy, **kwargs)
    assert second.created == 1
    assert len(healthy.added) == 1


async def test_dispatch_with_no_recipients_does_nothing(counting_llm):
    session = FakeSession()
    result = await generate_and_dispatch(
        session=session,
        recipients=[],
        dedup=MemoryDedup(),
        notify_type="提醒",
        facts=FACTS,
        rule_code="space_idle",
        llm=counting_llm,
    )
    assert result.created == 0
    assert result.targeted == 0
    assert counting_llm.calls == 0


async def test_dispatch_reuses_precomputed_draft(counting_llm):
    """接口层已为调用方角色生成过文案，派发时不应再调一次模型"""
    from app.agent.chains.notify_chain import NotifyDraft

    session = FakeSession()
    result = await generate_and_dispatch(
        session=session,
        recipients=[Recipient(user_id=1, username="张三", role_key=ROLE_OWNER)],
        dedup=MemoryDedup(),
        notify_type="提醒",
        facts=FACTS,
        rule_code="manual_notify",
        llm=counting_llm,
        precomputed={ROLE_OWNER: NotifyDraft("预生成标题", "预生成正文", "ai_json")},
    )

    assert counting_llm.calls == 0
    assert session.added[0].title == "预生成标题"


async def test_dispatch_survives_ai_outage(monkeypatch):
    """
    AI 全挂时仍必须写出模板文案 —— 通知链路不允许因 AI 失败而中断
    （开发流程.md 4.2：移除 AI 后降级为硬冲突检测，业务链路不中断）
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "AI_ENABLED", False)

    session = FakeSession()
    result = await generate_and_dispatch(
        session=session,
        recipients=[Recipient(user_id=1, username="张三", role_key=ROLE_OWNER)],
        dedup=MemoryDedup(),
        notify_type="提醒",
        facts=FACTS,
        rule_code="space_idle",
        llm=None,  # AI_ENABLED=False 时不得构造真实客户端
    )

    assert result.created == 1
    assert result.drafts[ROLE_OWNER].source == "template"
    assert session.added[0].title


# ---------- pick_draft ----------


def test_pick_draft_prefers_the_callers_role():
    from app.agent.chains.notify_chain import NotifyDraft
    from app.services.notify_service import DispatchResult

    result = DispatchResult(
        drafts={
            ROLE_OWNER: NotifyDraft("给预约人的", "", "template"),
            ROLE_RESOURCE_ADMIN: NotifyDraft("给管理员的", "", "template"),
        }
    )
    assert pick_draft(result, ROLE_RESOURCE_ADMIN).title == "给管理员的"


def test_pick_draft_falls_back_to_owner_then_anything():
    from app.agent.chains.notify_chain import NotifyDraft
    from app.services.notify_service import DispatchResult

    result = DispatchResult(drafts={ROLE_OWNER: NotifyDraft("预约人版", "", "template")})
    assert pick_draft(result, ROLE_SYSTEM_ADMIN).title == "预约人版"

    result = DispatchResult(
        drafts={ROLE_SYSTEM_ADMIN: NotifyDraft("系统管理员版", "", "template")}
    )
    assert pick_draft(result, ROLE_OWNER).title == "系统管理员版"


def test_pick_draft_returns_none_when_nothing_was_generated():
    from app.services.notify_service import DispatchResult

    assert pick_draft(DispatchResult(), ROLE_OWNER) is None
