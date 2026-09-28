"""
数据库读取层的结果映射

为什么值得单独测：`load_order_snapshot` 从一条 JOIN 里按**下标**取 11 个字段，
`load_rule_context` 用固定 5 条查询组装快照 —— 下标写错、JOIN 少一张表这类问题
不会在纯函数测试里暴露，只会在连上真库的那一刻炸掉。

这里用一个「按调用顺序返回预设结果集」的假会话，把 SQL 返回的元组
喂给真实实现，从而离线验证映射逻辑。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.services import notify_service
from app.services.rules.base import AUDIENCE_ADMIN_ONLY, AUDIENCE_OWNER_AND_ADMIN

NOW = datetime(2026, 9, 25, 10, 0)


class FakeResult:
    """够用的结果集：实现 .all() 与 .first()"""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self) -> list[tuple]:
        return list(self._rows)

    def first(self) -> tuple | None:
        return self._rows[0] if self._rows else None


class ScriptedSession:
    """
    按调用顺序返回预设结果集的假会话。

    额外记录执行过的语句，用来断言「固定 N 条查询、不做 N+1」——
    这类性能约束写成用例才不会在后续重构里被悄悄破坏。
    """

    def __init__(self, *results: list[tuple]) -> None:
        self._script = list(results)
        self.executed: list = []

    async def execute(self, stmt):
        self.executed.append(stmt)
        if not self._script:
            raise AssertionError("查询次数超出预期 —— 说明出现了 N+1")
        return FakeResult(self._script.pop(0))

    @property
    def query_count(self) -> int:
        return len(self.executed)


# ---------- load_order_snapshot ----------


def _order_row(overrides: dict[int, object] | None = None) -> tuple:
    """按 select 的列顺序拼一行：(id, user_id, space_id, start, end, status,
    device_ids, username, role_name, space_name, capacity)

    overrides 用**下标**指定要替换的列，与实现里的下标取法一一对应。
    """
    overrides = overrides or {}
    row = (
        101,                                        # 0 id
        1,                                          # 1 user_id
        2,                                          # 2 space_id
        datetime(2026, 9, 25, 14, 0),               # 3 start_time
        datetime(2026, 9, 25, 16, 0),               # 4 end_time
        2,                                          # 5 order_status
        [3, 5],                                     # 6 device_ids
        "张三",                                      # 7 username
        "普通使用者",                                  # 8 role_name
        "A栋3楼展厅",                                 # 9 space_name
        40,                                         # 10 capacity
    )
    return tuple(overrides.get(i, value) for i, value in enumerate(row))


async def test_the_row_helper_covers_every_selected_column():
    """夹具本身也要盯住：列数变了而夹具没变，下面的用例就成了假绿"""
    assert len(_order_row()) == 11


async def test_order_snapshot_maps_every_column():
    session = ScriptedSession([_order_row()])

    snapshot = await notify_service.load_order_snapshot(session, 101)

    assert snapshot is not None
    assert snapshot.id == 101
    assert snapshot.user_id == 1
    assert snapshot.space_id == 2
    assert snapshot.start_time == datetime(2026, 9, 25, 14, 0)
    assert snapshot.end_time == datetime(2026, 9, 25, 16, 0)
    assert snapshot.order_status == 2
    assert snapshot.device_ids == (3, 5)
    assert snapshot.user_name == "张三"
    assert snapshot.user_role_name == "普通使用者"
    assert snapshot.space_name == "A栋3楼展厅"
    assert snapshot.capacity == 40
    assert session.query_count == 1, "一条 JOIN 查询就该取回全部事实"


async def test_order_snapshot_returns_none_when_the_order_is_missing():
    session = ScriptedSession([])
    assert await notify_service.load_order_snapshot(session, 999999) is None


async def test_order_snapshot_without_a_provider_returns_bare_facts():
    """弱关联字段全为 NULL 时也要构造出快照，不能抛异常"""
    session = ScriptedSession(
        [_order_row({6: None, 7: None, 8: None, 9: None, 10: None})]
    )

    snapshot = await notify_service.load_order_snapshot(session, 101)

    assert snapshot is not None
    assert snapshot.device_ids == ()
    assert snapshot.user_name is None
    assert snapshot.space_name is None
    assert snapshot.capacity is None


@pytest.mark.parametrize("raw", [None, "3,5", 0, {"a": 1}])
async def test_order_snapshot_tolerates_a_non_list_device_ids_column(raw):
    """列类型异常时退化为空元组，不能让整条通知链路崩掉"""
    session = ScriptedSession([_order_row({6: raw})])

    snapshot = await notify_service.load_order_snapshot(session, 101)

    assert snapshot is not None
    assert snapshot.device_ids == ()


async def test_order_snapshot_skips_null_entries_in_device_ids():
    session = ScriptedSession([_order_row({6: [3, None, 5]})])

    snapshot = await notify_service.load_order_snapshot(session, 101)

    assert snapshot is not None
    assert snapshot.device_ids == (3, 5)


# ---------- load_recipient ----------


async def test_load_recipient_maps_the_role_to_a_tone():
    session = ScriptedSession([(2, "李管理", "资源管理员")])

    recipient = await notify_service.load_recipient(session, 2)

    assert recipient is not None
    assert recipient.user_id == 2
    assert recipient.username == "李管理"
    assert recipient.role_name == "资源管理员"
    assert recipient.role_key == "资源管理员"


async def test_load_recipient_falls_back_to_a_readable_name():
    session = ScriptedSession([(7, None, None)])

    recipient = await notify_service.load_recipient(session, 7)

    assert recipient is not None
    assert recipient.username == "用户#7"
    assert recipient.role_key == "预约人", "角色未知时按最保守的预约人视角说话"


async def test_load_recipient_returns_none_for_an_unknown_user():
    session = ScriptedSession([])
    assert await notify_service.load_recipient(session, 404) is None


# ---------- load_admin_recipients ----------


async def test_admin_recipients_exclude_normal_users():
    session = ScriptedSession(
        [
            (1, "张三", "普通使用者"),
            (2, "李管理", "资源管理员"),
            (3, "王系统", "系统管理员"),
        ]
    )

    recipients = await notify_service.load_admin_recipients(session)

    assert [r.user_id for r in recipients] == [2, 3]
    assert session.query_count == 1, "全体管理员应一条 JOIN 查完，不做 N+1"


async def test_admin_recipients_skip_accounts_without_a_role():
    """角色为空的账号无法确认是管理员，不该收到管理侧通知"""
    session = ScriptedSession([(2, "李管理", None)])

    assert await notify_service.load_admin_recipients(session) == []


async def test_admin_recipients_map_each_tone_role():
    session = ScriptedSession(
        [(2, "李管理", "资源管理员"), (3, "王系统", "系统管理员")]
    )

    recipients = await notify_service.load_admin_recipients(session)

    assert {r.role_key for r in recipients} == {"资源管理员", "系统管理员"}


# ---------- resolve_recipients ----------


async def test_resolve_recipients_deduplicates_an_admin_owner():
    """管理员给自己预约时不该收到两遍"""
    session = ScriptedSession(
        [(2, "李管理", "资源管理员")],           # 预约人
        [(2, "李管理", "资源管理员"), (3, "王系统", "系统管理员")],  # 全体管理员
    )

    recipients = await notify_service.resolve_recipients(
        session, audience=AUDIENCE_OWNER_AND_ADMIN, owner_id=2
    )

    assert [r.user_id for r in recipients] == [2, 3]


async def test_admin_only_audience_never_queries_the_owner():
    session = ScriptedSession([(3, "王系统", "系统管理员")])

    recipients = await notify_service.resolve_recipients(
        session, audience=AUDIENCE_ADMIN_ONLY, owner_id=1
    )

    assert [r.user_id for r in recipients] == [3]
    assert session.query_count == 1


async def test_owner_only_audience_never_queries_admins():
    session = ScriptedSession([(1, "张三", "普通使用者")])

    from app.services.rules.base import AUDIENCE_OWNER

    recipients = await notify_service.resolve_recipients(
        session, audience=AUDIENCE_OWNER, owner_id=1
    )

    assert [r.user_id for r in recipients] == [1]
    assert session.query_count == 1


# ---------- dispatch_order_notification ----------


class RecordingDedup:
    name = "recording"

    def __init__(self) -> None:
        self.closed = False

    async def claim(self, key) -> bool:
        return True

    async def release(self, key) -> None:
        return None

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def patched_dispatch(monkeypatch):
    """
    把 dispatch_order_notification 依赖的三件事都换掉：
    会话、收件人解析、文案派发。只保留编排逻辑本身。
    """
    from contextlib import asynccontextmanager

    from app.services.notify_service import DispatchResult

    state = {"snapshot": None, "recipients": [], "commits": 0, "dispatch": None}
    dedup = RecordingDedup()

    class FakeSession:
        async def commit(self) -> None:
            state["commits"] += 1

    @asynccontextmanager
    async def scope():
        yield FakeSession()

    async def fake_load(session, order_id):
        return state["snapshot"]

    async def fake_resolve(session, *, audience, owner_id, admin_only=None):
        state["audience"] = audience
        state["owner_id"] = owner_id
        return list(state["recipients"])

    async def fake_dispatch(**kwargs):
        state["dispatch"] = kwargs
        return DispatchResult(created=1)

    monkeypatch.setattr(notify_service, "session_scope", scope)
    monkeypatch.setattr(notify_service, "load_order_snapshot", fake_load)
    monkeypatch.setattr(notify_service, "resolve_recipients", fake_resolve)
    monkeypatch.setattr(notify_service, "generate_and_dispatch", fake_dispatch)
    monkeypatch.setattr(notify_service, "build_dedup", lambda session: dedup)

    state["dedup"] = dedup
    return state


async def test_event_dispatch_maps_the_snapshot_into_facts(patched_dispatch):
    from app.services.notify_service import OrderSnapshot, Recipient

    patched_dispatch["snapshot"] = OrderSnapshot(
        id=101,
        user_id=1,
        space_id=2,
        start_time=datetime(2026, 9, 25, 14, 0),
        end_time=datetime(2026, 9, 25, 16, 0),
        order_status=2,
        space_name="A栋3楼展厅",
    )
    patched_dispatch["recipients"] = [
        Recipient(user_id=1, username="张三", role_key="预约人")
    ]

    result = await notify_service.dispatch_order_notification(
        order_id=101,
        notify_type="提醒",
        rule_code="order_created",
        reason="场地已就绪",
    )

    assert result.created == 1
    call = patched_dispatch["dispatch"]
    assert call["order_ids"] == (101,)
    assert call["space_id"] == 2
    assert call["order_id"] == 101
    assert call["rule_code"] == "order_created"
    assert call["source"] == "event"
    assert call["facts"]["space_name"] == "A栋3楼展厅"
    assert call["facts"]["reason"] == "场地已就绪"
    assert patched_dispatch["commits"] == 1
    assert patched_dispatch["dedup"].closed is True, "去重后端必须释放"


async def test_event_dispatch_without_an_order_degrades_to_admins(patched_dispatch):
    from app.services.notify_service import Recipient

    patched_dispatch["snapshot"] = None
    patched_dispatch["recipients"] = [
        Recipient(user_id=2, username="李管理", role_key="资源管理员")
    ]

    await notify_service.dispatch_order_notification(
        order_id=None,
        notify_type="故障告警",
        rule_code="device_fault",
        extra_facts={"deviceName": "无人机-1"},
    )

    call = patched_dispatch["dispatch"]
    assert call["order_id"] is None
    assert call["order_ids"] == ()
    assert call["space_id"] is None
    assert call["facts"]["device_name"] == "无人机-1"
    assert patched_dispatch["owner_id"] is None


async def test_event_dispatch_skips_when_the_order_does_not_exist(patched_dispatch):
    """订单不存在时不该硬发一条没有事实依据的通知"""
    patched_dispatch["snapshot"] = None
    patched_dispatch["recipients"] = []

    result = await notify_service.dispatch_order_notification(
        order_id=999999, notify_type="提醒", rule_code="order_created"
    )

    assert result.created == 0
    assert patched_dispatch["dispatch"] is None
    assert patched_dispatch["commits"] == 0


async def test_event_dispatch_does_not_commit_when_nobody_can_be_reached(
    patched_dispatch,
):
    from app.services.notify_service import OrderSnapshot

    patched_dispatch["snapshot"] = OrderSnapshot(
        id=1,
        user_id=1,
        space_id=1,
        start_time=NOW,
        end_time=NOW + timedelta(hours=1),
        order_status=2,
    )
    patched_dispatch["recipients"] = []

    result = await notify_service.dispatch_order_notification(
        order_id=1, notify_type="提醒", rule_code="order_created"
    )

    assert result.created == 0
    assert patched_dispatch["commits"] == 0


# ---------- _fmt ----------


def test_fmt_handles_none_and_both_formats():
    from app.services.notify_service import _fmt

    assert _fmt(None) == ""
    assert _fmt(None, with_date=False) == ""
    assert _fmt(NOW) == "2026-09-25 10:00"
    assert _fmt(NOW, with_date=False) == "10:00"


# ---------- conflict_service.load_rule_context ----------


def _order_row_ctx(overrides: dict[int, object] | None = None) -> tuple:
    """(id, user_id, space_id, start, end, status, device_ids, agent_request)"""
    overrides = overrides or {}
    row = (
        1001,
        1,
        2,
        datetime(2026, 9, 25, 14, 0),
        datetime(2026, 9, 25, 16, 0),
        2,
        [3, 5],
        "需要 6 人参加的产品评审会",
    )
    return tuple(overrides.get(i, value) for i, value in enumerate(row))


def _context_session(
    orders=None, spaces=None, devices=None, users=None, last=None
) -> ScriptedSession:
    """按 load_rule_context 的固定查询顺序装填 5 个结果集"""
    return ScriptedSession(
        orders if orders is not None else [],
        spaces if spaces is not None else [],
        devices if devices is not None else [],
        users if users is not None else [],
        last if last is not None else [],
    )


async def test_rule_context_uses_exactly_five_queries():
    """★ 快照组装必须固定 5 条查询 —— 加一条 JOIN 换一次 N+1 都会在这里被拦下"""
    from app.services.conflict_service import load_rule_context

    session = _context_session()

    await load_rule_context(session, now=NOW)

    assert session.query_count == 5


async def test_rule_context_protects_itself_with_a_limit():
    """订单查询必须带 LIMIT：扫描窗口内订单可能上万，2 核 2G 上会直接 OOM"""
    from app.services.conflict_service import load_rule_context

    session = _context_session()
    await load_rule_context(session, now=NOW)

    order_sql = str(session.executed[0]).upper()
    assert "LIMIT" in order_sql
    assert "ORDER BY" in order_sql, "顺序稳定，看板与日志才可比对"


async def test_rule_context_maps_an_order_row():
    from app.services.conflict_service import load_rule_context

    session = _context_session(orders=[_order_row_ctx()])

    ctx = await load_rule_context(session, now=NOW)

    assert len(ctx.orders) == 1
    order = ctx.orders[0]
    assert order.id == 1001
    assert order.user_id == 1
    assert order.space_id == 2
    assert order.start_time == datetime(2026, 9, 25, 14, 0)
    assert order.end_time == datetime(2026, 9, 25, 16, 0)
    assert order.order_status == 2
    assert order.device_ids == (3, 5)
    assert order.agent_request == "需要 6 人参加的产品评审会"
    assert order.attendee_count is None, "人数只由 AI 富化回填，读取阶段不得臆测"


async def test_rule_context_normalizes_a_broken_device_ids_column():
    from app.services.conflict_service import load_rule_context

    session = _context_session(orders=[_order_row_ctx({6: None})])

    ctx = await load_rule_context(session, now=NOW)

    assert ctx.orders[0].device_ids == ()


async def test_rule_context_maps_space_rows_with_readable_fallbacks():
    """容量与状态允许为 NULL，但规则要拿它们做数值比较，必须落到默认值"""
    from app.services.conflict_service import load_rule_context

    session = _context_session(
        spaces=[
            (1, "A栋3楼展厅", 2, 40, 1),
            (2, None, None, None, None),
        ]
    )

    ctx = await load_rule_context(session, now=NOW)

    assert ctx.spaces[1].space_name == "A栋3楼展厅"
    assert ctx.spaces[1].capacity == 40
    assert ctx.spaces[1].space_type == 2
    assert ctx.spaces[2].space_name == "场地#2"
    assert ctx.spaces[2].capacity == 0
    assert ctx.spaces[2].space_type == 1
    assert ctx.spaces[2].status == 1


async def test_rule_context_maps_device_rows_with_readable_fallbacks():
    from app.services.conflict_service import load_rule_context

    session = _context_session(
        devices=[
            (7, "无人机-1", "无人机", 1),
            (8, None, None, None),
        ]
    )

    ctx = await load_rule_context(session, now=NOW)

    assert ctx.devices[7].device_name == "无人机-1"
    assert ctx.devices[7].device_type == "无人机"
    assert ctx.devices[8].device_name == "设备#8"
    assert ctx.devices[8].device_status == 1


async def test_rule_context_keeps_a_null_role_as_unknown():
    """角色为空的用户仍要进快照 —— 高价值设备规则把「角色未知」视为普通使用者"""
    from app.services.conflict_service import load_rule_context

    session = _context_session(
        users=[
            (1, "张三", 3, "普通使用者"),
            (2, None, None, None),
        ]
    )

    ctx = await load_rule_context(session, now=NOW)

    assert ctx.users[1].username == "张三"
    assert ctx.users[1].role_id == 3
    assert ctx.users[1].role_name == "普通使用者"
    assert ctx.users[2].username == "用户#2"
    assert ctx.users[2].role_id is None
    assert ctx.users[2].role_name is None


async def test_rule_context_collects_the_last_order_time_per_space():
    from app.services.conflict_service import load_rule_context

    last_end = datetime(2026, 8, 1, 18, 0)
    session = _context_session(last=[(1, last_end), (2, None), (None, last_end)])

    ctx = await load_rule_context(session, now=NOW)

    assert ctx.space_last_order_at == {1: last_end}, (
        "空 end_time 与空 space_id 的聚合行必须丢弃，否则闲置判定会误判"
    )


async def test_the_two_order_status_口径_are_kept_apart():
    """
    ★ 扫描窗口与闲置聚合必须用**两套**状态口径。

    第 5 条查询问的是「这个场地最近被用过吗」，读各场地最后一次预约的结束时间。
    若它跟扫描窗口共用前瞻口径 (1,2)，任何最后一笔预约已完成的场地都会丢掉
    这条记录，被误判成「长期闲置、无预约记录」——既是假警报，描述还与事实相反。
    这类错不会在规则层的纯函数用例里暴露（规则只看到快照），所以在这里钉住。
    """
    from app.services.conflict_service import load_rule_context
    from app.services.rules.base import ACTIVE_ORDER_STATUSES, HISTORY_ORDER_STATUSES

    session = _context_session(last=[(1, datetime(2026, 8, 1, 18, 0))])
    await load_rule_context(session, now=NOW)

    def status_lists(stmt) -> list[list[int]]:
        return [
            list(value)
            for value in stmt.compile().params.values()
            if isinstance(value, (list, tuple))
        ]

    assert [1, 2] in status_lists(session.executed[0]), (
        "扫描窗口应按已确认口径排除 4 已完成"
    )
    assert [1, 2, 4] in status_lists(session.executed[4]), (
        "闲置聚合的口径丢了 4 已完成，场地会被误判为长期闲置"
    )
    assert 4 not in ACTIVE_ORDER_STATUSES
    assert 4 in HISTORY_ORDER_STATUSES
    assert ACTIVE_ORDER_STATUSES != HISTORY_ORDER_STATUSES, "两套口径不能合并"


async def test_rule_context_is_empty_but_usable_on_an_empty_database():
    """★ 种子数据还没灌进去时扫描不能崩：规则引擎要能对着空快照跑完"""
    from app.services.conflict_service import load_rule_context
    from app.services.rules.registry import run_all

    session = _context_session()

    ctx = await load_rule_context(session, now=NOW)

    assert ctx.orders == ()
    assert ctx.spaces == {}
    assert ctx.devices == {}
    assert ctx.users == {}
    assert ctx.space_last_order_at == {}
    assert run_all(ctx) == []


async def test_rule_context_carries_the_thresholds_from_settings():
    from app.core.config import settings
    from app.services.conflict_service import load_rule_context

    session = _context_session()

    ctx = await load_rule_context(session, now=NOW)

    assert ctx.config.idle_days == settings.CONFLICT_IDLE_DAYS
    assert ctx.config.continuous_gap_minutes == settings.CONFLICT_CONTINUOUS_GAP_MINUTES
    assert ctx.now == NOW, "传入的 now 必须被采纳，否则定时任务与测试对不上时间"


async def test_rule_context_ignores_the_wall_clock_when_now_is_given():
    """不传 now 时取当前时间，传了就必须用传进来的那个"""
    from app.services.conflict_service import load_rule_context

    session = _context_session()

    ctx = await load_rule_context(session)

    assert ctx.now != NOW
    assert abs((ctx.now - datetime.now()).total_seconds()) < 5
