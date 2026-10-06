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

    from app.agent.chains.llm import build_fake_llm

    api.state.llm = build_fake_llm([NORMAL_REPLY])

    resp = await _submit(api)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["deviceStatus"] == "完好"
    assert data["ticketId"] is None
    assert data["repairSuggestion"] == "", "完好时不该留维修建议"


# ===========================================================================
# 巡检判定 → 回写 device_resource.device_status
#
# 用户反馈的原始问题：「AI 智能巡检有设备损坏，在资源与设备里面，
# 设备的状态还是完好」。根因是巡检只落 inspect_record 与 repair_ticket，
# **从不碰设备台账**（工单的 device_id 还写死 None，注释说设备名映射不回 id）。
# 下面这组用例把「回写」这条链路钉住。
# ===========================================================================
def _add_device(
    db_session,
    *,
    device_id: int,
    name: str,
    status: int = 1,
    available: int = 1,
    total: int | None = None,
):
    """插一台测试设备。`total` 缺省与 `available` 一致。

    ⚠️ `total_count` 是**回加时的上限**（`_restore_device` 用它夹住 +1）。
    若只给 `available=2` 而 `total_count` 仍是 1，回加会被上限挡住 ——
    那是**正确**行为，但会让「报损 −1 / 修好 +1」的用例看起来像坏了。
    所以两者要一起给。
    """
    from app.models.resource import DeviceResource

    db_session.add(
        DeviceResource(
            id=device_id,
            device_name=name,
            device_type="投影仪",
            device_status=status,
            total_count=available if total is None else total,
            available_count=available,
        )
    )
    return db_session


async def test_submit_fault_updates_device_ledger(api, db_session):
    """判定「损坏」且设备名唯一命中 → 台账状态改「损坏」、工单挂上 device_id。

    这是用户反馈那个不一致的**回归用例**：AI 说损坏，设备台账必须同步。
    """
    from sqlalchemy import select

    from app.models.inspection import RepairTicket
    from app.models.resource import DeviceResource

    _add_device(db_session, device_id=901, name="投影仪01", status=1, available=1)
    await db_session.commit()

    resp = await _submit(api)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["deviceStatus"] == "损坏"

    device = (
        (await db_session.execute(select(DeviceResource).where(DeviceResource.id == 901)))
        .scalars()
        .one()
    )
    # 关键断言：不再显示「完好」
    assert device.device_status == 2, "AI 判定损坏，设备台账必须同步为损坏(2)"
    # 报损要**减一台可借数**（2026-10-06 口径变更，取代原先的「静态上限不动」）：
    # 报损 −1 / 维修核验通过 +1，所以 available_count 的语义是「台账上可用的物理台数」。
    assert device.available_count == 0, "报损 1 台后，可借数应从 1 减到 0"

    ticket = (await db_session.execute(select(RepairTicket))).scalars().one()
    assert ticket.device_id == 901, "工单应挂到命中的设备上，而不是恒为 None"


async def test_submit_fault_leaves_unmatched_device_untouched(api, db_session):
    """AI 认出的设备名在台账里不存在 → **不猜**，一台都不改，工单 device_id 仍为空。"""
    from sqlalchemy import select

    from app.models.inspection import RepairTicket
    from app.models.resource import DeviceResource

    _add_device(db_session, device_id=902, name="音响01", status=1, available=1)
    await db_session.commit()

    resp = await _submit(api)  # FAULT_REPLY 的 deviceName 是「投影仪01」
    assert resp.status_code == 200, resp.text

    device = (
        (await db_session.execute(select(DeviceResource).where(DeviceResource.id == 902)))
        .scalars()
        .one()
    )
    assert device.device_status == 1, "名字对不上时绝不能改别的设备"
    assert device.available_count == 1

    ticket = (await db_session.execute(select(RepairTicket))).scalars().one()
    assert ticket.device_id is None


