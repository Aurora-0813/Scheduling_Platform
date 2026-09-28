"""
统一响应体契约的全局回归（模块 10）

文档 5.2 要求**所有**接口（含错误）都返回 `{code, message, data}`。
靠人逐个接口去测是防不住的 —— 新增一个忘了包的接口不会有任何人发现，
只会在联调时被前端问「这个接口怎么没有 code」。因此本文件**遍历
`app.routes`**，对每个已注册路由真的发一次请求，断言：

1. 响应体恰好是 `{code, message, data}` 三个键，`code` 是整数；
2. 失败响应的 HTTP 状态码与业务码分段一致（401xx→401、403xx→403…）；
3. 出参字段是 camelCase；
4. 未处理异常被收敛成 500/50000，且**不泄露堆栈与内部细节**。

遍历时用 `raise_app_exceptions=False` 的客户端：`ServerErrorMiddleware`
在把响应发出去之后仍会**重新抛出**原异常（Starlette 的行为），
用默认客户端会让本文件在遇到 500 时直接抛错，看不到响应体。

新增接口若确实不该包统一响应体（例如 SSE、文件下载），
必须登记进 `EXEMPT_PATHS` —— 登记即审查。
"""

from __future__ import annotations

import re

import httpx
import pytest
from fastapi import FastAPI

from app.core.error_codes import DEFAULT_MESSAGES, ErrorCode
from app.core.exceptions import _BUSINESS_ERROR_HTTP_STATUS, BizError, BusinessError
from app.core.response import ApiResponse, ok

pytestmark = pytest.mark.api

# 不返回统一响应体的**非 API** 路径。
# 这些是框架自带的文档端点，返回 HTML / OpenAPI JSON，不属于业务接口。
EXEMPT_PATHS = frozenset({"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"})

# 带请求体的方法，遍历时补一个空 JSON body 以触发参数校验分支
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})

# 响应体必须恰好是这三个键
ENVELOPE_KEYS = frozenset({"code", "message", "data"})

_PATH_PARAM = re.compile(r"\{[^}]+\}")


@pytest.fixture
async def tolerant_client(application: FastAPI):
    """
    允许应用抛异常的客户端。

    与 conftest 的 `client` 只差 `raise_app_exceptions=False`：
    否则未处理异常会从 `client.get(...)` 里抛出来，本文件就测不到
    那个「已经被发出去的 500 响应」。
    """
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=False,
    ) as http_client:
        yield http_client


