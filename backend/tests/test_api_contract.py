"""
六、接口契约层（C1–C12）—— 对应 docs/test.md 第六节

用 `TestClient` + `app.dependency_overrides[get_db]` 覆盖数据库依赖，**全程离线**：
- 数据库：`get_db` 换成返回哨兵对象的假依赖（不建连接、不连真库）
- 取数：`dashboard_service.get_all_stats` 换成记录型桩，顺便断言 `days` 有没有透传到位
- LLM：`LLM_API_KEY = ""` 走真实降级路径（**不是**把 `generate_report` 换成桩）——
  C6/C8 要验的正是「没有 key 时不抛 500 而是降级」，把服务函数换掉就证明不了这件事

⚠️ 关于 C1 的「逐字节一致」
    「改造前的响应体」在仓库里没有留档（只有一次初始提交），做不了真的前后 diff。
    因此改为把当前响应体**钉死成字面量**：字段、顺序、分隔符（`separators=(",",":")`）
    任何一处变化都会失败。守护效果与「改动前后逐字节一致」等价，
    但要说清这是**契约冻结**，不是历史对比 —— 别在答辩时把它讲成后者。
"""
import contextlib
import json
import re

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.schemas.dashboard import MAX_DAYS, MIN_DAYS
from app.services import dashboard_service as svc

STATS_PATH = "/api/v1/dashboard/stats"
REPORT_PATH = "/api/v1/dashboard/report"

# 桩返回的统计结果（形状即 DashboardStatsData）
STATS = {
    "spaceUsageRate": 46.7,
    "deviceIdleRate": 20.0,
    "peakHours": [{"hour": 14, "count": 5}, {"hour": 9, "count": 3}],
    "faultFrequency": [{"deviceName": "投影仪A", "count": 3}],
}

# C1 的字面量基线：紧凑分隔符 + 原样 UTF-8（FastAPI 的 JSONResponse 用 ensure_ascii=False）
# ⚠️ `degraded` 于 2026-09-28 追加到**末尾**（原 B1 待办：/stats 库不可达兜底）。
#    前四个字段的位置一个没动 —— 前端按顺序渲染，挪位置才算破坏契约；
#    往后追加是新字段，但**仍属契约变更，需通知前端**。
# ⚠️ 2026-09-28 修正：`message` 由 `"ok"` 改为 `"操作成功"`。
#    原字面量写的是 `"ok"`，但实现（`app/core/response.py` 的 `ok()`）与
#    《规范》5.2 的原文都是 `"message": "操作成功"`；`app/api/v1/dashboard.py`
#    走的是 `success(data)` → 默认文案「操作成功」。实测响应确为 `"操作成功"`，
#    故本条基线**当初就写错了**（模块 8 交付时该用例从未跑通过，见文件头说明）。
EXPECTED_STATS_TEXT = (
    '{"code":200,"message":"操作成功","data":{"spaceUsageRate":46.7,"deviceIdleRate":20.0,'
    '"peakHours":[{"hour":14,"count":5},{"hour":9,"count":3}],'
    '"faultFrequency":[{"deviceName":"投影仪A","count":3}],"degraded":false}}'
)

# /stats 的 data 字段顺序（前端按顺序渲染，**在中间插字段或改顺序即为契约破坏**）
STATS_DATA_KEYS = ["spaceUsageRate", "deviceIdleRate", "peakHours", "faultFrequency", "degraded"]
REPORT_DATA_KEYS = ["suggestions", "exportUrl", "degraded"]

_FAKE_DB = object()        # 哨兵：证明假依赖被用上了，而不是真的建了会话


# ------------------------------------------------------------
# 夹具
# ------------------------------------------------------------
@pytest.fixture
def recorded_days():
    """服务层实际收到的 days 序列（断言透传用）"""
    return []


