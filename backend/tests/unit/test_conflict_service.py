"""
冲突扫描编排：建议生成、契约转换、AI 富化、四段式扫描

本文件重点验证一条架构约束：**段2（AI 富化）与段3（跑规则）必须在
不持有数据库会话的情况下执行**。这里的假会话会记录自己的存活状态，
若将来有人把 AI 调用挪进事务里，这条用例会立刻失败。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta

import pytest

from app.core.config import settings
from app.services import conflict_service
from app.services.conflict_service import (
    DEFAULT_SUGGESTION,
    MAX_ENRICH_ORDERS,
    SUGGESTIONS,
    ScanSummary,
    build_conflict_items,
    enrich_attendees,
    scan_and_notify_job,
    suggest_for,
)
from app.services.notify_service import DispatchResult
from app.services.rules.base import AUDIENCE_OWNER_AND_ADMIN, RuleHit

VALID_JSON = '{"title": "AI 标题", "content": "AI 正文内容，用于测试。"}'


def _hit(**overrides) -> RuleHit:
    data = dict(
        rule_code="space_idle",
        rule_label="长期闲置",
        order_ids=(),
        reason="场地 A栋301会议室 在最近 14 天内没有任何有效预约。",
        space_id=1,
        audience=AUDIENCE_OWNER_AND_ADMIN,
        facts={"space_name": "A栋301会议室"},
    )
    data.update(overrides)
    return RuleHit(**data)


# ---------- 确定性建议 ----------


@pytest.mark.parametrize("rule_code", list(SUGGESTIONS))
def test_every_rule_has_its_own_suggestion(rule_code):
    assert suggest_for(_hit(rule_code=rule_code)) == SUGGESTIONS[rule_code]


def test_unknown_rule_falls_back_to_default_suggestion():
    """新增规则忘了补建议时不能返回空串，前端会显示一个空白项"""
    assert suggest_for(_hit(rule_code="brand_new_rule")) == DEFAULT_SUGGESTION


def test_suggestion_never_mentions_the_ai():
    """
    建议文本是规则内置口径，不由 AI 生成 ——
    /conflicts/scan 是看板轮询的只读接口，逐条调模型会让它从毫秒变成几十秒
    """
    for text in SUGGESTIONS.values():
        assert "AI" not in text
        assert text.strip()


# ---------- 契约转换 ----------


def test_conflict_item_keys_match_the_contract_exactly():
    """
    契约锁定字段名，CamelModel 负责蛇形转驼峰。
    多一个或少一个字段都会破坏前端，故这里断言**恰好**这四个。
    """
    items = build_conflict_items([_hit(order_ids=(1, 2))])
    payload = items[0].model_dump(by_alias=True)
    assert set(payload) == {"conflictType", "orderIds", "suggestion", "ruleCode"}


def test_conflict_item_values():
    items = build_conflict_items([_hit(order_ids=(1, 2))])
    assert items[0].conflict_type == "软冲突"
    assert items[0].order_ids == [1, 2]
    assert items[0].rule_code == "space_idle"


def test_idle_conflict_has_empty_order_ids():
    """闲置冲突没有关联订单，契约允许空数组而非 null"""
    payload = build_conflict_items([_hit()])[0].model_dump(by_alias=True)
    assert payload["orderIds"] == []


def test_build_conflict_items_preserves_order():
    hits = [_hit(rule_code="a"), _hit(rule_code="b"), _hit(rule_code="c")]
    assert [item.rule_code for item in build_conflict_items(hits)] == ["a", "b", "c"]


def test_empty_hits_produce_empty_list():
    assert build_conflict_items([]) == []


# ---------- AI 富化 ----------


def _llm_returning(count: int):
    from app.agent.chains.llm import build_fake_llm

    return build_fake_llm([f'{{"attendeeCount": {count}}}'])


async def test_enrich_fills_attendee_count(now, make_order, make_context):
    order = make_order(1, agent_request="大概来十来个人", attendee_count=None)
    ctx = make_context([order])

    enriched_ctx, count = await enrich_attendees(ctx, llm=_llm_returning(10))

    assert count == 1
    assert enriched_ctx.orders[0].attendee_count == 10
    # 不可变快照：原上下文不得被就地修改
    assert ctx.orders[0].attendee_count is None


async def test_enrich_skips_orders_without_request_text(now, make_order, make_context):
    order = make_order(1, agent_request=None)
    ctx, count = await enrich_attendees(make_context([order]), llm=_llm_returning(10))
    assert count == 0


async def test_enrich_skips_orders_that_already_have_a_count(
    now, make_order, make_context
):
    order = make_order(1, agent_request="40 人", attendee_count=40)
    ctx, count = await enrich_attendees(make_context([order]), llm=_llm_returning(10))
    assert count == 0


async def test_enrich_skips_finished_orders(now, make_order, make_context):
    """已结束的预约不再富化：既打扰用户也白烧 token"""
    order = make_order(
        1, agent_request="10 人", start=now - timedelta(hours=5), end=now - timedelta(hours=4)
    )
    ctx, count = await enrich_attendees(make_context([order]), llm=_llm_returning(10))
    assert count == 0


async def test_enrich_respects_the_cost_cap(monkeypatch, now, make_order, make_context):
    """单轮扫描的模型调用次数必须有上限，否则 2 核 2G 上会被打满"""
    monkeypatch.setattr(conflict_service, "MAX_ENRICH_ORDERS", 2)

    orders = [
        make_order(i, agent_request=f"{i} 人", start=now + timedelta(hours=i))
        for i in range(1, 5)
    ]
    enriched_ctx, count = await enrich_attendees(
        make_context(orders), llm=_llm_returning(3)
    )

    assert count == 2
    filled = [o for o in enriched_ctx.orders if o.attendee_count is not None]
    assert len(filled) == 2
    # 就近优先：先富化开始时间最早的两笔
    assert [o.id for o in filled] == [1, 2]


async def test_enrich_never_raises_on_ai_failure(monkeypatch, now, make_order, make_context):
    """
    模型不可用时富化静默跳过，绝不让整轮扫描失败。
    需求原文刻意不含数字，以确认返回 None 是「AI 与正则都没抽到」而非正则兜住了。
    """

    class Boom:
        async def ainvoke(self, messages):
            raise RuntimeError("模型不可用")

    monkeypatch.setattr(settings, "AI_ENABLED", True)
    ctx = make_context([make_order(1, agent_request="人数待定")])

    enriched_ctx, count = await enrich_attendees(ctx, llm=Boom())

    assert count == 0
    assert enriched_ctx.orders[0].attendee_count is None


async def test_enrich_regex_still_works_when_the_model_is_down(
    monkeypatch, now, make_order, make_context
):
    """模型挂了但原文里有明确人数时，正则兜底应把人数补上"""

    class Boom:
        async def ainvoke(self, messages):
            raise RuntimeError("模型不可用")

    monkeypatch.setattr(settings, "AI_ENABLED", True)
    ctx = make_context([make_order(1, agent_request="预计 18 人参加")])

    enriched_ctx, count = await enrich_attendees(ctx, llm=Boom())

    assert count == 1
    assert enriched_ctx.orders[0].attendee_count == 18


async def test_enrich_on_empty_snapshot_is_a_noop(make_context):
    ctx, count = await enrich_attendees(make_context(), llm=_llm_returning(5))
    assert count == 0


def test_max_enrich_orders_is_a_sane_cost_guard():
    assert 0 < MAX_ENRICH_ORDERS <= 50


# ---------- 四段式扫描 ----------


class StubSession:
    """只记录写入的假会话"""

    def __init__(self) -> None:
        self.added: list = []
        self.flushes = 0
        self.committed = False

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.committed = True


class ScopeTracker:
    """记录会话存活状态的假会话上下文，用于断言 AI 调用不发生在事务内"""

    def __init__(self) -> None:
        self.open_count = 0
        self.sessions: list[StubSession] = []
        self.ai_saw_open_sessions: list[int] = []
        self.rules_saw_open_sessions: list[int] = []

    @asynccontextmanager
    async def scope(self):
        self.open_count += 1
        session = StubSession()
        self.sessions.append(session)
        try:
            yield session
        finally:
            self.open_count -= 1


@pytest.fixture
def tracked(monkeypatch) -> ScopeTracker:
    """把 session_scope 换成可观测的假实现，一次都不碰真实数据库"""
    tracker = ScopeTracker()
    monkeypatch.setattr(conflict_service, "session_scope", tracker.scope)
    return tracker


async def test_scan_job_does_not_hold_a_session_while_calling_ai(
    tracked, monkeypatch, now, make_context, make_order
):
    """
    ★ 架构约束：调 AI 时不能持有数据库连接。
    一次模型调用 3~20 秒，持有连接会瞬间占满 2 核 2G 上的连接池。
    """
    ctx = make_context([make_order(1, agent_request="10 人")])

    async def fake_load(session, *, now=None):
        return ctx

    async def fake_enrich(context, *, llm=None, timeout=None):
        tracked.ai_saw_open_sessions.append(tracked.open_count)
        return context, 0

    def fake_run_all(context):
        tracked.rules_saw_open_sessions.append(tracked.open_count)
        return [_hit()]

    async def fake_persist(session, hits, *, dedup, llm=None, timeout=None):
        return DispatchResult(created=1)

    monkeypatch.setattr(conflict_service, "load_rule_context", fake_load)
    monkeypatch.setattr(conflict_service, "enrich_attendees", fake_enrich)
    monkeypatch.setattr(conflict_service, "run_all", fake_run_all)
    monkeypatch.setattr(conflict_service, "persist_conflict_notifications", fake_persist)

    tracker = _RecordingDedup()
    monkeypatch.setattr(conflict_service, "build_dedup", lambda session: tracker)

    summary = await scan_and_notify_job(now=now)

    assert tracked.ai_saw_open_sessions == [0], "AI 富化期间不得持有数据库会话"
    assert tracked.rules_saw_open_sessions == [0], "规则执行期间不得持有数据库会话"
    assert tracked.open_count == 0, "扫描结束后不得残留会话"
    assert isinstance(summary, ScanSummary)
    assert (summary.hits, summary.created) == (1, 1)


async def test_scan_job_opens_only_the_read_transaction_when_nothing_hits(
    tracked, monkeypatch, now, make_context
):
    """没有命中就不该开写事务，也不该构造去重后端"""
    async def fake_load(session, *, now=None):
        return make_context()

    def fake_run_all(context):
        return []

    monkeypatch.setattr(conflict_service, "load_rule_context", fake_load)
    monkeypatch.setattr(conflict_service, "run_all", fake_run_all)

    def boom(session):
        raise AssertionError("无命中时不应构造去重后端")

    monkeypatch.setattr(conflict_service, "build_dedup", boom)

    summary = await scan_and_notify_job(now=now)

    assert summary.hits == 0
    assert summary.created == 0
    assert tracked.open_count == 0


async def test_scan_job_summary_counts_enrichment(
    tracked, monkeypatch, now, make_context, make_order
):
    ctx = make_context([make_order(1, agent_request="10 人")])

    async def fake_load(session, *, now=None):
        return ctx

    async def fake_enrich(context, *, llm=None, timeout=None):
        return context, 3

    async def fake_persist(session, hits, *, dedup, llm=None, timeout=None):
        return DispatchResult(created=2, skipped=1, failed=1)

    monkeypatch.setattr(conflict_service, "load_rule_context", fake_load)
    monkeypatch.setattr(conflict_service, "enrich_attendees", fake_enrich)
    monkeypatch.setattr(conflict_service, "run_all", lambda context: [_hit()])
    monkeypatch.setattr(
        conflict_service, "persist_conflict_notifications", fake_persist
    )
    monkeypatch.setattr(conflict_service, "build_dedup", lambda session: _RecordingDedup())

    summary = await scan_and_notify_job(now=now)

    assert summary.scanned_orders == 1
    assert summary.enriched == 3
    assert (summary.created, summary.skipped, summary.failed) == (2, 1, 1)


class _RecordingDedup:
    """去重后端的空实现，避免扫描用例引入 Redis 或数据库"""

    name = "recording"

    async def claim(self, key):
        return True

    async def release(self, key):
        return None

    async def aclose(self):
        return None


async def test_scan_job_closes_the_dedup_backend_even_on_failure(
    tracked, monkeypatch, now, make_context
):
    """去重后端持有 Redis 连接，异常路径也必须释放"""
    closed = {"value": False}

    class Dedup(_RecordingDedup):
        async def aclose(self):
            closed["value"] = True

    async def fake_load(session, *, now=None):
        return make_context()

    async def fake_persist(session, hits, *, dedup, llm=None, timeout=None):
        raise RuntimeError("写库炸了")

    monkeypatch.setattr(conflict_service, "load_rule_context", fake_load)
    monkeypatch.setattr(conflict_service, "run_all", lambda context: [_hit()])
    monkeypatch.setattr(
        conflict_service, "persist_conflict_notifications", fake_persist
    )
    monkeypatch.setattr(conflict_service, "build_dedup", lambda session: Dedup())

    with pytest.raises(RuntimeError):
        await scan_and_notify_job(now=now)

    assert closed["value"] is True
    assert tracked.open_count == 0


async def test_scan_job_works_with_ai_fully_disabled(
    tracked, monkeypatch, now, make_context, make_order
):
    """
    ★ AI 全关时仍要能跑完一轮并产出模板通知 —— 应急预案（开发流程.md 13.1）。
    这条路径走的是真实的 persist + 真实的模板降级，只有数据库换成了假会话。
    """
    from app.agent.prompts.notify_templates import ROLE_OWNER
    from app.services.notify_service import Recipient

    monkeypatch.setattr(settings, "AI_ENABLED", False)
    ctx = make_context([make_order(1, agent_request="10 人")])

    async def fake_load(session, *, now=None):
        return ctx

    async def fake_recipients(session, *, audience, owner_id, admin_only=None):
        return [Recipient(user_id=owner_id or 1, username="张三", role_key=ROLE_OWNER)]

    monkeypatch.setattr(conflict_service, "load_rule_context", fake_load)
    monkeypatch.setattr(conflict_service, "resolve_recipients", fake_recipients)
    monkeypatch.setattr(conflict_service, "build_dedup", lambda session: _RecordingDedup())

    summary = await scan_and_notify_job(now=now)

    assert summary.scanned_orders == 1
    assert summary.hits >= 1, "闲置规则应命中"
    assert summary.created >= 1, "应写出模板通知"
    assert summary.failed == 0
    written = [msg for s in tracked.sessions for msg in s.added]
    assert written, "通知必须真的写入假会话"
    assert all(msg.title for msg in written), "模板降级后标题不得为空"
    assert tracked.sessions[-1].committed is True
