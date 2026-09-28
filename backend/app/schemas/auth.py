"""
认证与用户信息 schema（模块 9）

契约来源：项目文档 5.3 模块 9、文档 5.2 统一响应体。
所有字段名在 API 上是 camelCase（`CamelModel` 负责转换）：
`accessToken` / `refreshToken` / `avatar` / `permissions`。

为什么 LoginOut 只有 accessToken / refreshToken / role
------------------------------------------------------
文档 5.3 只约定了这三个字段。刻意**不加** `expiresIn` / `tokenType` 之类的
便利字段：契约是前端（模块 8）与小程序已经按此写好的东西，加字段虽然向后兼容，
但会让「文档即契约」这条约定失效 —— 下次别人也会顺手加。前端需要提前刷新时，
可以本地解析 accessToken 的 `exp`（JWT 标准字段，无需额外接口）。
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints

from app.core.camel import CamelModel
from app.core.security import PASSWORD_MAX_LENGTH

__all__ = [
    "LoginIn",
    "TokenPairOut",
    "LoginOut",
    "RefreshIn",
    "LogoutIn",
    "UserInfoOut",
]

# 用户名：允许首尾空格但不允许空串。这里显式 strip，
# 因为 CamelModel 刻意没有全局开启 str_strip_whitespace（会把密码也 strip，
# 见 app/core/camel.py 的说明）。
UsernameField = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]

# 密码：上限按 bcrypt 的有效长度（72）限制。
#
# ⚠️ 注意单位不一致：Pydantic 的 max_length 计的是**字符**，
# 而 bcrypt 的限制是 **72 字节**。72 个汉字是 216 字节，仍会超出。
# 真正的字节级校验在 app/core/security.py 的 `hash_password()` 里，
# 那条路径是唯一写入密码的入口，因此不会出现「注册时被静默截断」。
# 登录侧不设字节校验：登录只做校验不写库，截断行为与历史数据一致。
#
# 下限刻意只要求非空，不强制 6 位以上：登录接口必须能接受账号已存在的任意
# 密码。密码强度策略属于「创建用户」接口的职责（模块 9 的后台管理接口，
# 不在本轮范围内），放在登录侧只会让历史账号无法登录。
PasswordField = Annotated[
    str,
    StringConstraints(min_length=1, max_length=PASSWORD_MAX_LENGTH),
]


class LoginIn(CamelModel):
    """登录入参。"""

    username: UsernameField
    password: PasswordField


class TokenPairOut(CamelModel):
    """令牌对。登录与续期共用的出参结构。"""

    access_token: str
    refresh_token: str


class LoginOut(TokenPairOut):
    """登录出参（文档 5.3）。"""

    role: str | None = None


class RefreshIn(CamelModel):
    """
    续期入参。

    只接受 refreshToken，不接受 accessToken —— 续期的触发时机正是
    accessToken 已过期，要求它反而会让续期永远不可用。
    """

    refresh_token: Annotated[str, StringConstraints(min_length=1)]


class LogoutIn(CamelModel):
    """
    登出入参。

    `refreshToken` 为**可选**，这是刻意的设计：

    - 传了 → 只吊销这一个会话（该设备登出，其它设备不受影响）；
    - 没传 → 吊销该用户的**全部**会话（`revoke_all`）。

    为什么不给一个「什么都不做也返回成功」的默认：那等于假登出 ——
    refreshToken 还在白名单里，能继续换出新的 accessToken。
    文档 5.3 没有为登出约定请求体，因此这两种调用方式都必须可用。
    """

    refresh_token: str | None = Field(default=None, min_length=1)


class UserInfoOut(CamelModel):
    """当前用户信息（文档 5.3 的 `GET /auth/info`）。

    `role` 为 `None` 时表示账号未分配角色 —— 该状态在登录时已被拒绝
    （见 app/api/deps.py），因此正常流程下不会出现。
    """

    id: int
    username: str
    role: str | None = None
    avatar: str | None = None
    permissions: list[str] = Field(default_factory=list)