async def test_submit_fault_ambiguous_name_is_not_guessed(api, db_session):
    """同名设备有多台（投影仪1..4 这种）→ **宁可不写**，避免把好设备标成损坏。

    设备表里同型号多台是常态。挑错一台不会报错，只会让那台设备再也借不出去 ——
    属于「看起来正常、实际错了」的问题，所以匹配不唯一时必须放弃。
    """
    from sqlalchemy import select

    from app.models.resource import DeviceResource

    _add_device(db_session, device_id=903, name="投影仪01", status=1, available=1)
    _add_device(db_session, device_id=904, name="投影仪01", status=1, available=1)
    await db_session.commit()

    resp = await _submit(api)
    assert resp.status_code == 200, resp.text

    rows = (
        (await db_session.execute(select(DeviceResource).where(DeviceResource.id.in_((903, 904)))))
        .scalars()
        .all()
    )
    assert [r.device_status for r in rows] == [1, 1], "名字不唯一时不应改动任何一台"


def _fault_reply(device_name: str, device_status: str = "损坏") -> str:
    """按指定设备名拼一份「异常」回复，用于验匹配策略。"""
    return json.dumps(
        {
            "deviceStatus": device_status,
            "report": f"{device_name} 存在异常。",
            "repairSuggestion": "安排维修。",
            "deviceName": device_name,
            "deviceType": "设备",
        },
        ensure_ascii=False,
    )


async def test_submit_fault_matches_by_unique_substring(api, db_session):
    """模型报品类、台账写品牌型号 → 靠**唯一子串**命中。

    这条来自真实故障：台账里是 `大疆无人机`，而视觉模型报的是 `无人机` ——
    它看的是像素，不可能稳定输出我们台账里的精确名字。
    只做精确相等时永远匹配不上，表现就是「AI 说设备损坏，
    资源与设备里状态还是完好」。
    """
    from sqlalchemy import select

    from app.agent.chains.llm import build_fake_llm
    from app.models.inspection import RepairTicket
    from app.models.resource import DeviceResource

    _add_device(db_session, device_id=911, name="大疆无人机", status=1, available=2)
    await db_session.commit()

    api.state.llm = build_fake_llm([_fault_reply("无人机", "缺失配件")])

    resp = await _submit(api)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["deviceStatus"] == "缺失配件"

    device = (
        (await db_session.execute(select(DeviceResource).where(DeviceResource.id == 911)))
        .scalars()
        .one()
    )
    assert device.device_status == 3, "「无人机」应唯一子串命中「大疆无人机」并标为缺失配件(3)"

    ticket = (await db_session.execute(select(RepairTicket))).scalars().one()
    assert ticket.device_id == 911


async def test_submit_fault_substring_ambiguous_is_not_guessed(api, db_session):
    """子串命中多台 → 依旧放弃（`无人机` 同时命中两台无人机时不猜）。

    这是放宽匹配的代价：歧义时必须退回「不写」，否则会把好设备标成故障。
    """
    from sqlalchemy import select

    from app.agent.chains.llm import build_fake_llm
    from app.models.resource import DeviceResource

    _add_device(db_session, device_id=912, name="大疆无人机", status=1, available=1)
    _add_device(db_session, device_id=913, name="道通无人机", status=1, available=1)
    await db_session.commit()

    api.state.llm = build_fake_llm([_fault_reply("无人机")])

    resp = await _submit(api)
    assert resp.status_code == 200, resp.text

    rows = (
        (await db_session.execute(select(DeviceResource).where(DeviceResource.id.in_((912, 913)))))
        .scalars()
        .all()
    )
    assert [r.device_status for r in rows] == [1, 1], "子串有多台命中时不应改动任何一台"


async def test_submit_fault_decrements_available_count(api, db_session):
    """报损 1 台 → 可借数 −1；再修好 → +1。这一对必须对称。

    「报损减、修好加」是 2026-10-06 的口径。此前是「两边都不动」，
    用户反馈「报损后可借数没减」；更早一版只做了减、没做加，
    又变成「修好了也借不出去」。所以两个方向要**一起**钉住。
    """
    from sqlalchemy import select

    from app.models.resource import DeviceResource

    # 2 台可借，报损 1 台后应剩 1 台
    _add_device(db_session, device_id=931, name="投影仪01", status=1, available=2)
    await db_session.commit()

    data = (await _submit(api)).json()["data"]
    assert data["deviceWarning"] is None, "还有可借台数时不该有提示"

    device = (
        (await db_session.execute(select(DeviceResource).where(DeviceResource.id == 931)))
        .scalars()
        .one()
    )
    assert device.available_count == 1, "2 台里报损 1 台，可借数应变 1"

    # 维修完成 → 加回 2
    await api.client.put(
        f"/api/v1/tickets/{data['ticketId']}/status", headers=api.headers, json={"status": 3}
    )
    await db_session.refresh(device)
    assert device.available_count == 2, "修好后应加回 2"


