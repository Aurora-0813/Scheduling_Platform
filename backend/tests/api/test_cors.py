"""
CORS 行为回归（模块 10）

CORS 配置错了不会让后端测试变红，只会让**浏览器**里的前端报一个与真实原因
完全无关的错误，排查成本极高。因此把每一条配置都固化成断言：

| 断言                        | 防的是什么                                        |
| --------------------------- | ------------------------------------------------- |
| 白名单来源有 Allow-Origin    | 前端第一个请求就跨域失败                          |
| 非白名单来源没有 Allow-Origin| 来源被放开成 `*`（等于允许任意站点携带用户令牌）    |
| 错误响应也带 CORS 头         | 401 被浏览器报成跨域错误，前端往错的方向排查       |
| 不返回 Allow-Credentials     | 有人顺手打开凭据模式（本项目不用 Cookie 鉴权）     |
| 暴露 X-Request-Id            | 前端拿不到报错时该贴给后端的那个 ID                |
| OPTIONS 预检不要求鉴权        | 预检不带 Authorization 头，加了鉴权会让预检永远 401|

最后一条是纯粹的现实约束：**预检请求由浏览器发出，不会带任何业务头**。
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import settings

pytestmark = pytest.mark.api

ALLOW_ORIGIN = "access-control-allow-origin"
ALLOW_CREDENTIALS = "access-control-allow-credentials"
ALLOW_METHODS = "access-control-allow-methods"
ALLOW_HEADERS = "access-control-allow-headers"
MAX_AGE = "access-control-max-age"
EXPOSE_HEADERS = "access-control-expose-headers"

UNLISTED_ORIGIN = "http://evil.example.com"


@pytest.fixture
def allowed_origin() -> str:
    """配置里的第一个允许来源（不写死，避免改了 CORS_ORIGINS 就假绿）。"""
    origins = settings.cors_origin_list
    assert origins, "CORS_ORIGINS 为空，前端将完全无法跨域访问"
    return origins[0]


@pytest.fixture
async def tolerant_client(application: FastAPI):
    """允许应用抛异常的客户端，用于观察未处理异常路径的响应头。"""
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", follow_redirects=False
    ) as http_client:
        yield http_client


def _preflight_headers(origin: str) -> dict[str, str]:
    return {
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,authorization",
    }


# ==========================================================================
# 预检（OPTIONS）
# ==========================================================================
async def test_preflight_from_allowed_origin_succeeds(client, allowed_origin: str) -> None:
    """预检必须 200 且回显来源、方法与请求头。"""
    response = await client.options(
        "/api/v1/auth/login", headers=_preflight_headers(allowed_origin)
    )

    assert response.status_code == 200
    assert response.headers[ALLOW_ORIGIN] == allowed_origin
    assert "POST" in response.headers[ALLOW_METHODS]
    # allow_headers=["*"] 时 Starlette 原样回显浏览器请求的头
    assert "authorization" in response.headers[ALLOW_HEADERS].lower()


async def test_preflight_result_is_cached(client, allowed_origin: str) -> None:
    """`max_age` 要设：否则前端每个请求前都多一次 OPTIONS，请求量翻倍。"""
    response = await client.options(
        "/api/v1/auth/login", headers=_preflight_headers(allowed_origin)
    )

    assert response.headers[MAX_AGE] == "600"


async def test_preflight_from_unlisted_origin_is_rejected(client) -> None:
    """非白名单来源的预检直接 400，且**不带** Allow-Origin。"""
    response = await client.options("/api/v1/health", headers=_preflight_headers(UNLISTED_ORIGIN))

    assert response.status_code == 400
    assert ALLOW_ORIGIN not in response.headers


async def test_preflight_does_not_require_authentication(client, allowed_origin: str) -> None:
    """
    预检请求不带 `Authorization` 头（浏览器不会带业务头）。

    若哪天给路由加了「全局鉴权中间件」，预检会先返回 401，
    浏览器就不再发真正的请求 —— 症状是「所有跨域请求都失败」。
    """
    response = await client.options("/api/v1/auth/info", headers=_preflight_headers(allowed_origin))

    assert response.status_code == 200
    assert response.headers[ALLOW_ORIGIN] == allowed_origin


# ==========================================================================
# 实际请求
# ==========================================================================
async def test_actual_request_carries_allow_origin(client, allowed_origin: str) -> None:
    response = await client.get("/api/v1/health", headers={"Origin": allowed_origin})

    assert response.status_code == 200
    assert response.headers[ALLOW_ORIGIN] == allowed_origin


async def test_unlisted_origin_gets_no_cors_headers(client) -> None:
    """
    非白名单来源只是**拿不到** CORS 头，请求本身仍被正常处理。

    这一条是在守「来源不能是 `*`」：允许所有来源意味着任何网站都能
    在用户浏览器里调用本服务并读取响应。
    """
    response = await client.get("/api/v1/health", headers={"Origin": UNLISTED_ORIGIN})

    assert response.status_code == 200
    assert ALLOW_ORIGIN not in response.headers


async def test_error_response_still_carries_cors_headers(client, allowed_origin: str) -> None:
    """
    **CORS 中间件放在最外层的原因**（见 `app/main.py`）。

    4xx 响应由内层的异常处理器生成。若 CORS 不在最外层，这些响应就没有
    `Access-Control-Allow-Origin`，浏览器会把「401 未登录」显示成
    「跨域被拒绝」，前端会去查代理配置而不是去续期令牌。
    """
    response = await client.get("/api/v1/auth/info", headers={"Origin": allowed_origin})

    assert response.status_code == 401
    assert response.json()["code"] == 40101
    assert response.headers[ALLOW_ORIGIN] == allowed_origin


async def test_credentials_mode_is_disabled(client, allowed_origin: str) -> None:
    """
    鉴权走 `Authorization` 头，不用 Cookie，因此不开凭据模式。

    凭据模式一旦打开，浏览器就会携带 Cookie 并在 `Access-Control-Allow-Origin`
    上要求**精确来源**（不能是 `*`）。本项目的来源已是白名单，所以将来若要
    切到 Cookie 会话只需改 `main.py` 一处；当前保持关闭可以少一类 CSRF 风险。
    """
    response = await client.get("/api/v1/health", headers={"Origin": allowed_origin})

    assert ALLOW_CREDENTIALS not in response.headers


async def test_request_id_is_exposed_to_js(client, allowed_origin: str) -> None:
    """
    `X-Request-Id` 必须能被前端 JS 读到。

    默认只有少数「安全头」对 JS 可见，不显式暴露的话前端拿不到这个 ID，
    报错时就没法把它贴给后端做日志关联。
    """
    response = await client.get("/api/v1/health", headers={"Origin": allowed_origin})

    assert response.headers.get("x-request-id")
    assert "X-Request-Id" in response.headers[EXPOSE_HEADERS]


# ==========================================================================
# 已知边界：未处理异常
# ==========================================================================
async def test_unhandled_exception_response_has_no_cors_headers(
    application: FastAPI, tolerant_client: httpx.AsyncClient, allowed_origin: str
) -> None:
    """
    已知边界：**未处理异常**的 500 响应没有 CORS 头。

    原因是框架结构，不是配置疏漏：`Exception` 处理器由 Starlette 的
    `ServerErrorMiddleware` 调用，而它位于全部业务中间件**之外**，
    因此它生成的响应不会再回穿 CORS 中间件（同理也没有 `X-Request-Id`）。

    本用例把现状固定下来，理由如下：
    - 要让这类响应带上 CORS 头，只能在自己的中间件里再造一份 500 响应体，
      那样「统一响应体」就有两个来源，反而更容易不一致；
    - 走到这里说明是**未预料的**服务端缺陷（响应体仍是规范的信封，
      日志里有完整堆栈），此时缺一个 CORS 头是次要问题。

    将来若 Starlette 改了实现、或我们调整了中间件栈，这条用例会失败 ——
    那时请同步更新 `app/main.py` 的模块 docstring 与 `docs/api.md`。
    """

    @application.get("/api/v1/_probe/cors-boom", name="probe_cors_boom")
    async def _boom():
        raise RuntimeError("模拟未处理异常")

    response = await tolerant_client.get(
        "/api/v1/_probe/cors-boom", headers={"Origin": allowed_origin}
    )

    assert response.status_code == 500
    assert response.json()["code"] == 50000
    assert ALLOW_ORIGIN not in response.headers
    assert "x-request-id" not in response.headers


async def test_500_generated_inside_the_app_still_has_cors_headers(
    application: FastAPI, tolerant_client: httpx.AsyncClient, allowed_origin: str
) -> None:
    """
    对照组：只要响应是**在应用内部**生成的（路由或异常处理器），就带 CORS 头。

    与上一条的区别就是「谁生成了响应」。两条用例合起来，把
    「CORS 在最外层的收益边界」讲清楚了。
    """

    @application.get("/api/v1/_probe/inner-500", name="probe_inner_500")
    async def _inner_500():
        from fastapi.responses import JSONResponse

        from app.core.error_codes import ErrorCode
        from app.core.response import error_payload

        return JSONResponse(status_code=500, content=error_payload(ErrorCode.INTERNAL_ERROR))

    response = await tolerant_client.get(
        "/api/v1/_probe/inner-500", headers={"Origin": allowed_origin}
    )

    assert response.status_code == 500
    assert response.headers[ALLOW_ORIGIN] == allowed_origin