@contextlib.contextmanager
def client_with(stub_stats):
    """
    装配一个 TestClient：覆盖 get_db、并把取数换成 `stub_stats`。

    `app.dependency_overrides` 是**全局**可变状态，必须在 finally 里清掉 ——
    否则会污染同一进程里后续的用例。
    """
    async def _override_get_db():
        yield _FAKE_DB

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client(monkeypatch, recorded_days):
    """常规客户端：取数桩返回 STATS，并记录收到的 days"""
    async def _stub_stats(_db, days=svc.DEFAULT_DAYS):
        recorded_days.append(days)
        return STATS

    monkeypatch.setattr(svc, "get_all_stats", _stub_stats)
    with client_with(_stub_stats) as test_client:
        yield test_client


# ============================================================
# C1–C2：/stats 响应体与顺序
# ============================================================
def test_C1_stats响应体逐字节等于契约基线(client):
    """C1：HTTP 200，响应体与契约字面量**逐字节一致**（字段/顺序/分隔符全锁）"""
    response = client.get(STATS_PATH)

    assert response.status_code == 200
    assert response.text == EXPECTED_STATS_TEXT


def test_C2_外层与data内层key顺序未变(client):
    """
    C2：外层 `code/message/data`、`data` 内四字段顺序均未变。

    与 C1 的重合是有意的：C1 失败时只说明「有字节变了」，
    这条直接指出是**哪一层**的顺序变了，便于定位。
    """
    payload = client.get(STATS_PATH).json()

    assert list(payload.keys()) == ["code", "message", "data"]
    assert list(payload["data"].keys()) == STATS_DATA_KEYS


# ============================================================
# C3–C5：days 参数
# ============================================================
def test_C3_不传days时服务层收到7(client, recorded_days):
    """C3：不传 `days` → 服务层收到 7（默认值有单一定义处）"""
    client.get(STATS_PATH)

    assert recorded_days == [svc.DEFAULT_DAYS] == [7]


@pytest.mark.parametrize("days", [30, 1, 90])
def test_C4_days原样透传到服务层(client, recorded_days, days):
    """C4：`days` 为 30 / 1 / 90 → 服务层分别收到 30 / 1 / 90（不再被静默忽略）"""
    response = client.get(STATS_PATH, params={"days": days})

    assert response.status_code == 200
    assert recorded_days == [days], "days 必须原样透传，不能被路由层改写或忽略"


@pytest.mark.parametrize("days", ["0", "91", "-1", "abc"])
def test_C5_越界与非法days被400拦下(client, recorded_days, days):
    """
    C5：`0` / `91` / `-1` / `abc` → 全部 **HTTP 400 + code 40001**。

    `0` 与 `91` 是**边界外**（范围 1–90，闭区间），`abc` 是类型错。
    关键在于：非法请求**不得**落到服务层 —— 否则会拿脏参数去查库。

    ⚠️ **2026-09-28 修正：断言由 422 改为 400。**
    本条原先断言 422（FastAPI 的默认行为），但**团队在合并时把这个默认改掉了** ——
    `app/core/response.py` 的 `RequestValidationError` 处理器统一返回
    「HTTP 400 + `code=40001`」，这是全项目口径，不只本模块：

        docs/api.md:191          「参数校验失败是 HTTP 400 + code=40001」
        docs/api.md:27           HTTP 按语义返回真实状态（… 参数校验失败 400 …）
        docs/PR-integrate-module3.md:28
                                 「Pydantic 校验失败 → 400 / 40001（团队把 FastAPI 默认的 422 改掉了）」
                                 「422 → 400，测试同步」
        docs/团队仓库合并冲突比对.md:738-739
                                 「即 Pydantic 校验失败取『HTTP 400 + 业务码 40001』这条」

    注意这会连带影响**全局**：改成 422 会打坏 test_response_envelope / test_auth_api
    等一批断言 400 的用例。所以改的是本条，不是处理器。
    `docs/api-dashboard.md` 与本模块 `app/api/v1/dashboard.py` 的 docstring 里
    残留的「422」措辞同样是旧口径，属文档待同步项。
    """
    response = client.get(STATS_PATH, params={"days": days})

    assert response.status_code == 400
    assert response.json()["code"] == 40001
    assert recorded_days == [], "被参数校验拦下的请求不应触达服务层"


