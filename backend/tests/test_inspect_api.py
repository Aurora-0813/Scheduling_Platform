"""
模块 6：AI 智能巡检与维修工单 —— 接口层测试

覆盖三条契约（形状冻结在 `app/api/v1/mock_data.py`）：
    POST /api/v1/inspect/submit
    GET  /api/v1/tickets/list
    PUT  /api/v1/tickets/{ticketId}/status

与模块 2 的 `test_image_api.py` 做法**不同**：那里的库是替身（`get_db` 返回 None），
本文件用的是 `tests/conftest.py` 的 `client` 夹具 —— 它把 `get_db` 覆盖成一个**真实的
临时 SQLite 会话**（与生产一样「每请求一个新会话、不替调用方提交」）。
因此「服务层忘了 commit」「外键写反」「JOIN 取错字段」这类缺陷会被真实暴露。

模型仍用假模型替换：真视觉模型只在连云库时走（见 `docs/spec/后端改动1.md` 的实测记录）。
"""

from __future__ import annotations

import json
from datetime import time
from decimal import Decimal
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.api

SPACE_ID = 4  # 用真库种子里「A栋3楼展厅」的 id，语义上对得上
INSPECTOR_ID = 1

FAULT_REPLY = json.dumps(
    {
        "deviceStatus": "损坏",
        "report": "投影仪指示灯红色常亮，画面无输出，判定为灯泡损坏。",
        "repairSuggestion": "更换投影仪灯泡（型号 ET-LAL510）。",
        "deviceName": "投影仪01",
        "deviceType": "投影仪",
    },
    ensure_ascii=False,
)

NORMAL_REPLY = json.dumps(
    {
        "deviceStatus": "完好",
        "report": "设备外观完好，指示灯正常，未发现异常。",
        "repairSuggestion": "",
        "deviceName": "音响01",
        "deviceType": "音响",
    },
    ensure_ascii=False,
)

#: 完全不是 JSON —— 用来逼出 `_recognize` 的解析失败分支
UNPARSABLE_REPLY = "抱歉，这张照片我实在看不清，请重新拍摄。"

#: 最小的合法 PNG（1x1），够过魔数校验；真实图片校验由模块 2 的用例覆盖
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd4"
    "0000000049454e44ae426082"
)


@pytest.fixture
def fake_vision():
    """按剧本回复的假视觉模型工厂。

    用工厂而不是固定夹具：不同用例要不同的 `deviceStatus`（损坏 / 完好 / 解析不了），
    一个写死的夹具会让所有用例拿到同一个判定，测出来的行为也就没意义了。
    """
    from app.agent.chains.llm import build_fake_llm

    def _make(reply: str):
        return build_fake_llm([reply])

    return _make


@pytest.fixture
async def api(application, client, db_session, monkeypatch, fake_vision):
    """把「一个场地 + 一个假视觉模型 + 一枚合法令牌」装配好，供各用例直接用。"""
    import datetime as dt

    from app.core.llm import get_vision_llm
    from app.core.security import TokenType, create_token
    from app.models.resource import SpaceResource
    from app.services import auth_service, inspect_service

    # ---- 造一个场地（云库上 inspect_record.space_id 是真外键，必须先有行）----
    db_session.add(
        SpaceResource(
            id=SPACE_ID,
            space_name="A栋3楼展厅",
            space_type=2,
            capacity=50,
            location="A栋3楼中庭",
            budget=Decimal("800.00"),
            open_start_time=time(9, 0),
            open_end_time=time(21, 0),
            status=1,
        )
    )
    await db_session.commit()

    # ---- 鉴权：只替换「查库拿用户」这一步，令牌验签仍走真实现 ----
    class _FakeUser:
        id = INSPECTOR_ID
        username = "inspect-tester"
        status = auth_service.USER_STATUS_ACTIVE
        avatar = None

    async def _fake_get_user_by_id(db, user_id):
        return _FakeUser()

    monkeypatch.setattr(auth_service, "get_user_by_id", _fake_get_user_by_id)
    monkeypatch.setattr(auth_service, "role_name_of", lambda user: "系统管理员")
    monkeypatch.setattr(auth_service, "permissions_of", lambda user: ["*"])

    token, _ = create_token(
        user_id=INSPECTOR_ID,
        role="系统管理员",
        token_type=TokenType.ACCESS,
        expires_delta=dt.timedelta(minutes=10),
    )

    # ---- 不写真实文件系统 ----
    # `inspect_service.save_image` 会把图片落到 `backend/uploads/`，**这一步与数据库无关** ——
    # 用例每跑一次就往那儿堆一批 1×1 PNG（实测跑几轮堆了 36 个）。
    # 本文件只关心「服务层有没有把 image_url 落进库」，不关心字节有没有真的写盘；
    # 真实落盘由模块 2 的用例与云库联调覆盖。
    async def _fake_save_image(raw, mime):
        return "/uploads/test/inspect.png"

    monkeypatch.setattr(inspect_service, "save_image", _fake_save_image)

    # ---- 假视觉模型：用例可以中途换剧本 ----
    state = SimpleNamespace(llm=fake_vision(FAULT_REPLY))
    application.dependency_overrides[get_vision_llm] = lambda: state.llm

    return SimpleNamespace(
        client=client,
        state=state,
        headers={"Authorization": f"Bearer {token}"},
        space_id=SPACE_ID,
        inspector_id=INSPECTOR_ID,
    )


