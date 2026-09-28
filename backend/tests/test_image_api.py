"""
摄像头空间感知 —— 接口层测试
====================================================================

覆盖设计文档 §9.1 中的 T18 / T19：
    T18 未认证时返回 401
    T19 全链路（假模型）返回统一响应体，code=200

本文件验证的是**装配是否正确**：
    路由注册 → 依赖注入 → 服务调用 → 统一响应体 → 全局异常处理

不连数据库：
    get_db 被替换成「返回 None 的会话」，候选场地查询被 monkeypatch 替换。
    真正的数据库联调请在独立测试库 smart_scheduler_test 上另行执行。
"""

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from app.core.config import settings
from app.core.database import get_db
from app.core.llm import get_vision_llm
from app.main import app
from app.schemas.image import SpaceCandidate
from app.services import image_service

# ===========================================================================
# 脚本化响应：不同接口需要不同形状的模型返回
# ===========================================================================

SPACE_REPLY = (
    '{"spaceId": 101, "spaceName": "A栋3楼展厅", "rawText": "A-3F 展厅", '
    '"deviceHints": ["投影仪"], "confidence": 0.92, "question": null}'
)

SKETCH_REPLY = (
    '{"capacity": 30, "layout": "剧院式排布，前方设讲台", '
    '"requirements": ["需要投影"], "confidence": 0.85, "question": null}'
)


@pytest.fixture
def make_client(monkeypatch):
    """
    构造「不连库、不联网」测试客户端的工厂。

    参数：
        responses : list[str]  假模型的脚本化回复（按调用顺序消费）

    返回：
        TestClient

    为什么是工厂而不是单一夹具：
        空间识别与草图识别需要**不同形状**的模型回复。
        用统一夹具会让每个用例拿到不匹配的数据，测出来的行为也就没意义了。
        工厂形式允许每个用例声明自己需要的剧本。

    做了五件事：
        1. 打开 AUTH_BYPASS —— 免 Token 调用（见下方说明）
        2. 替换 get_db —— 返回 None 的会话（业务不再查库，够用）
        3. 替换 get_vision_llm —— 喂入脚本化的假模型
        4. monkeypatch 候选场地查询 —— 给固定数据
        5. 关闭空档计算，避免它去查数据库

    AUTH_BYPASS 为什么要显式 monkeypatch：
        合并前本夹具依赖开发者本地 .env 里恰好写着 AUTH_BYPASS=true，
        那会让「用例是否通过」取决于机器上的私有配置 —— CI 或另一台
        机器上没有这个变量时，全部用例会集体变成 401。这里显式打开，
        夹具自身即可复现；需要验证鉴权的用例请用下面的 auth_client。
    """
    clients: list[TestClient] = []

    async def _fake_db():
        """占位数据库依赖：直接 yield None"""
        yield None

    async def _fake_candidates(db, limit=None):
        return [
            SpaceCandidate(
                spaceId=101,
                spaceName="A栋3楼展厅",
                spaceType=2,
                location="A栋3楼",
                capacity=40,
            )
        ]

    monkeypatch.setattr(settings, "AUTH_BYPASS", True)
    monkeypatch.setattr(settings, "IMAGE_ENABLE_AVAILABLE_SLOTS", False)
    monkeypatch.setattr(image_service, "list_active_space_candidates", _fake_candidates)

    def _make(responses: list[str]) -> TestClient:
        fake = FakeMessagesListChatModel(responses=[AIMessage(content=r) for r in responses])
        app.dependency_overrides[get_db] = _fake_db
        app.dependency_overrides[get_vision_llm] = lambda: fake

        # 用 with 语义进入 TestClient，让 lifespan 正常执行（创建上传目录、释放连接池）
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield _make

    for c in clients:
        c.__exit__(None, None, None)
    app.dependency_overrides.clear()


# ===========================================================================
# T19：正常路径与统一响应体
# ===========================================================================


def test_analyze_returns_unified_response(make_client, fake_jpeg):
    """T19：/api/v1/image/analyze 返回统一响应体 + 正确的 data 结构"""
    client = make_client([SPACE_REPLY])

    resp = client.post(
        "/api/v1/image/analyze",
        files={"file": ("site.jpg", fake_jpeg, "image/jpeg")},
    )

    assert resp.status_code == 200
    body = resp.json()

    # —— 统一响应体三件套（§5.2）——
    assert set(body.keys()) == {"code", "message", "data"}
    assert body["code"] == 200

    # —— data 契约字段（§5.3 模块 2）——
    data = body["data"]
    assert data["type"] == "space"
    assert data["spaceId"] == 101
    assert data["spaceName"] == "A栋3楼展厅"
    assert data["confidence"] == pytest.approx(0.92)
    assert data["needConfirm"] is False
    # —— 本模块新增的扩展字段（§4.4）——
    assert "question" in data
    assert "candidates" in data
    assert "imageUrl" in data
    assert "availableTime" in data
    assert "devices" in data