# ============================================================
# C6–C8：/report 降级响应
# ============================================================
def test_C6_无key时report返回200并降级(client, no_llm_key):
    """C6：`LLM_API_KEY = ""` → HTTP 200、`degraded=true`，**不抛 500**"""
    response = client.get(REPORT_PATH)

    assert response.status_code == 200
    assert response.json()["data"]["degraded"] is True


def test_C7_report的data字段名为camelCase(client, no_llm_key):
    """C7：`data` 字段名为 `suggestions` / `exportUrl` / `degraded`"""
    data = client.get(REPORT_PATH).json()["data"]

    assert list(data.keys()) == REPORT_DATA_KEYS


def test_C8_导出链接形如static路径且建议非空三要素齐全(client, no_llm_key):
    """
    C8：`exportUrl` 形如 `/static/exports/dashboard_YYYYMMDD_HHMMSS.csv`；
    `suggestions` 非空；每条三要素齐全。

    ⚠️ 本条的断言在**阶段 3** 由 `exportUrl is None` 改为匹配路径 ——
    那不是为了让测试变绿而放宽，而是导出功能真的落地了（见 docs/test.md 第六节）。
    改的是「期望值随实现推进」，与「把测试改到能过」是两件事。
    """
    data = client.get(REPORT_PATH).json()["data"]

    assert re.match(r"^/static/exports/dashboard_\d{8}_\d{6}\.csv$", data["exportUrl"] or ""), \
        f"exportUrl 应为 /static/exports/ 下的 CSV 相对路径，实际 {data['exportUrl']!r}"
    assert data["suggestions"], "降级也必须给出建议，不能是空数组"
    for item in data["suggestions"]:
        for key in ("finding", "evidence", "suggestion"):
            assert isinstance(item[key], str) and item[key].strip(), \
                f"三要素 {key} 缺失或为空: {item}"


def test_C9_report的days透传到取数环节(client, recorded_days, no_llm_key):
    """
    C9：`/report?days=15` → `15` 透传到取数环节。

    注意这里记的是**取数**收到的 days —— 降级路径同样要按请求的窗口取数，
    不能因为 LLM 不可用就退回默认 7 天。
    """
    client.get(REPORT_PATH, params={"days": 15})

    assert recorded_days == [15]


def test_C13_库不可达时仍200且exportUrl为null(monkeypatch, no_llm_key, export_dir):
    """
    C13：数据库不可达 → HTTP 200、`degraded=true`、**`exportUrl` 为 null**。

    与 C6 的差别只在 exportUrl：C6 那条 stats 取到了，有统计数字可导；
    这里连 stats 都没有，硬导会得到一个「统计字段全空」的 CSV，比 null 更容易误导。
    所以 `degraded=true` 与 `exportUrl=null` 不等价，两个分支都要有断言。
    """
    async def _boom(_db, days=svc.DEFAULT_DAYS):
        raise RuntimeError("模拟数据库不可达")

    monkeypatch.setattr(svc, "get_all_stats", _boom)

    with client_with(_boom) as failing_client:
        response = failing_client.get(REPORT_PATH)

    assert response.status_code == 200, "本接口不返回 500（《规范》13.1 演示应急预案）"
    data = response.json()["data"]
    assert data["degraded"] is True
    assert data["exportUrl"] is None
    assert data["suggestions"], "取数失败也要给出说明性建议，不能是空数组"


