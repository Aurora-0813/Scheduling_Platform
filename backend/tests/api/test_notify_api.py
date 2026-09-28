"""
POST /api/v1/notify/generate 接口测试

契约（开发流程.md 5.3 模块7）：
    入：{ "type": "延期致歉", "orderInfo": {} }
    出：{ "title": "...", "content": "..." }（严格两个字段）

只替换「查订单」与「解析收件人」两处数据库读取，派发、去重与写入走真实实现，
因此本文件同时覆盖了「生成 → 去重 → 落库」整条链路。
"""
from __future__ import annotations

from datetime import datetime

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from app.agent.prompts.notify_templates import ROLE_OWNER, ROLE_RESOURCE_ADMIN
from app.services.dedup import MemoryDedup
from app.services.notify_service import OrderSnapshot, Recipient
from tests.api.conftest import auth_header, make_token

END_POINT = "/api/v1/notify/generate"

AI_RESPONSE = '{"title": "AI 标题", "content": "AI 生成的正文内容。"}'


class CountingLLM(FakeMessagesListChatModel):
    """统计底层生成被调用了几次，用来断言「同角色只调一次模型」"""

    # pydantic 模型不允许随意挂属性，计数器必须声明成字段
    calls: int = 0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        return super()._generate(messages, stop, run_manager, **kwargs)


class SharedMemoryDedup(MemoryDedup):
    """
    跨请求共享的进程内去重。

    MemoryDedup.aclose() 会清空状态（进程退出即失效，本该如此），
    但真实后端是 Redis —— 状态在进程之外，天然跨请求。接口层要验证的
    正是这个「重复调用不重复落库」的语义，故此处让 close 变成空操作。
    """

    async def aclose(self) -> None:
        return None


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


@pytest.fixture
def patch_notify(monkeypatch, session, patch_scope):
    """替换订单查询与收件人解析，并让去重退化为跨请求共享的进程内实现"""
    from app.api.v1 import notify as notify_module

    patch_scope(notify_module)
    dedup = SharedMemoryDedup()
    monkeypatch.setattr(notify_module, "build_dedup", lambda s: dedup)

    def _apply(snapshot=None, recipients=None):
        async def fake_load(session, order_id):
            return snapshot

        async def fake_recipients(session, *, audience, owner_id, admin_only=None):
            return list(recipients or [])

        monkeypatch.setattr(notify_module, "load_order_snapshot", fake_load)
        monkeypatch.setattr(notify_module, "resolve_recipients", fake_recipients)
        return snapshot

    return _apply


@pytest.fixture
def counting_client(client):
    """注入可计数的假模型，用来验证一个角色只调一次模型"""
    from app.api.deps import get_llm
    from app.main import app

    model = CountingLLM(responses=[AIMessage(content=AI_RESPONSE)] * 6)
    app.dependency_overrides[get_llm] = lambda: model
    yield client, model
    app.dependency_overrides.clear()


OWNER = Recipient(user_id=1, username="张三", role_name="普通使用者", role_key=ROLE_OWNER)
ADMIN = Recipient(
    user_id=2, username="李管理", role_name="资源管理员", role_key=ROLE_RESOURCE_ADMIN
)


# ---------- 契约形状 ----------


