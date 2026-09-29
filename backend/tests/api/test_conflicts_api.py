"""
GET /api/v1/conflicts/scan 接口测试

契约（开发流程.md 5.3 模块7）：
    [ { "conflictType": "软冲突", "orderIds": [1,2], "suggestion": "...", "ruleCode": "..." } ]

服务函数被替换成假实现，所以这里不连数据库 ——
本文件盯的是**契约形状**：驼峰字段名、状态码、鉴权、只读性。
SQL 与规则的真实联动由阶段 5 的冒烟验证覆盖。
"""
from __future__ import annotations

from tests.api.conftest import auth_header, make_token


def _stub_service(monkeypatch, conflict_module, hits, scope_patch):
    """把快照读取与 AI 富化都换成假实现，只留规则与契约转换是真的"""

    class StubContext:
        orders = ()

    async def fake_load(session, *, now=None):
        return StubContext()

    async def fake_enrich(ctx, *, llm=None, timeout=None):
        return ctx, 0

    monkeypatch.setattr(conflict_module, "load_rule_context", fake_load)
    monkeypatch.setattr(conflict_module, "enrich_attendees", fake_enrich)
    monkeypatch.setattr(conflict_module, "run_all", lambda ctx: hits)
    return scope_patch(conflict_module)


def test_scan_returns_the_four_contract_fields(
    monkeypatch, client_with_llm, session, patch_scope
):
    """★ 字段名回归防线：多一个少一个都会破坏前端"""
    from app.api.v1 import conflict as conflict_module
    from app.services.rules.base import AUDIENCE_OWNER_AND_ADMIN, RuleHit

    hits = [
        RuleHit(
            rule_code="continuous_activity",
            rule_label="连续活动无休息",
            order_ids=(1, 2),
            reason="两场活动之间仅有 8 分钟间隔。",
            space_id=2,
            audience=AUDIENCE_OWNER_AND_ADMIN,
            facts={"space_name": "A栋3楼展厅"},
        )
    ]
    _stub_service(monkeypatch, conflict_module, hits, patch_scope)

    response = client_with_llm.get(
        "/api/v1/conflicts/scan", headers=auth_header(make_token())
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert isinstance(body["data"], list)
    assert len(body["data"]) == 1

    item = body["data"][0]
    assert set(item) == {"conflictType", "orderIds", "suggestion", "ruleCode"}
    assert item["conflictType"] == "软冲突"
    assert item["orderIds"] == [1, 2]
    assert item["ruleCode"] == "continuous_activity"
    assert item["suggestion"]


def test_scan_never_leaks_snake_case_keys(
    monkeypatch, client_with_llm, session, patch_scope
):
    """防驼峰回归：后端模型字段是蛇形，序列化必须转成驼峰"""
    from app.api.v1 import conflict as conflict_module
    from app.services.rules.base import RuleHit

    _stub_service(
        monkeypatch,
        conflict_module,
        [
            RuleHit(
                rule_code="space_idle",
                rule_label="长期闲置",
                order_ids=(),
                reason="场地闲置。",
            )
        ],
        patch_scope,
    )

    item = client_with_llm.get(
        "/api/v1/conflicts/scan", headers=auth_header(make_token())
    ).json()["data"][0]

    assert "conflict_type" not in item
    assert "order_ids" not in item
    assert "rule_code" not in item


def test_idle_conflict_returns_empty_order_ids(
    monkeypatch, client_with_llm, session, patch_scope
):
    """契约允许空数组，但不得是 null"""
    from app.api.v1 import conflict as conflict_module
    from app.services.rules.base import RuleHit

    _stub_service(
        monkeypatch,
        conflict_module,
        [
            RuleHit(
                rule_code="space_idle",
                rule_label="长期闲置",
                order_ids=(),
                reason="场地 A栋301会议室 在最近 14 天内没有任何有效预约。",
            )
        ],
        patch_scope,
    )

    item = client_with_llm.get(
        "/api/v1/conflicts/scan", headers=auth_header(make_token())
    ).json()["data"][0]

    assert item["orderIds"] == []
    assert item["orderIds"] is not None


def test_scan_returns_all_hits_in_rule_order(
    monkeypatch, client_with_llm, session, patch_scope
):
    from app.api.v1 import conflict as conflict_module
    from app.services.rules.base import RuleHit

    codes = ["continuous_activity", "capacity_overflow", "space_overuse", "space_idle"]
    hits = [
        RuleHit(rule_code=code, rule_label=code, order_ids=(i,), reason="r")
        for i, code in enumerate(codes, start=1)
    ]
    _stub_service(monkeypatch, conflict_module, hits, patch_scope)

    data = client_with_llm.get(
        "/api/v1/conflicts/scan", headers=auth_header(make_token())
    ).json()["data"]

    assert [item["ruleCode"] for item in data] == codes


def test_scan_with_no_conflicts_returns_empty_list(
    monkeypatch, client_with_llm, session, patch_scope
):
    from app.api.v1 import conflict as conflict_module

    _stub_service(monkeypatch, conflict_module, [], patch_scope)

    body = client_with_llm.get(
        "/api/v1/conflicts/scan", headers=auth_header(make_token())
    ).json()

    assert body["code"] == 200
    assert body["data"] == []


def test_scan_is_read_only(monkeypatch, client_with_llm, session, patch_scope):
    """
    只读接口：不落库、不推消息，幂等可重放，看板可以放心轮询。
    假会话的 execute 一旦被调用就会抛 AssertionError，写库则会被记录。
    """
    from app.api.v1 import conflict as conflict_module

    _stub_service(monkeypatch, conflict_module, [], patch_scope)

    response = client_with_llm.get(
        "/api/v1/conflicts/scan", headers=auth_header(make_token())
    )

    assert response.status_code == 200
    assert session.added == []
    assert session.commits == 0


# ---------- 鉴权 ----------


def test_scan_requires_a_token(monkeypatch, client_with_llm, session, patch_scope):
    from app.api.v1 import conflict as conflict_module

    _stub_service(monkeypatch, conflict_module, [], patch_scope)

    body = client_with_llm.get("/api/v1/conflicts/scan").json()

    # ⚠️ 2026-09-28 修正：团队规范里「缺少认证令牌」= **40101**（`TOKEN_MISSING`），
    # `code` 是 5 位业务码，不是 HTTP 数字（《规范》5.2）。
    assert body["code"] == 40101
    assert body["data"] is None


def test_scan_rejects_a_malformed_authorization_header(
    monkeypatch, client_with_llm, session, patch_scope
):
    from app.api.v1 import conflict as conflict_module

    _stub_service(monkeypatch, conflict_module, [], patch_scope)

    for header in ("Token abc", "Bearer", "abc", "Bearer   "):
        body = client_with_llm.get(
            "/api/v1/conflicts/scan", headers={"Authorization": header}
        ).json()
        # 这些头都取不出凭据（scheme 不匹配 / 令牌为空）→ 40101 `TOKEN_MISSING`
        assert body["code"] == 40101, f"错误的头未被拦截：{header!r}"


def test_scan_rejects_a_forged_token(monkeypatch, client_with_llm, session, patch_scope):
    """用别的密钥签的 token 必须被拒 —— 防止身份伪造"""
    import jwt

    from app.api.v1 import conflict as conflict_module

    _stub_service(monkeypatch, conflict_module, [], patch_scope)

    forged = jwt.encode({"sub": "1", "username": "攻击者"}, "not-the-real-key", algorithm="HS256")
    body = client_with_llm.get(
        "/api/v1/conflicts/scan", headers=auth_header(forged)
    ).json()

    # 签名不对 → 40102 `TOKEN_INVALID`（与 40101「缺少令牌」区分开）
    assert body["code"] == 40102


def test_scan_rejects_an_expired_token(
    monkeypatch, client_with_llm, session, patch_scope
):
    from app.api.v1 import conflict as conflict_module

    _stub_service(monkeypatch, conflict_module, [], patch_scope)

    expired = make_token(expires_in_minutes=-1)
    body = client_with_llm.get(
        "/api/v1/conflicts/scan", headers=auth_header(expired)
    ).json()

    # 已过期 → 40103 `TOKEN_EXPIRED`
    assert body["code"] == 40103
    assert "过期" in body["message"] or "失效" in body["message"] or "登录" in body["message"]


def test_scan_accepts_a_token_without_a_role_claim(
    monkeypatch, client_with_llm, session, patch_scope
):
    """角色声明缺失时不应 500 —— 上游认证模块可能不带该字段"""
    from app.api.v1 import conflict as conflict_module

    _stub_service(monkeypatch, conflict_module, [], patch_scope)

    body = client_with_llm.get(
        "/api/v1/conflicts/scan", headers=auth_header(make_token(role_name=None))
    ).json()

    assert body["code"] == 200


def test_health_endpoint_still_works(sync_client):
    body = sync_client.get("/api/v1/health").json()
    assert body["code"] == 200
    assert body["data"]["status"] == "ok"