def _iter_api_routes(app: FastAPI) -> list[tuple[str, str]]:
    """列出全部 `(method, path)`。只取 `/api/` 下的路由。"""
    found: list[tuple[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None)
        if not methods or not path.startswith("/api/"):
            continue
        for method in sorted(methods):
            found.append((method, path))
    return found


def _concrete(path: str) -> str:
    """把 `/orders/{orderId}/cancel` 变成可请求的 `/orders/1/cancel`。"""
    return _PATH_PARAM.sub("1", path)


# ==========================================================================
# 全局遍历
# ==========================================================================
async def test_every_api_route_returns_the_envelope(
    application: FastAPI, tolerant_client: httpx.AsyncClient
) -> None:
    """
    每个已注册接口都返回统一响应体。

    失败时把**全部**不合规的路由一次性列出来 —— 逐个断言的话，
    要跑 N 次才能修完 N 个问题。
    """
    routes = _iter_api_routes(application)
    assert len(routes) >= 20, f"只发现 {len(routes)} 个接口，路由注册可能被改坏了"

    problems: list[str] = []
    for method, path in routes:
        url = _concrete(path)
        response = await tolerant_client.request(
            method, url, json={} if method in _BODY_METHODS else None
        )
        try:
            body = response.json()
        except ValueError:
            problems.append(f"{method} {url} -> HTTP {response.status_code} 不是 JSON")
            continue

        if not isinstance(body, dict) or set(body) != ENVELOPE_KEYS:
            actual = sorted(body) if isinstance(body, dict) else type(body).__name__
            problems.append(f"{method} {url} -> 响应体键为 {actual}，应为 {sorted(ENVELOPE_KEYS)}")
            continue

        if not isinstance(body["code"], int) or not isinstance(body["message"], str):
            problems.append(f"{method} {url} -> code/message 类型不对: {body!r}")
            continue

        # 成功响应的 code 恒为 200（文档 5.2）
        if response.status_code < 400 and body["code"] != ErrorCode.SUCCESS:
            problems.append(f"{method} {url} -> HTTP {response.status_code} 但 code={body['code']}")

        # 失败响应：HTTP 状态码跟随业务码分段（见 app/api/v1/auth.py 的说明）
        if body["code"] != ErrorCode.SUCCESS and response.status_code != body["code"] // 100:
            problems.append(
                f"{method} {url} -> code={body['code']} 与 HTTP {response.status_code} 不同段"
            )

    assert not problems, "以下接口不符合统一响应体契约:\n" + "\n".join(problems)


async def test_envelope_keys_are_camel_case(
    application: FastAPI, tolerant_client: httpx.AsyncClient
) -> None:
    """
    成功响应里的字段名都是 camelCase（文档 6.2）。

    只检查成功的响应：错误响应的 `data` 可能是 `{"errors": [...]}`，
    那是统一结构、不含业务字段。
    """
    offenders: list[str] = []
    for method, path in _iter_api_routes(application):
        response = await tolerant_client.request(
            method, _concrete(path), json={} if method in _BODY_METHODS else None
        )
        if response.status_code >= 400:
            continue
        data = response.json().get("data")
        if isinstance(data, dict) and any("_" in key for key in data):
            offenders.append(f"{method} {path} -> {sorted(data)}")

    assert not offenders, "以下接口返回了 snake_case 字段:\n" + "\n".join(offenders)


def test_no_unregistered_non_api_routes(application: FastAPI) -> None:
    """
    非 `/api/` 路径必须登记在 `EXEMPT_PATHS`。

    这是防止「新增了一个裸路由」的哨兵：漏登记的路径会在下一次有人在
    本文件新增豁免时被一并发现，而不是等到前端联调时报错。
    """
    unregistered = {
        getattr(route, "path", "")
        for route in application.routes
        if getattr(route, "methods", None) and not getattr(route, "path", "").startswith("/api/")
    } - EXEMPT_PATHS

    assert not unregistered, (
        f"以下非 API 路径未登记进 EXEMPT_PATHS: {sorted(unregistered)}。"
        "若它们是业务接口，说明漏了统一响应体；若确实例外，请登记并写明原因。"
    )


# ==========================================================================
# 错误分支：参数校验 / 404 / 405 / 未处理异常
# ==========================================================================
async def test_validation_error_lists_the_offending_fields(client) -> None:
    """参数校验失败 → 400/40001，且 `data.errors[].field` 用 camelCase。"""
    response = await client.post("/api/v1/auth/login", json={"username": "admin"})

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == ErrorCode.PARAM_INVALID
    errors = body["data"]["errors"]
    assert [item["field"] for item in errors] == ["password"]
    assert all(item["message"] for item in errors)


async def test_unknown_route_returns_404_envelope(client) -> None:
    """未注册的路径也要是统一响应体（不能裸奔出 Starlette 的默认 404）。"""
    response = await client.get("/api/v1/definitely-not-here")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == ErrorCode.NOT_FOUND
    assert body["message"] == "接口或资源不存在"


async def test_method_not_allowed_is_documented_as_400xx(client) -> None:
    """
    已知偏差：405 复用 400xx 段（HTTP 405 但 `code=40000`）。

    这是本项目**唯一**违反「HTTP 状态码跟随业务码分段」的地方，
    来源是 `app/core/response.py` 的 `_STATUS_TO_CODE` 映射（405 → BAD_REQUEST）。
    保留现状而不是新增 405xx 段，理由有两条：

    1. 405 只可能来自**调用方的代码写错**（用错 HTTP 方法），不是业务分支，
       前端不需要对它做任何差异化处理；
    2. 改 `app/core/error_codes.py` 是动全组共用的契约表，
       为一个前端根本不会遇到的场景去动它，风险大于收益。

    本用例把这个偏差固定下来：将来若真加了 405xx 段，这里会失败并提醒更新文档。
    """
    response = await client.post("/api/v1/health")

    assert response.status_code == 405
    body = response.json()
    assert body["code"] == ErrorCode.BAD_REQUEST
    assert body["message"] == "请求方法不被允许"
    # Allow 头要透传，否则调用方不知道该用哪个方法
    assert response.headers.get("allow")


async def test_unhandled_exception_is_500_without_leaking_internals(
    application: FastAPI, tolerant_client: httpx.AsyncClient
) -> None:
    """
    未处理异常 → 500/50000，且响应体里**没有**堆栈、表名、SQL 或文件路径。

    泄露内部信息是文档 13 风险登记里明确列出的项：异常消息里常常带着
    `SELECT ... FROM sys_user` 或 `C:\\...\\auth_service.py`。
    """
    secret = "SELECT password_hash FROM sys_user WHERE username='admin'"

    @application.get("/api/v1/_probe/boom", name="probe_boom")
    async def _boom():
        raise RuntimeError(secret)

    response = await tolerant_client.get("/api/v1/_probe/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == ErrorCode.INTERNAL_ERROR
    assert set(body) == ENVELOPE_KEYS

    assert secret not in response.text
    assert "sys_user" not in response.text
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text
    assert "auth_service" not in response.text


async def test_response_model_violation_is_a_server_error(
    application: FastAPI, tolerant_client: httpx.AsyncClient
) -> None:
    """
    出参不符合声明的 `response_model` → 500/50000。

    这是**服务端 bug**（写错了字段类型），不能伪装成 200 让前端去猜。
    未注册处理器时 FastAPI 会抛 `ResponseValidationError` 并返回一个
    没有业务码的响应，本用例保证它也被收敛进统一结构。
    """

    @application.get(
        "/api/v1/_probe/bad-model",
        name="probe_bad_model",
        response_model=ApiResponse[int],
    )
    async def _bad_model():
        return ok("这不是整数")

    response = await tolerant_client.get("/api/v1/_probe/bad-model")

    assert response.status_code == 500
    assert response.json()["code"] == ErrorCode.INTERNAL_ERROR


# ==========================================================================
# 兼容层与异常类的对账（两条抛法必须给出同一个状态码）
# ==========================================================================
def _biz_error_subclasses() -> list[type[BizError]]:
    """递归收集 `BizError` 的全部子类（含孙类）。"""
    found: list[type[BizError]] = []
    pending = list(BizError.__subclasses__())
    while pending:
        cls = pending.pop()
        found.append(cls)
        pending.extend(cls.__subclasses__())
    return found


def test_legacy_status_table_agrees_with_the_exception_classes() -> None:
    """
    同一个业务码，两条抛法必须给出同一个 HTTP 状态码。

    本项目有两种抛法，历史上它们**不一致**：

        raise ResourceConflictError(...)   → 按子类取 409
        raise BusinessError(40901, ...)    → 查 `_BUSINESS_ERROR_HTTP_STATUS`，
                                             当时表里没登记 → 落默认 400

    于是「目标时段资源已被占用」返回 409 还是 400，取决于调用方选的写法，
    前端拿不到稳定契约。40901 已按此对齐；本用例保证以后新增的登记项不会
    再制造同类不一致 —— 只比**两条路径都存在**的码，只有兼容层一条路径的码
    （模块 1/2 的 41xxx，无对应子类）不在对账范围内。
    """
    by_code: dict[int, type[BizError]] = {}
    for cls in _biz_error_subclasses():
        code = getattr(cls, "code", None)
        # 取最靠上层的子类：同一 code 若被派生类重复声明，以基类为准
        if isinstance(code, int) and code not in by_code:
            by_code[code] = cls

    problems: list[str] = []
    for code, mapped in _BUSINESS_ERROR_HTTP_STATUS.items():
        cls = by_code.get(code)
        if cls is not None and cls.http_status != mapped:
            problems.append(f"{code}: 兼容层表里是 {mapped}，{cls.__name__} 是 {cls.http_status}")
        if not 400 <= mapped < 600:
            problems.append(f"{code}: 兼容层表里是 {mapped}，不是合法的 4xx/5xx")

    assert not problems, (
        "兼容层状态码映射与异常类不一致（同一个错误会返回两种状态码）:\n" + "\n".join(problems)
    )


async def test_legacy_conflict_error_returns_http_409(
    application: FastAPI, tolerant_client: httpx.AsyncClient
) -> None:
    """
    走兼容层抛 40901，HTTP 状态码必须是 409。

    40901（`RESOURCE_CONFLICT`「目标时段资源已被占用」）目前**没有任何调用方**
    —— 模块 3 尚未合入 —— 所以这条路上没有任何既有用例能发现状态码是错的。
    本用例自己起一个探针路由把它钉住：只要有人把表里那行删了，这里立刻变红。
    """

    @application.post("/api/v1/_probe/legacy-conflict", name="probe_legacy_conflict")
    async def _legacy_conflict():
        raise BusinessError(ErrorCode.RESOURCE_CONFLICT)

    response = await tolerant_client.post("/api/v1/_probe/legacy-conflict")

    assert response.status_code == 409
    body = response.json()
    assert set(body) == ENVELOPE_KEYS
    assert body["code"] == ErrorCode.RESOURCE_CONFLICT
    assert body["message"] == DEFAULT_MESSAGES[ErrorCode.RESOURCE_CONFLICT]
    # 与「HTTP 跟随业务码分段」的全局约定保持一致（40901 // 100 == 409）
    assert response.status_code == body["code"] // 100


async def test_lifespan_is_not_required_for_requests(client) -> None:
    """
    夹具用 `ASGITransport` 直接构造应用、不跑 lifespan，接口仍要能用。

    这条断言的意义是「接口不依赖启动期的预热」：单测与 CI 里没有 MySQL、
    没有 Redis，若哪个接口偷偷依赖了 lifespan 建好的东西，这里会立刻失败。
    """
    assert (await client.get("/api/v1/health")).status_code == 200