def test_generate_returns_exactly_title_and_content(
    client_with_llm, session, patch_notify
):
    """★ 契约只允许 title / content 两个字段，source 等内部字段不得泄漏"""
    patch_notify(snapshot=_snapshot(), recipients=[OWNER])

    response = client_with_llm.post(
        END_POINT,
        json={"type": "延期致歉", "orderInfo": {"orderId": 101}},
        headers=auth_header(make_token()),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert set(body["data"]) == {"title", "content"}
    assert isinstance(body["data"]["title"], str)
    assert isinstance(body["data"]["content"], str)
    assert body["data"]["title"]
    assert body["data"]["content"]


def test_generate_persists_the_notification(client_with_llm, session, patch_notify):
    """落库口径：延期致歉 → notify_type=2，收件人取数据库中的人"""
    patch_notify(snapshot=_snapshot(), recipients=[OWNER])

    client_with_llm.post(
        END_POINT,
        json={"type": "延期致歉", "orderInfo": {"orderId": 101}},
        headers=auth_header(make_token()),
    )

    assert len(session.added) == 1
    message = session.added[0]
    assert message.receiver_id == 1
    assert message.notify_type == 2
    assert message.order_id == 101
    assert message.is_read == 0
    assert message.title
    assert session.commits == 1


def test_generate_accepts_an_integer_type(client_with_llm, session, patch_notify):
    patch_notify(snapshot=_snapshot(), recipients=[OWNER])

    body = client_with_llm.post(
        END_POINT,
        json={"type": 1, "orderInfo": {"orderId": 101}},
        headers=auth_header(make_token()),
    ).json()

    assert body["code"] == 200
    assert session.notify_types == [1]


def test_generate_works_without_order_info(client_with_llm, session, patch_notify):
    """契约示例给的就是空 orderInfo：只生成文案，不落库"""
    patch_notify(snapshot=None, recipients=[])

    body = client_with_llm.post(
        END_POINT,
        json={"type": "延期致歉", "orderInfo": {}},
        headers=auth_header(make_token()),
    ).json()

    assert body["code"] == 200
    assert body["data"]["title"]
    assert session.added == []


# ---------- 校验 ----------


def test_missing_type_returns_business_code_400(client_with_llm, patch_notify):
    """缺 type 属请求参数校验失败。主干把它统一收敛成 code=400 + 固定文案
    「请求参数有误，请检查后重试」（见 core/exceptions.py 的 handler，以及
    docs/摄像头空间感知模块设计.md 的接口约定）—— 不要改回 422。
    """
    patch_notify(snapshot=None)

    body = client_with_llm.post(
        END_POINT,
        json={"orderInfo": {}},
        headers=auth_header(make_token()),
    ).json()

    assert body["code"] == 400
    assert "请求参数有误" in body["message"]


def test_unknown_type_returns_business_code_400(client_with_llm, patch_notify):
    patch_notify(snapshot=None)

    body = client_with_llm.post(
        END_POINT,
        json={"type": "不存在的语气", "orderInfo": {}},
        headers=auth_header(make_token()),
    ).json()

    assert body["code"] == 400
    assert "不支持的通知类型" in body["message"]


def test_missing_order_info_defaults_to_empty(client_with_llm, patch_notify):
    """orderInfo 可省略，不应报参数错误"""
    patch_notify(snapshot=None)

    body = client_with_llm.post(
        END_POINT, json={"type": "提醒"}, headers=auth_header(make_token())
    ).json()

    assert body["code"] == 200


def test_generate_requires_a_token(client_with_llm, patch_notify):
    patch_notify(snapshot=None)

    body = client_with_llm.post(
        END_POINT, json={"type": "提醒", "orderInfo": {}}
    ).json()

    assert body["code"] == 401
    assert body["data"] is None


# ---------- 身份与事实的来源安全 ----------


def test_payload_user_id_cannot_redirect_the_notification(
    client_with_llm, session, patch_notify
):
    """
    ★ 开发流程.md 5.1：身份标识禁止从请求体传入，防止身份伪造。
    载荷里塞 userId=999 不得让通知发给 999。
    """
    patch_notify(snapshot=_snapshot(), recipients=[OWNER])

    client_with_llm.post(
        END_POINT,
        json={
            "type": "提醒",
            "orderInfo": {"orderId": 101, "userId": 999, "receiverId": 999},
        },
        headers=auth_header(make_token(user_id=1)),
    )

    assert 999 not in session.receiver_ids
    assert session.receiver_ids == [1]


def test_payload_cannot_override_the_tone(client_with_llm, session, patch_notify):
    """orderInfo 里的 notifyType 是载荷字段，语气只认顶层 type"""
    patch_notify(snapshot=_snapshot(), recipients=[OWNER])

    client_with_llm.post(
        END_POINT,
        json={"type": 1, "orderInfo": {"orderId": 101, "notifyType": 2}},
        headers=auth_header(make_token()),
    )

    assert session.notify_types == [1]


def test_payload_cannot_overwrite_database_facts(
    client_with_llm, session, patch_notify, monkeypatch
):
    """
    ★ 关掉 AI 后文案由模板渲染，于是能直接看到事实来源：
    载荷里的场地名不得覆盖库中事实，否则请求方能借 AI 把错误的场地名
    写进给用户看的正式通知。
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "AI_ENABLED", False)
    patch_notify(snapshot=_snapshot(), recipients=[OWNER])

    client_with_llm.post(
        END_POINT,
        json={
            "type": "提醒",
            "orderInfo": {"orderId": 101, "spaceName": "伪造的场地"},
        },
        headers=auth_header(make_token()),
    )

    message = session.added[0]
    text = f"{message.title}{message.content}"
    assert "A栋3楼展厅" in text
    assert "伪造的场地" not in text


def test_payload_facts_reach_the_notification(
    client_with_llm, session, patch_notify, monkeypatch
):
    """载荷里库中没有的事实（如冲突原因）应当补进文案，而不是被一律丢弃"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "AI_ENABLED", False)
    patch_notify(snapshot=_snapshot(), recipients=[OWNER])

    client_with_llm.post(
        END_POINT,
        json={
            "type": "延期致歉",
            "orderInfo": {"orderId": 101, "reason": "设备临时检修"},
        },
        headers=auth_header(make_token()),
    )

    assert "设备临时检修" in session.added[0].content


def test_missing_order_is_not_persisted(client_with_llm, session, patch_notify):
    """
    订单在库中不存在时只生成文案、不落库：
    避免 AI 依据来路不明的载荷编造资源名后写进正式通知。
    """
    patch_notify(snapshot=None, recipients=[OWNER])

    body = client_with_llm.post(
        END_POINT,
        json={"type": "提醒", "orderInfo": {"orderId": 999999}},
        headers=auth_header(make_token()),
    ).json()

    assert body["code"] == 200
    assert body["data"]["title"]
    assert session.added == []
    assert session.commits == 0


def test_non_numeric_order_id_is_treated_as_absent(
    client_with_llm, session, patch_notify
):
    patch_notify(snapshot=None)

    body = client_with_llm.post(
        END_POINT,
        json={"type": "提醒", "orderInfo": {"orderId": "abc"}},
        headers=auth_header(make_token()),
    ).json()

    assert body["code"] == 200
    assert session.added == []


# ---------- 多角色、幂等与降级 ----------


def test_every_recipient_gets_a_row(counting_client, session, patch_notify):
    """预约人与管理员各收一条，且各自只按自己的语气调用一次模型"""
    patch_notify(snapshot=_snapshot(), recipients=[OWNER, ADMIN])

    fake_client, model = counting_client
    fake_client.post(
        END_POINT,
        json={"type": "提醒", "orderInfo": {"orderId": 101}},
        headers=auth_header(make_token()),
    )

    assert sorted(session.receiver_ids) == [1, 2]
    # 调用方角色（预约人）的文案已预生成，只有管理员那一组需要再调一次
    assert model.calls == 2


def test_repeat_request_is_deduplicated(client_with_llm, session, patch_notify):
    """同一订单同一语气在 TTL 内重复请求不重复落库（幂等）"""
    patch_notify(snapshot=_snapshot(), recipients=[OWNER])
    payload = {"type": "提醒", "orderInfo": {"orderId": 101}}
    headers = auth_header(make_token())

    first = client_with_llm.post(END_POINT, json=payload, headers=headers).json()
    second = client_with_llm.post(END_POINT, json=payload, headers=headers).json()

    # 两次都要给出可用文案，只是第二次不再写库
    assert first["data"]["title"] and second["data"]["title"]
    assert len(session.added) == 1


def test_different_tone_is_not_deduplicated(client_with_llm, session, patch_notify):
    """提醒与致歉是两条不同语义的通知，不应被同一个指纹压掉"""
    patch_notify(snapshot=_snapshot(), recipients=[OWNER])
    headers = auth_header(make_token())

    client_with_llm.post(
        END_POINT, json={"type": "提醒", "orderInfo": {"orderId": 101}}, headers=headers
    )
    client_with_llm.post(
        END_POINT,
        json={"type": "延期致歉", "orderInfo": {"orderId": 101}},
        headers=headers,
    )

    assert session.notify_types == [1, 2]


def test_generate_still_works_with_ai_disabled(
    client_with_llm, session, patch_notify, monkeypatch
):
    """
    ★ 应急预案（开发流程.md 13.1）：AI 全关时接口仍返回模板文案并正常落库，
    模板里的场地名等事实也要正确填充。
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "AI_ENABLED", False)
    patch_notify(snapshot=_snapshot(), recipients=[OWNER])

    body = client_with_llm.post(
        END_POINT,
        json={"type": "延期致歉", "orderInfo": {"orderId": 101}},
        headers=auth_header(make_token()),
    ).json()

    assert body["code"] == 200
    assert body["data"]["title"]
    assert body["data"]["content"]
    assert "A栋3楼展厅" in body["data"]["title"]
    assert len(session.added) == 1


def test_write_failure_does_not_break_the_response(
    client_with_llm, session, patch_notify
):
    """
    收件人写库失败时接口仍须返回文案 ——
    文案已经生成出来了，不该因为落库失败让调用方拿到 500。
    """
    patch_notify(snapshot=_snapshot(), recipients=[OWNER])
    session._fail_after = 1  # 让假会话的第一次 flush 抛错，模拟写库失败

    body = client_with_llm.post(
        END_POINT,
        json={"type": "提醒", "orderInfo": {"orderId": 101}},
        headers=auth_header(make_token()),
    ).json()

    assert body["code"] == 200
    assert body["data"]["title"]