async def test_submit_fault_at_zero_warns_instead_of_going_negative(api, db_session):
    """可借数已是 0 时再报损：**不再往下减**，并回传「已有人报修」的提示。

    不允许负库存，也不能静默什么都不做 —— 用户看到「工单建了、可借数没变」
    会以为是 bug，所以必须把原因带回去。
    """
    from sqlalchemy import select

    from app.models.resource import DeviceResource

    _add_device(db_session, device_id=932, name="投影仪01", status=1, available=0)
    await db_session.commit()

    data = (await _submit(api)).json()["data"]
    assert data["ticketId"], "仍然要建工单 —— 故障是真实的"
    assert data["deviceWarning"], "可借数为 0 时必须回传提示"
    assert "已有人报修" in data["deviceWarning"], data["deviceWarning"]

    device = (
        (await db_session.execute(select(DeviceResource).where(DeviceResource.id == 932)))
        .scalars()
        .one()
    )
    assert device.available_count == 0, "不允许负库存"
    assert device.device_status == 2, "状态照改 —— 它确实报损了"


async def test_restore_never_exceeds_total_count(api, db_session):
    """回加不得超过 `total_count`，否则 2 台的设备能被加成 3 台。

    报损在下限 0 处会**不再减**，所以「减」的次数可能少于「加」的次数；
    没有上限保护就会凭空多出台数。
    """

    from app.models.resource import DeviceResource

    # 可借数已是上限，直接走一遍恢复：不应超过 total_count
    _add_device(db_session, device_id=933, name="投影仪01", status=1, available=2)
    await db_session.commit()

    from app.models.inspection import RepairTicket
    from app.services import inspect_service

    device = await db_session.get(DeviceResource, 933)
    device.device_status = 2
    device.available_count = 2  # 已被人工加回上限
    await db_session.commit()

    ticket = RepairTicket(device_id=933, space_id=api.space_id, ticket_status=1)
    db_session.add(ticket)
    await db_session.flush()

    await inspect_service._restore_device(db_session, ticket)
    await db_session.commit()
    await db_session.refresh(device)

    assert device.available_count == 2, f"不得超过 total_count=2，实际 {device.available_count}"


async def test_submit_unrecognized_does_not_touch_device(api, db_session):
    """判定「无法识别」→ 不建工单、也不改台账。

    照片拍糊了不代表设备坏了。这与 `ABNORMAL_STATUSES` 不含「无法识别」是同一口径。
    """
    from sqlalchemy import func, select

    from app.agent.chains.llm import build_fake_llm
    from app.models.inspection import RepairTicket
    from app.models.resource import DeviceResource

    _add_device(db_session, device_id=905, name="投影仪01", status=1, available=1)
    await db_session.commit()

    api.state.llm = build_fake_llm([UNPARSABLE_REPLY])

    resp = await _submit(api)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["ticketId"] is None

    device = (
        (await db_session.execute(select(DeviceResource).where(DeviceResource.id == 905)))
        .scalars()
        .one()
    )
    assert device.device_status == 1, "无法识别时不应动设备台账"
    assert device.available_count == 1

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


