"""
FastAPI 依赖注入：认证与鉴权（模块 9）

分层约定
--------
- `get_db` / `get_token_store` / `get_redis` 是**资源类**依赖；
- `get_current_user` 是**认证**依赖（你是谁）；
- `require_permission` / `require_role` 是**授权**依赖（你能干什么）。

使用方式：

    @router.get("/orders", dependencies=[Depends(require_permission(Permission.ORDER_VIEW))])
    async def list_orders(...): ...

    @router.post("/orders")
    async def create_order(current: CurrentUser = Depends(get_current_user), ...): ...

accessToken 为什么不查 Redis
----------------------------
`get_current_user` 只做三件事：验签名/过期、查库、判权限。**不查 Redis 版本号。**
这样可以保证 Redis 挂掉时，已登录的用户手里的 accessToken 仍能访问业务接口 ——
否则 Redis 单点故障会扩大成全站不可用（决策 7）。

代价：`revoke_all()`（登出 / 强制下线）后，已签发的 accessToken 最多还能用
`JWT_EXPIRE_MINUTES`（默认 30 分钟）。这是 JWT 的固有取舍，
详见 app/services/auth_service.py 的「强制下线的时间窗」。

权限以数据库为准
----------------
令牌里虽然有 `role` 声明，但**授权判定不使用它**：管理员改了某人的角色后，
旧令牌里的 role 会滞后到下次登录为止。这里每次请求都从数据库读角色
（`get_current_user` 本来就要查库判状态，顺带读角色不增加查询次数），
因此改角色**立即生效**。令牌里的 `role` 只用于日志与审计。
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langchain_core.language_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.chains.llm import build_llm
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import (
    ForbiddenError,
    PermissionDeniedError,
    RoleMissingError,
    TokenMissingError,
    UnauthorizedError,
    UserDisabledError,
)
from app.core.logging import get_logger
from app.core.permissions import ROLE_ADMIN, WILDCARD, has_permission
from app.core.security import TokenPayload, TokenType, decode_token
from app.core.token_store import TokenStore, build_token_store
from app.services import auth_service

__all__ = [
    "CurrentUser",
    "bearer_scheme",
    "get_token_store",
    "get_redis",
    "reset_token_store",
    "get_current_user",
    "require_role",
    "require_permission",
    "get_llm",
]

logger = get_logger(__name__)

# auto_error=False 是关键：默认的 True 在缺少 Authorization 头时会直接抛
# Starlette 的 HTTPException(403)，前端拿到 403 + code 40300，与「未登录」
# 的语义不符（应为 401 + 40101）。关掉自动报错后由我们抛 TokenMissingError，
# 错误码才准确。
bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="BearerToken",
    description="登录接口返回的 accessToken，格式：`Bearer <accessToken>`",
)


# ==========================================================================
# 资源类依赖
# ==========================================================================
_token_store: TokenStore | None = None


async def get_token_store() -> TokenStore:
    """
    refreshToken 白名单存储（进程内单例）。

    声明为 `async def`：`def` 依赖会被 FastAPI 丢到线程池执行，而这里只是读
    一个模块级变量，进线程池纯属浪费。

    测试里用 `app.dependency_overrides[get_token_store] = lambda: fake_store`
    替换即可，无需真实 Redis。
    """
    global _token_store
    if _token_store is None:
        _token_store = build_token_store()
    return _token_store


def reset_token_store() -> None:
    """
    丢弃当前单例，下次调用重新构造。

    用途：进程启动/关闭时刷新连接（main.py 的 lifespan），以及测试之间隔离
    状态 —— `REDIS_ENABLED` 或配置变了之后必须重置，否则会继续用旧实现。
    """
    global _token_store
    _token_store = None


async def get_redis() -> Any:
    """
    Redis 客户端；`REDIS_ENABLED=false` 时返回 None。

    仅供探针与埋点等可选功能使用。**认证逻辑不要直接用它** ——
    请通过 `get_token_store()`，那里有错误翻译与降级语义。
    """
    from app.core.redis import get_client

    return get_client()


# ==========================================================================
# 认证依赖
# ==========================================================================
@dataclass(frozen=True)
class CurrentUser:
    """
    已认证的当前用户。

    刻意只装**不可变的原始值**，不持有 ORM 实例：ORM 实例与会话绑定，
    请求结束后会话关闭，误传到后台任务里会抛 `DetachedInstanceError`；
    快照值则可以在任何地方安全使用。
    """

    id: int
    username: str
    role: str | None
    avatar: str | None
    permissions: frozenset[str] = field(default_factory=frozenset)
    token: TokenPayload | None = None

    def has_permission(self, required: str | None) -> bool:
        """是否拥有指定权限（`required` 为空表示无需权限）。"""
        return has_permission(self.permissions, required)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    """
    解析 Authorization 头并返回当前用户。

    失败分支与错误码（前端据此决定「去续期」还是「去登录页」）：

    | 情形                                   | 异常                  | code  |
    | -------------------------------------- | --------------------- | ----- |
    | 没有 Authorization 头 / 头里没有令牌     | `TokenMissingError`   | 40101 |
    | 签名错、结构损坏、缺字段                 | `TokenInvalidError`   | 40102 |
    | 已过期                                 | `TokenExpiredError`   | 40103 |
    | 拿 refreshToken 调业务接口              | `TokenTypeInvalidError`| 40104 |
    | 用户已被删除                            | `UnauthorizedError`   | 40100 |
    | 账号被禁用                              | `UserDisabledError`   | 40108 |
    | 账号未分配角色                          | `RoleMissingError`    | 40302 |

    前四种由 `decode_token` 抛出，本函数不重复处理。

    联调开关（AUTH_BYPASS）
    ----------------------
    模块 1/2 的接口在联调期需要「不带 Token 直接调」的便利，模块代码里
    也引用了 `AUTH_BYPASS` 这个开关。这里实现它，但加了三道保险：
        1. 仅 `APP_ENV=dev` 生效 —— 非 dev 环境由 config.py 的启动校验
           直接拒绝启动（见 Settings._check_security_settings）；
        2. 每次放行都打 WARNING 日志，避免「忘了关」却无人察觉；
        3. 放行的用户权限取通配符 `*`，语义上等同管理员。因为这是本地联调
           的临时身份，不该再叠加权限判定制造困惑。
    """
    if settings.AUTH_BYPASS:
        logger.warning(
            "⚠️ AUTH_BYPASS=true：已跳过 Token 校验，所有请求视为管理员。"
            "仅限本地联调，演示与部署前必须置为 false"
        )
        return CurrentUser(
            id=0,
            username="auth-bypass",
            role=ROLE_ADMIN,
            avatar=None,
            permissions=frozenset({WILDCARD}),
            token=None,
        )

    if credentials is None or not credentials.credentials:
        raise TokenMissingError()

    # expected_type=ACCESS 是必需的：不校验类型的话，拿到 refreshToken 的人
    # 就能直接调业务接口，绕过「accessToken 短有效期」这层设计。
    payload = decode_token(credentials.credentials, expected_type=TokenType.ACCESS)

    user = await auth_service.get_user_by_id(db, payload.user_id)
    if user is None:
        # 令牌签名有效但用户已不存在 —— 用它自己的错误码，
        # 与「伪造令牌」区分开，便于排查「账号被删了还拿着令牌」这类问题
        logger.info("认证失败：令牌对应的用户已不存在 userId=%s", payload.user_id)
        raise UnauthorizedError("账号已不存在，请重新登录")

    if user.status != auth_service.USER_STATUS_ACTIVE:
        raise UserDisabledError()

    role_name = auth_service.role_name_of(user)
    if role_name is None:
        raise RoleMissingError()

    return CurrentUser(
        id=user.id,
        username=user.username,
        role=role_name,
        avatar=user.avatar,
        permissions=frozenset(auth_service.permissions_of(user)),
        token=payload,
    )


# ==========================================================================
# 授权依赖
# ==========================================================================
def require_permission(required: str) -> Callable[..., Coroutine[Any, Any, CurrentUser]]:
    """
    生成一个「要求指定权限」的依赖。

    权限码格式 `模块:动作`（决策 4），常量见 app/core/permissions.py 的
    `Permission`。判定来源是 `sys_role.permissions`（决策 3）。

    用在 `dependencies=[...]` 里时返回值被丢弃；需要拿到当前用户时
    在函数签名里声明 `current: CurrentUser = Depends(require_permission(...))`，
    两者都支持。
    """

    async def _dependency(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not current.has_permission(required):
            # 日志里带 userId 与角色，便于回答「为什么他 403」；
            # 响应里带所需权限码，前端与联调时能直接定位（权限码不是机密）
            logger.info(
                "鉴权失败：缺少权限 required=%s userId=%s role=%s",
                required,
                current.id,
                current.role,
                extra={
                    "extra_fields": {
                        "required": required,
                        "userId": current.id,
                        "role": current.role,
                    }
                },
            )
            raise PermissionDeniedError(f"当前角色缺少所需权限：{required}")
        return current

    return _dependency


def require_role(*roles: str) -> Callable[..., Coroutine[Any, Any, CurrentUser]]:
    """
    生成一个「要求指定角色之一」的依赖。

    与 `require_permission` 的关系：**优先用权限**。权限判定来自数据库的
    `sys_role.permissions`，改权限不需要改代码；角色判定把角色名硬编码进
    代码，新增角色时要回来改。只有在语义上确实与角色绑定
    （例如「管理员专属」且不希望被权限配置绕过）时才用本函数。

    用法：`Depends(require_role(ROLE_ADMIN, ROLE_RESOURCE_ADMIN))`
    """
    allowed = frozenset(roles)

    async def _dependency(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not current.role or current.role not in allowed:
            logger.info(
                "鉴权失败：角色不符 allowed=%s userId=%s role=%s",
                sorted(allowed),
                current.id,
                current.role,
            )
            raise ForbiddenError("当前角色无权访问该接口")
        return current

    return _dependency


# ==========================================================================
# 文本 LLM 依赖（模块 7 的通知 / 抽取链）
# ==========================================================================
async def get_llm() -> BaseChatModel:
    """模块 7 注入用：文本 LLM（通知 / 抽取链）；视觉 LLM 见 `app/core/llm.py`。

    做成 FastAPI 依赖而不是在业务里直接 `build_llm()`，是为了让接口测试能用
    `app.dependency_overrides[get_llm]` 换成假模型，不真调外部 API
    （见 `tests/api/conftest.py` 与 `tests/api/test_notify_api.py`）。
    """
    return build_llm()