# C14：/stats 库不可达（2026-09-28 补，原 B1 待办）
# ------------------------------------------------------------
def test_C14_stats库不可达时仍200并降级为空结果(monkeypatch):
    """
    C14：数据库不可达 → `/stats` 返回 **200**、`degraded=true`、四项为空、**不抛 500**。

    这条是 2026-09-28 补的兜底（原 B1 待办），此前实测是：
        /report 库不可达 → 200 + degraded       ✓
        /stats  库不可达 → **500 Internal Server Error**  ✗
    同一份验收标准（「断开数据库时 /stats 返回 200 + degraded=true + 空 4 字段，
    不再返回 500」），两个接口一个达标一个没有。

    断言「四项为空」而不只是看状态码，是因为**空手返回 200 也能过状态码** ——
    那样前端会拿到四个 0 却以为是真的 0%，比 500 更难查。所以必须同时锁：
    ① 状态码 200 ② degraded=true ③ 四项确实是零值占位。
    """
    async def _boom(_db, days=svc.DEFAULT_DAYS):
        raise RuntimeError("模拟数据库不可达")

    monkeypatch.setattr(svc, "get_all_stats", _boom)

    with client_with(_boom) as failing_client:
        response = failing_client.get(STATS_PATH)

    assert response.status_code == 200, "本接口不返回 500（《规范》13.1 演示应急预案）"
    data = response.json()["data"]

    assert data["degraded"] is True
    assert data["spaceUsageRate"] == 0.0
    assert data["deviceIdleRate"] == 0.0
    assert data["peakHours"] == []
    assert data["faultFrequency"] == []
    # 降级时字段集合不能变 —— 前端不该为了降级写第二套解析
    assert list(data.keys()) == STATS_DATA_KEYS


def test_C14补充_正常路径的degraded为false(monkeypatch, recorded_days):
    """
    反向锁：库正常时 `degraded` 必须是 `false`。

    否则「永远返回 true 的常量」也能让 C14 通过，而那样前端会把每次正常请求
    都标成「数据暂时不可用」—— 比不实现兜底还糟。
    """
    async def _stub_stats(_db, days=svc.DEFAULT_DAYS):
        recorded_days.append(days)
        return STATS

    monkeypatch.setattr(svc, "get_all_stats", _stub_stats)
    with client_with(_stub_stats) as ok_client:
        data = ok_client.get(STATS_PATH).json()["data"]

    assert data["degraded"] is False
    assert data["spaceUsageRate"] == STATS["spaceUsageRate"]


# ============================================================
# C10–C12：OpenAPI 契约
# ============================================================
def test_C10_openapi暴露days参数及范围():
    """C10：两个接口都暴露 `days`，且 `default=7 / minimum=1 / maximum=90`"""
    spec = app.openapi()

    for path in (STATS_PATH, REPORT_PATH):
        params = spec["paths"][path]["get"]["parameters"]
        days = [p for p in params if p["name"] == "days"]
        assert days, f"{path} 未暴露 days 参数"
        schema = days[0]["schema"]
        assert schema["default"] == svc.DEFAULT_DAYS == 7
        assert schema["minimum"] == MIN_DAYS == 1
        assert schema["maximum"] == MAX_DAYS == 90


def test_C11_openapi含五个业务schema():
    """C11：五个 schema 都在（前端据此生成类型）"""
    schemas = app.openapi()["components"]["schemas"]

    for name in ("PeakHourItem", "FaultFrequencyItem",
                 "DashboardStatsData", "Suggestion", "DashboardReportData"):
        assert name in schemas, f"OpenAPI 缺 schema {name}"


def test_C12_两个data模型的属性名均为camelCase():
    """C12：`DashboardStatsData` / `DashboardReportData` 的属性名均为 camelCase"""
    schemas = app.openapi()["components"]["schemas"]

    assert list(schemas["DashboardStatsData"]["properties"].keys()) == STATS_DATA_KEYS
    assert list(schemas["DashboardReportData"]["properties"].keys()) == REPORT_DATA_KEYS


def test_C12补充_校验范围与传输用同一个单一定义处():
    """
    补一条 docs/test.md 没写、但契约层最容易漂移的：`MIN_DAYS` / `MAX_DAYS` / `DEFAULT_DAYS`
    在 `schemas.dashboard` 定义、由路由与 OpenAPI 共用。

    若哪天有人在路由里手写 `Query(7, ge=1, le=90)`，这条会失败 —— 那正是要抓的漂移。
    """
    spec = app.openapi()
    rendered = json.dumps(spec["paths"][STATS_PATH]["get"]["parameters"])

    assert f'"minimum": {MIN_DAYS}' in rendered
    assert f'"maximum": {MAX_DAYS}' in rendered
    assert f'"default": {svc.DEFAULT_DAYS}' in rendered