async def test_ticket_done_restores_device(api, db_session):
    """人工把工单推成「已完成」→ 设备恢复可借（`device_status` 改回 1）。

    这是「修复完成后可用的设备没有增加」的**回归用例**。
    上一轮只做了单向同步（完好→损坏），没有反向路径，设备永远借不出去。
    """
    from sqlalchemy import select

    from app.models.resource import DeviceResource

    _add_device(db_session, device_id=921, name="投影仪01", status=1, available=1)
    await db_session.commit()

    # 巡检判定损坏 → 设备被标为 2
    ticket_id = (await _submit(api)).json()["data"]["ticketId"]
    device = (
        (await db_session.execute(select(DeviceResource).where(DeviceResource.id == 921)))
        .scalars()
        .one()
    )
    assert device.device_status == 2, "前置条件：巡检已把设备标为损坏"
    assert device.available_count == 0, "前置条件：报损已把可借数减到 0"

    # 处理完成 → 设备应恢复
    resp = await api.client.put(
        f"/api/v1/tickets/{ticket_id}/status", headers=api.headers, json={"status": 3}
    )
    assert resp.status_code == 200, resp.text

    await db_session.refresh(device)
    assert device.device_status == 1, "维修完成后设备必须恢复为「完好」，否则永远借不出去"
    assert device.available_count == 1, "维修完成后可借数必须 +1 回来"
    # 接口把恢复结果回传，前端才能提示「设备已恢复可借」
    assert resp.json()["data"]["availableCount"] == 1
    assert resp.json()["data"]["deviceId"] == 921


async def test_ticket_processing_does_not_restore_device(api, db_session):
    """只推到「处理中」**不**恢复设备 —— 修还没修好，不能提前放行。"""
    from sqlalchemy import select

    from app.models.resource import DeviceResource

    _add_device(db_session, device_id=922, name="投影仪01", status=1, available=1)
    await db_session.commit()

    ticket_id = (await _submit(api)).json()["data"]["ticketId"]
    await api.client.put(
        f"/api/v1/tickets/{ticket_id}/status", headers=api.headers, json={"status": 2}
    )

    device = (
        (await db_session.execute(select(DeviceResource).where(DeviceResource.id == 922)))
        .scalars()
        .one()
    )
    assert device.device_status == 2, "还没修好就恢复可借，是更严重的错"


async def test_handle_verification_failure_does_not_restore_device(api, db_session, application):
    """核验未通过 → **不**恢复设备；核验通过 → 恢复。

    这条把「恢复」与「AI 核验结论」绑在一起：恢复可借 = 宣称设备能用了，
    必须有凭据（核验通过的照片），而不是单方面关掉工单。

    ⚠️ `/handle` 走的是 `get_optional_vision_llm` 这个依赖（与 `/inspect/submit`
    的 `get_vision_llm` **不是同一个**，原因是核验链路允许模型缺席）。
    所以这里要覆盖的是它；不覆盖的话会打真实 API，用例联网必挂。
    """
    from sqlalchemy import select

    from app.agent.chains.llm import build_fake_llm
    from app.core.llm import get_optional_vision_llm
    from app.models.resource import DeviceResource

    _add_device(db_session, device_id=923, name="投影仪01", status=1, available=1)
    await db_session.commit()

    ticket_id = (await _submit(api)).json()["data"]["ticketId"]

    async def _post_handle():
        return await api.client.post(
            f"/api/v1/tickets/{ticket_id}/handle",
            headers=api.headers,
            files={"file": ("after.png", PNG_1PX, "image/png")},
        )

    application.dependency_overrides[get_optional_vision_llm] = lambda: api.state.llm
    try:
        # 核验仍判定损坏 → 不通过，设备保持损坏
        api.state.llm = build_fake_llm(
            [
                json.dumps(
                    {
                        "deviceStatus": "损坏",
                        "report": "指示灯仍不亮，未修复。",
                        "deviceName": "投影仪01",
                    },
                    ensure_ascii=False,
                )
            ]
        )
        resp = await _post_handle()
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["passed"] is False

        device = (
            (await db_session.execute(select(DeviceResource).where(DeviceResource.id == 923)))
            .scalars()
            .one()
        )
        assert device.device_status == 2, "核验未通过时不能恢复可借"

        # 核验判定完好 → 通过，设备恢复
        api.state.llm = build_fake_llm(
            [
                json.dumps(
                    {
                        "deviceStatus": "完好",
                        "report": "指示灯已恢复正常，部件齐全。",
                        "deviceName": "投影仪01",
                    },
                    ensure_ascii=False,
                )
            ]
        )
        resp = await _post_handle()
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["passed"] is True

        await db_session.refresh(device)
        assert device.device_status == 1, "核验通过后设备必须恢复可借"
    finally:
        application.dependency_overrides.pop(get_optional_vision_llm, None)


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
