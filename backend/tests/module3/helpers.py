"""测试公共辅助：身份常量、令牌构造与时间构造（§5.1 时间统一 `YYYY-MM-DD HH:mm:ss`）。

身份怎么来的
------------
`§5.1` / `docs/api.md` §1.6：身份**一律**从 JWT 解析。本模块曾用一版读
`X-User-Id` 请求头的 mock 兜底（`app/core/deps.py`），已在重组时删除 ——
那个头不在契约里，改一个头就能变成任何人。

现在测试与生产走同一条路：用 `app.core.security.create_token` 现签一个真的
accessToken，放进 `Authorization: Bearer`。签出来的令牌由团队的
`app.api.deps.get_current_user` 真解析、真查库，因此「令牌无效 / 用户不存在 /
账号被禁用 / 未分配角色」这些分支在测试里也真实存在，不是被 mock 掉的。
"""
from datetime import datetime, timedelta

from app.core.security import TokenType, create_token

# 演示阶段的两个用户（在 tests/module3/conftest.py 里连同角色一起灌进测试库）
MOCK_USER_ID = 1
# 另一用户，用于越权类用例
OTHER_USER_ID = 2

#: 两个用户共用的角色名。必须在 `sys_role` 里有对应行 ——
#: `get_current_user` 在角色为空时抛 `RoleMissingError`（403/40302），
#: 只灌 `sys_user` 不灌角色的话，所有用例会一起变成 403。
ROLE_NAME = "user"

#: 令牌有效期。给足余量，避免用例跑到一半过期（accessToken 默认 30 分钟）。
_TOKEN_TTL = timedelta(hours=1)

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def access_token(user_id: int = MOCK_USER_ID, role: str = ROLE_NAME) -> str:
    """给指定用户签一个真实的 accessToken（团队 `create_token`）。"""
    token, _ = create_token(user_id, role, TokenType.ACCESS, _TOKEN_TTL)
    return token


def auth_headers(user_id: int = MOCK_USER_ID, role: str = ROLE_NAME) -> dict[str, str]:
    """构造 `Authorization` 头。切换身份就靠它，不要再用请求头伪造。"""
    return {"Authorization": f"Bearer {access_token(user_id, role)}"}


def time_dt(days: int = 1, hour: int = 9, minute: int = 0) -> datetime:
    """构造相对当前时间的整点 datetime（默认明天 09:00）。"""
    return (datetime.now() + timedelta(days=days)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )


def time_str(days: int = 1, hour: int = 9, minute: int = 0) -> str:
    """构造接口用的时间字符串（默认明天 09:00）。"""
    return time_dt(days, hour, minute).strftime(TIME_FORMAT)