def _submit(
    api,
    *,
    space_id=None,
    content=PNG_1PX,
    filename="inspect.png",
    mime="image/png",
    headers=None,
):
    return api.client.post(
        "/api/v1/inspect/submit",
        headers=api.headers if headers is None else headers,
        files={"file": (filename, content, mime)},
        data={"spaceId": str(api.space_id if space_id is None else space_id)},
    )


# ===========================================================================
# POST /inspect/submit
# ===========================================================================
async def test_submit_fault_creates_ticket(api, db_session):
    """判定「损坏」→ 200、返回 ticketId，且**巡检记录与工单都真的落了库**。"""
    from sqlalchemy import select

    from app.models.inspection import InspectRecord, RepairTicket

    resp = await _submit(api)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 200

    data = body["data"]
    assert data["deviceStatus"] == "损坏"
    assert data["repairSuggestion"]
    assert data["ticketId"], "判定为损坏时必须建工单"

    record = (await db_session.execute(select(InspectRecord))).scalars().one()
    assert record.space_id == api.space_id
    assert record.inspector_id == api.inspector_id, "巡检人必须来自 JWT"
    assert record.ai_result["deviceStatus"] == "损坏"
    assert record.ai_result["deviceName"] == "投影仪01"

    ticket = (await db_session.execute(select(RepairTicket))).scalars().one()
    assert ticket.id == data["ticketId"]
    assert ticket.inspect_id == record.id, "工单必须挂回刚建的巡检记录"
    assert ticket.ticket_status == 1, "新建工单应是「待处理」"
    assert ticket.handler_id is None, "还没人处理，处理人应为空"


async def test_submit_normal_creates_no_ticket(api, db_session):
    """判定「完好」→ 不建工单。这是**降噪**的关键：没坏的设备不该产生工单。"""
    from sqlalchemy import func, select

    from app.agent.chains.llm import build_fake_llm
    from app.models.inspection import RepairTicket

    api.state.llm = build_fake_llm([NORMAL_REPLY])

    resp = await _submit(api)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["deviceStatus"] == "完好"
    assert data["ticketId"] is None
    assert data["repairSuggestion"] == "", "完好时不该留维修建议"

    total = (await db_session.execute(select(func.count()).select_from(RepairTicket))).scalar_one()
    assert total == 0


async def test_submit_parse_failure_degrades_without_ticket(api, db_session):
    """模型回了一段散文（不是 JSON）→ 降级为「无法识别」，**仍留记录、但不建工单**。

    为什么记录仍要落库：用户提交过一次，库里必须查得到这次提交发生过；
    否则前端看不到任何痕迹，用户会以为接口坏了。
    """
    from sqlalchemy import select

    from app.agent.chains.llm import build_fake_llm
    from app.models.inspection import InspectRecord, RepairTicket

    api.state.llm = build_fake_llm([UNPARSABLE_REPLY])

    resp = await _submit(api)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["deviceStatus"] == "无法识别"
    assert data["ticketId"] is None

    record = (await db_session.execute(select(InspectRecord))).scalars().one()
    assert record.ai_result["parseFallback"] is True
    assert "rawText" in record.ai_result, "降级时把原始回复留档，便于排查模型到底说了什么"
    assert (await db_session.execute(select(RepairTicket))).scalars().all() == []


