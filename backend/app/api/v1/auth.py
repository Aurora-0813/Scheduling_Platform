"""
认证接口（模块 9）

契约来源：项目文档 5.3 模块 9（login / info）。
`refresh` 与 `logout` 文档未约定，按实施方案补齐（见各函数说明）。

所有接口的出参都包在统一响应体 `ApiResponse` 里（文档 5.2）。

关于客户端 IP
-------------
`_client_ip()` 优先读 `X-Forwarded-For` 的第一段，其次读 `request.client.host`。
它**只用于风控日志**，不参与任何鉴权判定 —— 该头可以由客户端伪造，
拿它做访问控制等于没有访问控制。生产环境应在 Nginx 层覆盖该头
（`proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for`），
否则拿到的是客户端的自报值。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_token_store
from app.core.database import get_db
from app.core.response import ApiResponse, ok
from app.core.token_store import TokenStore
from app.schemas.auth import LoginIn, LoginOut, LogoutIn, RefreshIn, TokenPairOut, UserInfoOut
from app.schemas.common import ErrorResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["认证与权限（模块 9）"])

# 认证接口通用的错误响应声明，让 /docs 里能看到统一错误信封的实际形状。
#
# HTTP 状态码的分配规则：**跟随业务码分段**（见 app/core/exceptions.py 每类
# 的 http_status 与 app/core/error_codes.py 的分段表）。因此：
# - 401xx 段（凭据无效、令牌各类问题、**账号被禁用**）→ HTTP 401
# - 403xx 段（已认证但缺权限、未分配角色、跨用户操作）→ HTTP 403
# 前端请按响应体里的 `code` 分支，不要按 HTTP 状态码分支 —— 401 底下有
# 7 个含义完全不同的业务码，处理方式（续期 / 重新登录 / 联系管理员）各不相同。
_AUTH_ERROR_RESPONSES: dict[int | str, dict] = {
    status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse, "description": "参数校验失败（40001）"},
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": (
            "认证失败。可能的 code：40100 账号已不存在、40101 缺少令牌、"
            "40102 令牌无效、40103 令牌已过期、40104 令牌类型不对、"
            "40105 已被强制下线、40106 刷新令牌不可用、"
            "**40107 用户名或密码错误**、**40108 账号已禁用**、40109 账号被临时锁定"
        ),
    },
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": (
            "权限不足。可能的 code：40300 通用无权限（含跨用户吊销会话）、"
            "40301 缺少所需权限、40302 账号未分配角色"
        ),
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponse,
        "description": "Redis 不可用（50301）。仅续期与登出会返回，这两个接口刻意不做降级",
    },
}


def _client_ip(request: Request) -> str | None:
    """取客户端 IP，仅供风控日志使用（可被伪造，不得用于鉴权）。"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else None


@router.post(
    "/login",
    response_model=ApiResponse[LoginOut],
    summary="登录",
    description=(
        "校验账号密码并签发令牌对。\n\n"
        "- `accessToken` 有效期 30 分钟，用于访问业务接口；\n"
        "- `refreshToken` 有效期 7 天，只用于 `POST /auth/refresh`；\n"
        "- 账号禁用返回 40108、未分配角色返回 40302，两者都在**密码校验通过之后**才可能返回。"
    ),
    responses=_AUTH_ERROR_RESPONSES,
)
async def login(
    payload: LoginIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    token_store: TokenStore = Depends(get_token_store),
) -> ApiResponse[LoginOut]:
    """登录。对应文档 5.3 的 `POST /api/v1/auth/login`。"""
    data = await auth_service.login(
        db,
        token_store,
        username=payload.username,
        password=payload.password,
        client_ip=_client_ip(request),
    )
    return ok(data, message="登录成功")


@router.get(
    "/info",
    response_model=ApiResponse[UserInfoOut],
    summary="获取当前用户信息",
    description=(
        "返回当前登录用户的信息与权限清单。\n\n"
        "`permissions` 是该角色在 `sys_role.permissions` 里的权限码数组；"
        '若为 `["*"]` 表示拥有全部权限。前端据此渲染菜单。'
    ),
    responses=_AUTH_ERROR_RESPONSES,
)
async def info(current: CurrentUser = Depends(get_current_user)) -> ApiResponse[UserInfoOut]:
    """
    获取当前用户信息。对应文档 5.3 的 `GET /api/v1/auth/info`。

    直接从 `CurrentUser` 快照构造，不重新查库 —— `get_current_user` 刚刚
    读过同一行，再查一次是多余的往返。
    """
    data = UserInfoOut(
        id=current.id,
        username=current.username,
        role=current.role,
        avatar=current.avatar,
        permissions=sorted(current.permissions),
    )
    return ok(data)


@router.post(
    "/refresh",
    response_model=ApiResponse[TokenPairOut],
    summary="续期（轮换令牌）",
    description=(
        "用 `refreshToken` 换取新的令牌对。\n\n"
        "**前端必须用单例 Promise 去重刷新**（同一时刻只发一个刷新请求）：\n\n"
        "1. 旧 `refreshToken` 换取成功后立即失效（轮换）；\n"
        "2. 旧令牌在 **60 秒宽限期**内仍可再换一次，之后的尝试一律拒绝；\n"
        "3. 因此并发的重复刷新最多只有一个能拿到新令牌，其余请求会失败。\n\n"
        "令牌版本不符（账号已被强制下线）返回 40105；"
        "`refreshToken` 不在白名单（已登出/已轮换/重放）返回 40106；"
        "Redis 不可用返回 50301（此接口**不做降级**，因为没有白名单就无法判断令牌是否仍然有效）。"
    ),
    responses=_AUTH_ERROR_RESPONSES,
)
async def refresh(
    payload: RefreshIn,
    db: AsyncSession = Depends(get_db),
    token_store: TokenStore = Depends(get_token_store),
) -> ApiResponse[TokenPairOut]:
    """续期。不需要 Authorization 头 —— 触发时机正是 accessToken 已过期。"""
    data = await auth_service.refresh(db, token_store, refresh_token=payload.refresh_token)
    return ok(data, message="续期成功")


@router.post(
    "/logout",
    response_model=ApiResponse[None],
    summary="登出",
    description=(
        "吊销 refreshToken。\n\n"
        "- 请求体传 `refreshToken` → 只吊销该会话（其它设备不受影响）；\n"
        "- 不传（或令牌已过期/无法解析）→ 吊销该用户的**全部**会话；\n"
        "- 传了**别人的** refreshToken → 40300（防止跨用户踢人）。\n\n"
        "⚠️ 已知限制：`accessToken` 是无状态校验的，登出后它仍能用到自然过期"
        "（最多 30 分钟）。需要立即失效时请把 `JWT_EXPIRE_MINUTES` 调小。"
    ),
    responses=_AUTH_ERROR_RESPONSES,
)
async def logout(
    current: CurrentUser = Depends(get_current_user),
    payload: LogoutIn | None = None,
    token_store: TokenStore = Depends(get_token_store),
) -> ApiResponse[None]:
    """
    登出。

    请求体整体可选（`LogoutIn | None`），因此前端既可以不带 body 调用，
    也可以只带 `refreshToken`。文档 5.3 没有约定请求体，两种方式都要能用。
    """
    await auth_service.logout(
        token_store,
        user_id=current.id,
        refresh_token=payload.refresh_token if payload else None,
    )
    return ok(None, message="已登出")
