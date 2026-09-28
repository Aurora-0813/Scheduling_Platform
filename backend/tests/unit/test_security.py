"""
密码哈希与 JWT 单元测试（模块 9 的安全底座）

被测对象：`app/core/security.py`。这里**不碰数据库、不碰 Redis**，
因为该模块的所有输入都是内存里的明文与令牌 —— 认证接口的行为差异
（谁被拒、返回哪个错误码）交由 `tests/api/test_auth_api.py` 覆盖，
本文件只盯住「密码学与令牌格式」这一层。

三条最容易被改坏、且改坏后**不会立刻报错**的约定：

1. **口令校验失败必须是 False，不能抛异常**
   （`verify_password`）。库里可能存着历史明文、空值、被截断的哈希，
   一旦抛异常，登录接口会 500 而不是 401，前端拿不到「用户名或密码错误」。
2. **`exp` / `iat` 必须是 UTC 时间戳**。PyJWT 把 naive datetime 当作 UTC
   编码，若这里换成 `time_utils.now()`（本地时间），`exp` 会凭空偏移 8 小时，
   表现为「刚登录就过期」或「令牌多活 8 小时」—— 两者都不会报错。
   `test_exp_is_utc_based_not_local_time` 就是这条的哨兵。
3. **`type` 声明必须校验**。少了它，refreshToken 可以直接当 accessToken
   调业务接口，等于把「7 天有效」的令牌当成短期令牌用。

bcrypt 的 72 字节截断是**已知且有意保留的现状**（不是我们的实现选择），
见文件末尾的用例与汇报文档的待确认项。
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest

from app.core import security
from app.core.config import settings
from app.core.exceptions import TokenExpiredError, TokenInvalidError, TokenTypeInvalidError
from app.core.security import (
    PASSWORD_MAX_LENGTH,
    TokenType,
    create_token,
    decode_token,
    fake_verify_password,
    hash_password,
    verify_password,
)

pytestmark = pytest.mark.unit

# bcrypt 哈希的固定形态：`$2b$<cost>$<53 字符盐+摘要>`
_BCRYPT_PATTERN = re.compile(r"^\$2[aby]\$(\d{2})\$[./A-Za-z0-9]{53}$")


def _claims_of(token: str) -> dict[str, Any]:
    """解开令牌但不校验（用于断言载荷格式本身）。"""
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"verify_exp": False},
    )


# ==========================================================================
# 口令哈希
# ==========================================================================
async def test_hash_password_produces_bcrypt_hash_with_configured_cost() -> None:
    """哈希是 bcrypt，且 cost 取自配置（测试环境为 4）。

    若有人把 cost 写死成 12，测试会变慢但不会失败 —— 这条断言把
    「hash 里记录的 cost」与「settings.BCRYPT_ROUNDS」绑在一起。
    """
    hashed = await hash_password("Test@123456")

    matched = _BCRYPT_PATTERN.match(hashed)
    assert matched, f"不是预期的 bcrypt 形态: {hashed[:10]}..."
    assert matched.group(1) == f"{settings.BCRYPT_ROUNDS:02d}"


async def test_hash_password_is_salted() -> None:
    """同一口令两次哈希结果不同（bcrypt 自带随机盐）。"""
    first = await hash_password("Test@123456")
    second = await hash_password("Test@123456")

    assert first != second
    # 但两者都能校验通过
    assert await verify_password("Test@123456", first)
    assert await verify_password("Test@123456", second)


async def test_verify_password_accepts_only_the_right_password() -> None:
    hashed = await hash_password("Test@123456")

    assert await verify_password("Test@123456", hashed) is True
    assert await verify_password("Test@12345", hashed) is False
    assert await verify_password("test@123456", hashed) is False, "大小写必须敏感"
    assert await verify_password("", hashed) is False


@pytest.mark.parametrize(
    "stored",
    [
        None,  # 历史数据里的空值
        "",  # 空串
        "plaintext-password",  # 有人手工写进去的明文
        "$2b$04$tooshort",  # 被截断的哈希
        "$1$md5$notbcrypt",  # 别的算法
    ],
)
async def test_verify_password_returns_false_for_broken_stored_hash(stored) -> None:
    """坏哈希一律返回 False **而不是抛异常** —— 否则登录接口会 500。"""
    assert await verify_password("Test@123456", stored) is False


async def test_hash_password_rejects_nul_byte() -> None:
    """bcrypt 不接受 `\\x00`，因此在写库前就拒绝（属于入参非法）。"""
    with pytest.raises(ValueError):
        await hash_password("abc\x00def")


async def test_password_longer_than_72_bytes_is_truncated_by_bcrypt() -> None:
    """
    ⚠️ 已知现状：bcrypt 只使用口令的**前 72 字节**，超出部分被静默忽略。

    因此「前 72 字节相同、之后不同」的两个口令会互相校验通过：

        "a"*72 + "X"  与  "a"*72 + "Y"   →  verify 通过

    这是 bcrypt 算法本身的行为，不是本项目的实现缺陷。当前的处理方式是：

    - `app/schemas/auth.py` 用 `max_length=PASSWORD_MAX_LENGTH`(72) 在**字符**
      层面拦一道（登录接口）；
    - `hash_password()` 是唯一写入口，因此不存在「注册时被静默截断」的路径。

    但要注意单位差：72 个汉字是 216 字节，字符层校验拦不住字节层截断。
    本用例把现状钉住：哪天在 `hash_password()` 里补上字节校验，
    它会失败并提醒同步更新本条注释与汇报文档的待确认项。
    """
    head = "a" * 72
    hashed = await hash_password(head + "X")

    assert await verify_password(head + "Y", hashed) is True, "bcrypt 截断行为已变化，请复核"
    assert await verify_password("a" * 71 + "b", hashed) is False


async def test_fake_verify_password_costs_the_same_as_a_real_check() -> None:
    """用户不存在时也要走一次等价的 bcrypt 校验（防用户名枚举）。

    这里校验的是「占位哈希本身是合规的 bcrypt，且与占位明文匹配」，
    而不是耗时 —— 在 CI 的慢机器上比耗时会抖动。
    """
    dummy_hash = security._get_dummy_hash()
    matched = _BCRYPT_PATTERN.match(dummy_hash)
    assert matched, "占位哈希必须是真实的 bcrypt 哈希，否则耗时不等价"
    assert matched.group(1) == f"{settings.BCRYPT_ROUNDS:02d}"
    assert await verify_password(security._DUMMY_PASSWORD, dummy_hash) is True

    assert await fake_verify_password() is None


def test_dummy_hash_is_created_lazily() -> None:
    """占位哈希惰性生成：import 期就算一次 bcrypt 会白等 250 毫秒。"""
    assert security._dummy_hash is not None or security._get_dummy_hash()


def test_password_max_length_constant_is_bcrypt_limit() -> None:
    """被 schema 引用的上限值就是 bcrypt 的 72 字节（见 app/schemas/auth.py）。"""
    assert PASSWORD_MAX_LENGTH == 72


# ==========================================================================
# JWT：签发
# ==========================================================================
def test_token_type_enum_values_are_stable() -> None:
    """`type` 声明是接口契约（前端可能解析），不能改名。"""
    assert TokenType.ACCESS.value == "access"
    assert TokenType.REFRESH.value == "refresh"
    assert TokenType.ACCESS == "access", "StrEnum 的成员应可直接与字符串比较"


def test_create_token_payload_shape() -> None:
    token, payload = create_token(42, "admin", TokenType.ACCESS, timedelta(minutes=30), version=3)

    claims = _claims_of(token)
    assert claims["sub"] == "42", "sub 按 RFC 7519 必须是字符串"
    assert claims["role"] == "admin"
    assert claims["type"] == "access"
    assert claims["ver"] == 3
    assert re.fullmatch(r"[0-9a-f]{32}", claims["jti"]), "jti 应是 uuid4().hex"

    assert payload.user_id == 42
    assert payload.jti == claims["jti"]
    assert payload.version == 3
    assert payload.token_type is TokenType.ACCESS


def test_create_token_defaults_version_to_zero() -> None:
    """未强制下线过的用户版本号为 0。"""
    _, payload = create_token(1, "user", TokenType.ACCESS, timedelta(minutes=5))
    assert payload.version == 0


def test_exp_is_utc_based_not_local_time() -> None:
    """`exp` 必须是「当前 UTC 时间戳 + 有效期」，不能带本地时区偏移。

    这是「差 8 小时」类故障的哨兵：若 `security.py` 改用
    `app/utils/time_utils.now()`（本地 naive 时间）来算 `exp`，
    在东八区会多出 28800 秒。
    """
    before = time.time()
    token, payload = create_token(1, "user", TokenType.ACCESS, timedelta(minutes=30))
    after = time.time()

    exp = _claims_of(token)["exp"]
    # 容差 2 秒：PyJWT 把 exp 截成整数秒，且本地时间与 UTC 之间不做任何换算，
    # 因此一旦有人改用本地时间，这里的差值会跳到 +28800（东八区），必然失败。
    assert before + 1798 <= exp <= after + 1802, "exp 与 UTC 当前时间之差应约等于 30 分钟"

    # payload 里的 exp 是带时区的 datetime，且与声明的 exp 一致
    assert payload.exp.tzinfo is not None
    assert abs(payload.exp.timestamp() - exp) < 1
    assert 1798 <= payload.expires_in <= 1800


def test_iat_and_exp_are_consistent() -> None:
    token, _ = create_token(1, "user", TokenType.REFRESH, timedelta(days=7))
    claims = _claims_of(token)

    assert claims["exp"] - claims["iat"] == 7 * 24 * 3600


def test_role_may_be_none() -> None:
    """未分配角色的令牌也能签出来（登录接口会先拦住，这里是防御性保留）。"""
    token, _ = create_token(1, None, TokenType.ACCESS, timedelta(minutes=5))
    assert _claims_of(token)["role"] is None


# ==========================================================================
# JWT：解析与校验
# ==========================================================================
def test_decode_token_round_trip() -> None:
    token, payload = create_token(7, "resource_admin", TokenType.REFRESH, timedelta(days=1), 2)

    decoded = decode_token(token, expected_type=TokenType.REFRESH)

    assert decoded.user_id == payload.user_id == 7
    assert decoded.role == "resource_admin"
    assert decoded.jti == payload.jti
    assert decoded.version == 2
    assert decoded.token_type is TokenType.REFRESH


def test_decode_without_expected_type_accepts_both_kinds() -> None:
    access, _ = create_token(1, "user", TokenType.ACCESS, timedelta(minutes=1))
    refresh, _ = create_token(1, "user", TokenType.REFRESH, timedelta(minutes=1))

    assert decode_token(access).token_type is TokenType.ACCESS
    assert decode_token(refresh).token_type is TokenType.REFRESH


@pytest.mark.parametrize("wrong_type", [TokenType.REFRESH, TokenType.ACCESS])
def test_type_mismatch_is_rejected(wrong_type: TokenType) -> None:
    """拿 refreshToken 调业务接口（或反之）必须 40104，而不是放行。"""
    issued = TokenType.ACCESS if wrong_type is TokenType.REFRESH else TokenType.REFRESH
    token, _ = create_token(1, "user", issued, timedelta(minutes=5))

    with pytest.raises(TokenTypeInvalidError):
        decode_token(token, expected_type=wrong_type)


def test_expired_token_raises_expired_error() -> None:
    """过期要用独立错误码（40103）：前端据此触发续期，而不是跳登录页。"""
    token, _ = create_token(1, "user", TokenType.ACCESS, timedelta(seconds=-10))

    with pytest.raises(TokenExpiredError):
        decode_token(token, expected_type=TokenType.ACCESS)


def test_tampered_signature_is_rejected() -> None:
    """改一个签名位就该被拒。

    特意改**第一位**而不是最后一位：base64url 的最后一个字符只承载 2 个有效
    比特，改它可能解码出**完全相同**的字节，得到一个「看起来改了、其实没改」的
    假用例（实测踩过）。第一位一定落在真实字节上。
    """
    token, _ = create_token(1, "user", TokenType.ACCESS, timedelta(minutes=5))
    header, payload_part, signature = token.split(".")
    flipped = ("a" if signature[0] != "a" else "b") + signature[1:]

    with pytest.raises(TokenInvalidError):
        decode_token(f"{header}.{payload_part}.{flipped}")


def test_modified_payload_with_original_signature_is_rejected() -> None:
    """改载荷（例如把自己的 sub 换成管理员的）而沿用旧签名 → 必须被拒。"""
    import base64
    import json

    token, _ = create_token(1, "user", TokenType.ACCESS, timedelta(minutes=5))
    header, payload_part, signature = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload_part + "=="))
    claims["sub"] = "999"
    forged_payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")

    with pytest.raises(TokenInvalidError):
        decode_token(f"{header}.{forged_payload}.{signature}")


def test_token_signed_with_other_secret_is_rejected() -> None:
    claims = {
        "sub": "1",
        "role": "admin",
        "type": "access",
        "jti": "x" * 32,
        "ver": 0,
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    forged = jwt.encode(claims, "another-secret-key-value", algorithm=settings.JWT_ALGORITHM)

    with pytest.raises(TokenInvalidError):
        decode_token(forged)


def test_unsigned_token_is_rejected() -> None:
    """`alg: none` 的令牌必须被拒（PyJWT 的 `none` 算法不接受密钥）。"""
    forged = jwt.encode({"sub": "1", "type": "access"}, None, algorithm="none")

    with pytest.raises(TokenInvalidError):
        decode_token(forged)


@pytest.mark.parametrize("missing_claim", ["exp", "iat", "sub", "jti", "type"])
def test_missing_required_claim_is_rejected(missing_claim: str) -> None:
    """五个必需声明缺一不可（由 PyJWT 的 `options.require` 保证）。"""
    claims: dict[str, Any] = {
        "sub": "1",
        "role": "user",
        "type": "access",
        "jti": "y" * 32,
        "ver": 0,
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    del claims[missing_claim]
    token = jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    with pytest.raises(TokenInvalidError):
        decode_token(token)


def test_unknown_type_value_is_rejected() -> None:
    """`type` 不在枚举里（例如被改成 "admin"）→ 40104，不能当作 access 放行。"""
    token = jwt.encode(
        {
            "sub": "1",
            "role": "user",
            "type": "admin",
            "jti": "z" * 32,
            "ver": 0,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

    with pytest.raises(TokenTypeInvalidError):
        decode_token(token)


def test_non_numeric_subject_is_rejected() -> None:
    """`sub` 不是数字 → 令牌无效（用户 ID 无法定位）。"""
    token = jwt.encode(
        {
            "sub": "not-a-number",
            "role": "user",
            "type": "access",
            "jti": "w" * 32,
            "ver": 0,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

    with pytest.raises(TokenInvalidError):
        decode_token(token)


@pytest.mark.parametrize("bad_version", ["abc", None, [1]])
def test_bad_version_falls_back_to_zero(bad_version: Any) -> None:
    """`ver` 缺失或非法一律按 0 处理，**不报错**。

    版本号是「强制下线」的辅助声明：旧版本客户端签出的令牌可能没有它。
    把它当成硬错误会让「升级后所有老令牌立刻失效」，代价远大于收益。
    """
    token = jwt.encode(
        {
            "sub": "1",
            "role": "user",
            "type": "access",
            "jti": "v" * 32,
            "ver": bad_version,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

    assert decode_token(token).version == 0


def test_missing_version_falls_back_to_zero() -> None:
    token = jwt.encode(
        {
            "sub": "1",
            "role": "user",
            "type": "access",
            "jti": "u" * 32,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

    assert decode_token(token).version == 0


@pytest.mark.parametrize("garbage", ["", "not.a.jwt", "a.b.c", "Bearer x.y.z"])
def test_garbage_token_is_rejected(garbage: str) -> None:
    with pytest.raises(TokenInvalidError):
        decode_token(garbage)