async def test_submit_without_token_is_401(client):
    """无令牌 → 401 / 40101（鉴权闸门必须真的在）"""
    resp = await client.post(
        "/api/v1/inspect/submit",
        files={"file": ("x.png", PNG_1PX, "image/png")},
        data={"spaceId": str(SPACE_ID)},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == 40101


async def test_submit_space_not_found(api):
    """不存在的场地 → 404 / 40402（不是 500：外键错误必须先被业务层挡下）"""
    resp = await _submit(api, space_id=999999)
    assert resp.status_code == 404
    assert resp.json()["code"] == 40402


async def test_submit_rejects_non_image(api):
    """内容不是图片（只是改了个后缀）→ 400 / 41001"""
    resp = await _submit(api, content=b"this is definitely not an image", filename="x.png")
    assert resp.status_code == 400
    assert resp.json()["code"] == 41001


# ===========================================================================
# GET /tickets/list
# ===========================================================================
async def test_list_joins_report_from_inspect_record(api):
    """列表里的 report / deviceStatus **不是**工单表上的字段，靠 JOIN 巡检记录取。

    这条用例真正守的是那个 JOIN：把 outerjoin 删掉，report 会变成 None，
    前端表格里「巡检报告」一列会静默空掉 —— 不报错，只是没内容。
    """
    await _submit(api)

    resp = await api.client.get("/api/v1/tickets/list", headers=api.headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    assert data["page"] == 1 and data["pageSize"] == 10
    assert data["total"] == 1
    item = data["list"][0]
    assert item["deviceStatus"] == "损坏"
    assert item["report"].startswith("投影仪指示灯"), "report 必须来自巡检记录的 ai_result"
    assert item["deviceName"] == "投影仪01"
    assert item["status"] == 1 and item["statusText"] == "待处理"
    assert item["spaceId"] == api.space_id


async def test_list_is_empty_without_tickets(api):
    """没有工单时返回空列表而不是报错 —— 前端首屏就是这种情况。"""
    resp = await api.client.get("/api/v1/tickets/list", headers=api.headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 0 and data["list"] == []


async def test_list_filters_by_status(api):
    """status 筛选：不匹配的状态应筛掉（防止 where 条件被写丢）"""
    await _submit(api)

    hit = await api.client.get("/api/v1/tickets/list", headers=api.headers, params={"status": 1})
    assert hit.json()["data"]["total"] == 1

    miss = await api.client.get("/api/v1/tickets/list", headers=api.headers, params={"status": 3})
    assert miss.json()["data"]["total"] == 0


async def test_list_rejects_bad_status(api):
    """非法 status → 400 / 40001（参数校验不能只写在 Query 的 ge/le 上就以为够了）"""
    resp = await api.client.get("/api/v1/tickets/list", headers=api.headers, params={"status": 9})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40001


# ===========================================================================
# PUT /tickets/{ticketId}/status
# ===========================================================================
async def test_ticket_status_flow(api, db_session):
    """1 待处理 → 2 处理中 → 3 已完成；处理人取自 JWT，不从请求体来。"""
    from app.models.inspection import RepairTicket

    ticket_id = (await _submit(api)).json()["data"]["ticketId"]

    resp = await api.client.put(
        f"/api/v1/tickets/{ticket_id}/status", headers=api.headers, json={"status": 2}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == 2 and data["statusText"] == "处理中"
    assert data["handlerId"] == api.inspector_id, "处理人必须来自 JWT（§5.1）"
    assert data["handleTime"], "处理时间不能为空"

    resp = await api.client.put(
        f"/api/v1/tickets/{ticket_id}/status", headers=api.headers, json={"status": 3}
    )
    assert resp.json()["data"]["statusText"] == "已完成"

    ticket = await db_session.get(RepairTicket, ticket_id)
    assert ticket.ticket_status == 3
    assert ticket.handler_id == api.inspector_id


async def test_ticket_status_rejects_unknown_value(api):
    """status=9 → 400 / 40001"""
    ticket_id = (await _submit(api)).json()["data"]["ticketId"]
    resp = await api.client.put(
        f"/api/v1/tickets/{ticket_id}/status", headers=api.headers, json={"status": 9}
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40001


async def test_ticket_status_unknown_ticket_is_40405(api):
    """不存在的工单 → 404 / 40405（而不是 500 或静默成功）"""
    resp = await api.client.put(
        "/api/v1/tickets/999999/status", headers=api.headers, json={"status": 3}
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == 40405