def test_sketch_returns_unified_response(make_client, fake_jpeg):
    """草图接口返回统一响应体，且各字段按契约填充"""
    client = make_client([SKETCH_REPLY])

    resp = client.post(
        "/api/v1/image/sketch",
        files={"file": ("sketch.jpg", fake_jpeg, "image/jpeg")},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200

    data = body["data"]
    assert data["type"] == "sketch"
    assert data["capacity"] == 30
    assert data["layout"] == "剧院式排布，前方设讲台"
    assert data["requirements"] == ["需要投影"]
    assert data["confidence"] == pytest.approx(0.85)
    assert data["needConfirm"] is False


def test_sketch_mismatched_schema_degrades(make_client, fake_jpeg):
    """
    模型返回的字段与草图 schema 完全不搭（把空间识别的结果塞过来了）→ 走降级。

    这是一条真实存在的边界：模型偶尔会「答非所问」。
    我们要求的是「不能报错、响应体依然规范、明确告诉用户没读懂」，
    而不是把一个空结果当成成功返回。
    """
    client = make_client([SPACE_REPLY])

    resp = client.post(
        "/api/v1/image/sketch",
        files={"file": ("sketch.jpg", fake_jpeg, "image/jpeg")},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    data = body["data"]
    assert data["type"] == "sketch"
    assert data["capacity"] is None
    assert data["needConfirm"] is True
    assert data["question"]  # 必须给出引导语，而不是一个空结果


def test_missing_file_returns_friendly_error(make_client):
    """
    缺少 file 字段 → 统一响应体，而不是 FastAPI 默认的 422 结构。

    本项目约定（模块 10）：参数校验失败 = HTTP 400 + 业务码 40001，
    校验明细放在 data.errors 里，前端拿到的结构与其他错误完全一致。
    """
    client = make_client([SPACE_REPLY])

    resp = client.post("/api/v1/image/analyze")

    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 40001
    assert body["data"]["errors"]


def test_unsupported_image_type_returns_41001(make_client):
    """T11（接口层）：上传非图片 → 41001，且响应体规范"""
    client = make_client([SPACE_REPLY])

    resp = client.post(
        "/api/v1/image/analyze",
        files={"file": ("evil.txt", b"not an image at all", "image/jpeg")},
    )

    # 业务码 41001 映射到 HTTP 400（见 app/core/exceptions.py 的
    # _BUSINESS_ERROR_HTTP_STATUS）：本项目 HTTP 状态码与业务码并存，
    # 前者给网关/浏览器看，后者给业务前端看。
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 41001
    # 错误提示必须是人话，且不泄露内部堆栈
    assert "图片" in body["message"]


# ===========================================================================
# T18：鉴权
# ===========================================================================


@pytest.fixture
def auth_client(monkeypatch):
    """
    构造一个**开启真实鉴权**的测试客户端（AUTH_BYPASS=false）。

    单独成一个夹具的原因：
        make_client 显式打开 AUTH_BYPASS 才能免 Token 调通，
        而鉴权用例恰恰要验证「关掉放行后必须拦住」。
    """
    monkeypatch.setattr(settings, "AUTH_BYPASS", False)

    async def _fake_db():
        yield None

    app.dependency_overrides[get_db] = _fake_db
    client = TestClient(app)
    client.__enter__()
    try:
        yield client
    finally:
        client.__exit__(None, None, None)
        app.dependency_overrides.clear()


def test_missing_token_returns_401(auth_client, fake_jpeg):
    """T18：无 Authorization 请求头 → HTTP 401 / 业务码 40101（TokenMissingError）

    ⚠️ **2026-09-28 改口径**：认证失败保留 HTTP 状态行，不再是 200 + `code=401`。
    主文档 5.2 的「统一响应体」说的是 `{code, message, data}` 这个**结构**，
    与状态码正交——401 仍走统一响应体，只是状态行写真值；前端 axios 拦截器靠状态行
    跳登录。与本模块「参数校验失败 → 200 + code=400」性质不同：那是请求已到业务层、
    前端留在原页改输入，认证失败是整类请求都不该发出去。

    实现处：`core/exceptions.py` 的 `ErrorCode` 401xx → HTTP 401 映射
    （`_BUSINESS_ERROR_HTTP_STATUS`）。
    """
    resp = auth_client.post(
        "/api/v1/image/analyze",
        files={"file": ("site.jpg", fake_jpeg, "image/jpeg")},
    )

    assert resp.status_code == 401
    body = resp.json()
    assert set(body) == {"code", "message", "data"}, "401 也必须是统一响应体结构"
    assert body["code"] == 40101
    assert "登录" in body["message"] or "认证" in body["message"]


def test_malformed_auth_header_returns_401(auth_client, fake_jpeg):
    """
    T18：Authorization 格式不对（缺 Bearer 前缀）→ 40101。

    注意与下一条用例的区别：`HTTPBearer` 认不出这个头，等价于「没带令牌」，
    因此码是 40101 而不是 40102 —— 前端据此提示「请先登录」而不是「登录已失效」。
    """
    resp = auth_client.post(
        "/api/v1/image/analyze",
        files={"file": ("site.jpg", fake_jpeg, "image/jpeg")},
        headers={"Authorization": "this.is.not.a.valid.token"},
    )

    assert resp.status_code == 401
    assert resp.json()["code"] == 40101


def test_invalid_token_returns_401(auth_client, fake_jpeg):
    """T18：Token 签名无效 → 40102（TokenInvalidError，令牌结构可识别但验签失败）"""
    resp = auth_client.post(
        "/api/v1/image/analyze",
        files={"file": ("site.jpg", fake_jpeg, "image/jpeg")},
        headers={"Authorization": "Bearer this.is.not.a.valid.token"},
    )

    assert resp.status_code == 401
    assert resp.json()["code"] == 40102


def test_valid_token_is_accepted(monkeypatch, fake_jpeg):
    """
    T18 反向用例：签发一个合法 Token，应当被放行（防止鉴权写死成全拦）。

    合并时改写了三处，原因见下 —— 原版测不到「放行」这条路径：

    1. **令牌改由 `create_token` 签发**。原版手写 JWT，载荷是
       `{userId, username, role, exp}`；本项目 `decode_token` 要求的是
       `{sub, type, jti, iat, exp, ver}`（RFC 7519 的 `sub` + 自定义
       `type`/`jti` 用于区分 access/refresh 与支持强制下线）。
       按原载荷签发的令牌，在本项目里就是一枚「结构不符的伪造令牌」，
       必然得到 40102。
    2. **补齐用户查询**。`get_current_user` 验签后还要查库取角色与状态，
       而本文件其他用例把 `get_db` 换成了返回 None 的会话，查库必失败。
       故这里 monkeypatch 掉 `auth_service` 的三个查询函数。
    3. **不再依赖 `.env`**。原版靠外部 AUTH_BYPASS=true 才跑得通。
    """
    import datetime as dt

    from app.core.security import TokenType, create_token
    from app.services import auth_service

    monkeypatch.setattr(settings, "AUTH_BYPASS", False)

    token, _ = create_token(
        user_id=1,
        role="user",
        token_type=TokenType.ACCESS,
        expires_delta=dt.timedelta(minutes=5),
    )

    class _FakeUser:
        """仅提供 get_current_user 会读取的四个字段。"""

        id = 1
        username = "user01"
        status = auth_service.USER_STATUS_ACTIVE
        avatar = None

    async def _fake_get_user_by_id(db, user_id):
        return _FakeUser()

    monkeypatch.setattr(auth_service, "get_user_by_id", _fake_get_user_by_id)
    monkeypatch.setattr(auth_service, "role_name_of", lambda user: "user")
    monkeypatch.setattr(auth_service, "permissions_of", lambda user: [])

    async def _fake_db():
        yield None

    async def _fake_candidates(db, limit=None):
        return [SpaceCandidate(spaceId=101, spaceName="A栋3楼展厅", spaceType=2, capacity=40)]

    monkeypatch.setattr(settings, "IMAGE_ENABLE_AVAILABLE_SLOTS", False)
    monkeypatch.setattr(image_service, "list_active_space_candidates", _fake_candidates)

    fake = FakeMessagesListChatModel(responses=[AIMessage(content=SPACE_REPLY)])
    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_vision_llm] = lambda: fake

    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/image/analyze",
                files={"file": ("site.jpg", fake_jpeg, "image/jpeg")},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.json()["code"] == 200


# ===========================================================================
# 基础接口
# ===========================================================================


def test_health_check(make_client):
    """健康检查接口应能正常返回，供部署探活与联调自检使用"""
    client = make_client([SPACE_REPLY])

    resp = client.get("/api/v1/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    # 字段名以模块 10 的 health.py 为准：status / service / env。
    # 模块 2 原版断言的是 data["app"]，那是其开发期临时接口的字段名。
    assert body["data"]["status"] == "ok"
    assert body["data"]["service"]
    assert body["data"]["env"]
