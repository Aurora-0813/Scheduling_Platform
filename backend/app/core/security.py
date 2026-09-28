"""
密码哈希与 JWT 签发/解析

封装边界（重要）
----------------
`passlib` 只在本文件的 `hash_password` / `verify_password` 两个函数里出现。
passlib 1.7.4 发布于 2020 年、上游维护停滞，将来若换成 `argon2` 或直接用
`bcrypt` 库，改动范围就是这一个文件里的两个函数，不会波及 services 与 api。

为什么所有哈希操作都是 async
-----------------------------
bcrypt cost=12 单次约 200~300 毫秒，是纯 CPU 计算。若在协程里同步调用，
会阻塞整个事件循环 —— 登录高峰期所有请求（包括其它模块的）一起卡住。
因此统一用 `asyncio.to_thread` 丢到线程池执行。

JWT 时间戳的时区陷阱
--------------------
项目业务时间统一用本地 naive datetime（见 app/utils/time_utils.py），
但 JWT 的 `exp` / `iat` 按 RFC 7519 是 **Unix 时间戳（UTC）**。
PyJWT 编码 naive datetime 时会直接 `timegm(value.utctimetuple())`，
即把它当作 UTC —— 若传入本地时间，`exp` 会凭空偏移 8 小时（东八区），
表现为 token 要么提前 8 小时失效、要么多活 8 小时。

所以这里**刻意不复用** `time_utils.now()`，改用带时区的 UTC 时间。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.exceptions import TokenExpiredError, TokenInvalidError, TokenTypeInvalidError

__all__ = [
    "TokenType",
    "TokenPayload",
    "PASSWORD_MAX_LENGTH",
    "hash_password",
    "verify_password",
    "fake_verify_password",
    "create_token",
    "decode_token",
]

# bcrypt 算法本身只使用前 72 字节，超出部分被静默忽略。
# 在 schema 层按此上限校验，避免出现「密码很长但只有前 72 字节生效」的困惑。
PASSWORD_MAX_LENGTH = 72

# passlib 全部封装在这两行里
_pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=settings.BCRYPT_ROUNDS,
)

# 用于「用户不存在时也走一遍等价校验」的固定明文/哈希对，见 fake_verify_password
_DUMMY_PASSWORD = "timing-equalization-dummy-password"
_dummy_hash: str | None = None


# ==========================================================================
# 密码
# ==========================================================================
async def hash_password(raw_password: str) -> str:
    """
    生成密码哈希。

    bcrypt 有 NUL 字节限制，含 `\\x00` 的密码会抛异常，这里提前拒绝
    （属于入参非法，不是服务端故障）。
    """
    if "\x00" in raw_password:
        raise ValueError("密码不能包含空字符")
    return await asyncio.to_thread(_pwd_context.hash, raw_password)


async def verify_password(raw_password: str, hashed_password: str | None) -> bool:
    """
    校验密码。

    哈希为空或格式非法时返回 False 而不是抛异常 —— 数据库里可能存着历史遗留的
    明文或空值，登录接口不应该因此 500。
    """
    if not hashed_password:
        return False
    try:
        return await asyncio.to_thread(_pwd_context.verify, raw_password, hashed_password)
    except (ValueError, TypeError):
        # passlib 的 UnknownHashError 继承自 ValueError
        return False


def _get_dummy_hash() -> str:
    """惰性生成占位哈希。放在 import 期生成会白等一次 ~250ms 的 bcrypt。"""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _pwd_context.hash(_DUMMY_PASSWORD)
    return _dummy_hash


async def fake_verify_password() -> None:
    """
    用户不存在时执行一次开销等价的 bcrypt 校验。

    若用户不存在就直接返回，响应耗时会明显短于「用户存在但密码错」，
    攻击者据此可以枚举出系统里有哪些用户名。调用方在查不到用户时
    应调用本函数后再抛出统一的「用户名或密码错误」。
    """
    await asyncio.to_thread(_pwd_context.verify, _DUMMY_PASSWORD, _get_dummy_hash())


# ==========================================================================
# JWT
# ==========================================================================
class TokenType(StrEnum):
    """令牌类型。access 用于访问业务接口，refresh 只用于换取新令牌。

    用 `StrEnum`（Python 3.11+）而不是 `(str, Enum)`：后者在 3.11 上
    `f"{TokenType.ACCESS}"` 会得到 `"TokenType.ACCESS"` 而不是 `"access"`，
    一旦有人把成员直接插进日志或 JWT 载荷就会静默写错值。
    本项目所有使用点都显式取 `.value`（见 security.py 与 auth_service.py），
    换成 `StrEnum` 后两种写法结果一致。
    """

    ACCESS = "access"
    REFRESH = "refresh"


@dataclass(frozen=True)
class TokenPayload:
    """解析后的 JWT 载荷（已做类型转换）。"""

    user_id: int
    role: str | None
    token_type: TokenType
    jti: str
    exp: datetime
    iat: datetime
    # 令牌版本号，用于「强制下线」：对该用户 INCR 版本后，
    # 版本号对不上的 refreshToken 一律拒绝。详见 app/core/token_store.py
    version: int = 0

    @property
    def expires_in(self) -> int:
        """距过期还有多少秒（至少为 0）。"""
        delta = (self.exp - _utc_now()).total_seconds()
        return max(0, int(delta))


def _utc_now() -> datetime:
    """JWT 专用：带 UTC 时区的当前时间。业务时间请用 app.utils.time_utils.now()。"""
    return datetime.now(UTC)


def create_token(
    user_id: int,
    role: str | None,
    token_type: TokenType,
    expires_delta: timedelta,
    version: int = 0,
) -> tuple[str, TokenPayload]:
    """
    签发令牌。

    返回 `(token, payload)`。payload 一并返回是为了让调用方拿到 `jti`，
    以便把它写进 Redis 白名单（见 app/core/token_store.py）。

    载荷字段：`sub`(用户ID) / `role` / `type` / `jti` / `ver` / `iat` / `exp`。
    `sub` 按 RFC 7519 要求序列化为字符串，解析时再转回 int。

    `version` 由调用方从 TokenStore 读取当前值后传入，用于强制下线。
    """
    issued_at = _utc_now()
    expires_at = issued_at + expires_delta
    jti = uuid.uuid4().hex

    claims: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "type": token_type.value,
        "jti": jti,
        "ver": version,
        "iat": issued_at,
        "exp": expires_at,
    }

    token = jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    payload = TokenPayload(
        user_id=user_id,
        role=role,
        token_type=token_type,
        jti=jti,
        exp=expires_at,
        iat=issued_at,
        version=version,
    )
    return token, payload


def decode_token(token: str, expected_type: TokenType | None = None) -> TokenPayload:
    """
    解析并校验令牌。

    抛出：
    - `TokenExpiredError`：签名正确但已过期，前端据此触发续期流程。
    - `TokenInvalidError`：签名错误、结构损坏、缺少必需字段。
    - `TokenTypeInvalidError`：类型不符（例如拿 refreshToken 直接调业务接口）。

    `expected_type` 为 None 表示不校验类型。
    """
    try:
        claims = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "iat", "sub", "jti", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError() from exc
    except jwt.InvalidTokenError as exc:
        # 包含签名错误、格式错误、缺字段等全部情形。
        # 刻意不把底层原因透给前端，避免为攻击者提供试探线索。
        raise TokenInvalidError() from exc

    raw_type = claims.get("type")
    try:
        token_type = TokenType(raw_type)
    except ValueError as exc:
        raise TokenTypeInvalidError() from exc

    if expected_type is not None and token_type is not expected_type:
        raise TokenTypeInvalidError()

    try:
        user_id = int(claims["sub"])
    except (TypeError, ValueError) as exc:
        raise TokenInvalidError() from exc

    try:
        version = int(claims.get("ver", 0))
    except (TypeError, ValueError):
        # 版本号缺失或非法都按 0 处理：0 是「从未强制下线」的默认值
        version = 0

    return TokenPayload(
        user_id=user_id,
        role=claims.get("role"),
        token_type=token_type,
        jti=str(claims["jti"]),
        exp=datetime.fromtimestamp(claims["exp"], tz=UTC),
        iat=datetime.fromtimestamp(claims["iat"], tz=UTC),
        version=version,
    )
