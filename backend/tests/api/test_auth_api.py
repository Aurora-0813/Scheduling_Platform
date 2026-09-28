"""
认证接口测试（模块 9）—— **这是 M1 验收的达成点**

覆盖文档 5.3 模块 9 的契约，以及方案中列出的全部失败分支：

| 用例                                 | 期望                        |
| ------------------------------------ | --------------------------- |
| 登录成功                              | 200 / 三个字段 / 可直接用    |
| 密码错、账号不存在                     | 401 / 40107（文案不区分）    |
| 账号禁用 / 未分配角色                  | 403 / 40108 / 40302          |
| 缺参数                                | 400 / 40001 + 字段级明细     |
| 无 token / 伪造签名 / 已过期 / 类型错用 | 401 / 40101 / 40102 / 40103 / 40104 |
| refresh 轮换与宽限期                   | 200，旧令牌按宽限期规则失效  |
| 登出后旧 refreshToken                  | 401 / 40106 或 40105         |
| 跨用户吊销会话                         | 403 / 40300                  |

这些错误码不是随便挑的：前端据它决定「静默续期」还是「跳登录页」
（40103 → 续期；40102/40105 → 重新登录），所以错误码本身也是契约，
改动错误码等于改动前端逻辑，必须同步 `docs/api.md`。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.error_codes import ErrorCode
from app.core.permissions import ROLE_USER, Permission, permissions_for_role
from app.core.security import TokenType, create_token
from app.models.system import SysUser
from tests.fakes.factories import (
    ADMIN_PASSWORD,
    DEFAULT_PASSWORD,
    create_admin,
    create_role,
    create_user,
    create_user_with_raw_password,
)

pytestmark = pytest.mark.api

LOGIN = "/api/v1/auth/login"
INFO = "/api/v1/auth/info"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"


def _data(response: httpx.Response) -> dict:
    """取统一响应体（并顺带断言信封结构）。"""
    body = response.json()
    assert set(body) == {"code", "message", "data"}, body
    return body


# ==========================================================================
# 登录成功
# ==========================================================================
async def test_login_success_returns_token_pair(
    client: httpx.AsyncClient, db_session: AsyncSession, login
) -> None:
    await create_admin(db_session)

    response = await login(client, "admin", ADMIN_PASSWORD)
    assert response.status_code == 200

    body = _data(response)
    assert body["code"] == ErrorCode.SUCCESS
    assert body["message"] == "登录成功"

    data = body["data"]
    assert data["role"] == "admin"
    assert data["accessToken"] and data["refreshToken"]
    assert data["accessToken"] != data["refreshToken"]


async def test_login_payload_has_exactly_the_contract_fields(
    client: httpx.AsyncClient, db_session: AsyncSession, login
) -> None:
    """
    文档 5.3 约定 `data` 只有 `accessToken` / `refreshToken` / `role` 三个字段。

    这条用例守着「不要随手往登录响应里加字段」：多余字段会进前端契约，
    日后删它就是破坏性变更。真需要暴露更多信息，请加到 `GET /auth/info`。
    """
    await create_admin(db_session)
    response = await login(client, "admin", ADMIN_PASSWORD)
    assert set(response.json()["data"]) == {"accessToken", "refreshToken", "role"}


async def test_access_token_from_login_can_call_info(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    login,
    auth_headers,
) -> None:
    """登录签发的 accessToken 必须能立刻通过鉴权 —— 端到端的最小闭环。"""
    user, _role = await create_admin(db_session)

    token = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]
    response = await client.get(INFO, headers=auth_headers(token))
    assert response.status_code == 200

    data = response.json()["data"]
    assert data["id"] == user.id
    assert data["username"] == "admin"
    assert data["role"] == "admin"
    # 权限来自 sys_role.permissions（决策 3），与静态映射一致
    assert set(data["permissions"]) == set(permissions_for_role("admin"))


async def test_username_is_trimmed_but_password_is_not(
    client: httpx.AsyncClient, db_session: AsyncSession, login
) -> None:
    """
    `username` 会 strip（前端输入框常带尾随空格），`password` **不会**。

    口令里的空格是有效字符，strip 掉会让「密码结尾带空格」的用户
    永远登不上，且没有任何报错线索。
    """
    await create_user(
        db_session,
        username="admin",
        password="Pwd with space ",
        role=await create_role(db_session, name="admin"),
    )

    ok_response = await login(client, "  admin  ", "Pwd with space ")
    assert ok_response.status_code == 200

    bad_response = await login(client, "admin", "Pwd with space")
    assert bad_response.status_code == 401


# ==========================================================================
# 登录失败
# ==========================================================================
async def test_login_with_wrong_password_returns_40107(
    client: httpx.AsyncClient, db_session: AsyncSession, login
) -> None:
    await create_admin(db_session)
    response = await login(client, "admin", "definitely-wrong")

    assert response.status_code == 401
    assert _data(response)["code"] == ErrorCode.CREDENTIALS_INVALID


async def test_login_with_unknown_user_returns_the_same_error(
    client: httpx.AsyncClient, db_session: AsyncSession, login
) -> None:
    """
    「用户不存在」与「密码错误」必须返回**完全一样**的错误码与文案。

    否则攻击者可以批量试用户名、靠错误码枚举出系统里有哪些账号，
    再针对这些账号做定向爆破。
    """
    await create_admin(db_session)

    unknown = await login(client, "nobody", "whatever")
    wrong_password = await login(client, "admin", "wrong")

    assert unknown.status_code == wrong_password.status_code == 401
    assert unknown.json() == wrong_password.json()


async def test_login_with_disabled_account_returns_40108(
    client: httpx.AsyncClient, db_session: AsyncSession, login
) -> None:
    role = await create_role(db_session, name="admin")
    await create_user(db_session, username="frozen", password=DEFAULT_PASSWORD, role=role, status=0)

    # HTTP 401 而不是 403：本项目的规则是「HTTP 状态码跟随业务码分段」
    # （见 app/core/exceptions.py 每类的 http_status 与 error_codes.py 的分段表）。
    # 40108 属于 401xx 段 = 认证失败，因为被禁用的账号**无法完成认证**，
    # 而不是「已认证但无权访问」。前端按 `code` 分支，不按 HTTP 状态码分支。
    response = await login(client, "frozen", DEFAULT_PASSWORD)
    assert response.status_code == 401, response.text
    assert _data(response)["code"] == ErrorCode.USER_DISABLED


async def test_login_without_role_returns_40302(
    client: httpx.AsyncClient, db_session: AsyncSession, login
) -> None:
    """未分配角色（`role_id` 为空）的账号不能登录 —— 否则会签出无权限的令牌。"""
    await create_user(db_session, username="orphan", password=DEFAULT_PASSWORD, role=None)

    response = await login(client, "orphan", DEFAULT_PASSWORD)
    assert response.status_code == 403
    assert _data(response)["code"] == ErrorCode.ROLE_MISSING


async def test_disabled_and_role_errors_are_hidden_behind_a_wrong_password(
    client: httpx.AsyncClient, db_session: AsyncSession, login
) -> None:
    """
    密码错时**不得**泄露「账号被禁用」或「账号没有角色」。

    实现上靠校验顺序（密码 → 状态 → 角色）保证，这条用例把顺序钉住：
    若有人把状态检查挪到密码之前，40108 就会在密码错误时出现，用例失败。
    """
    role = await create_role(db_session, name="admin")
    await create_user(db_session, username="frozen", password=DEFAULT_PASSWORD, role=role, status=0)
    await create_user(db_session, username="orphan", password=DEFAULT_PASSWORD, role=None)

    frozen = await login(client, "frozen", "wrong-password")
    orphan = await login(client, "orphan", "wrong-password")

    assert frozen.status_code == 401
    assert orphan.status_code == 401
    assert _data(frozen)["code"] == ErrorCode.CREDENTIALS_INVALID
    assert _data(orphan)["code"] == ErrorCode.CREDENTIALS_INVALID


async def test_login_tolerates_broken_password_column(
    client: httpx.AsyncClient, db_session: AsyncSession, login
) -> None:
    """
    库里存着明文 / 空串 / 别家的哈希 / 被截断的哈希时，登录必须 401 而不是 500。

    云库是手工建的，`password` 列里出现什么历史数据都不奇怪；
    500 会把「运维数据问题」变成「后端接口故障」，把排查方向带偏。
    （`NULL` 这一种不必测：`sys_user.password` 是 `NOT NULL`，数据库自己就挡住了。）
    """
    role = await create_role(db_session, name="admin")
    broken = {
        # 明文：早期手工插的数据
        "legacy": "123456",
        # 空串：NOT NULL 允许空串，但空串不是合法哈希
        "blank": "",
        # 别的算法（比如从旧系统迁过来的 argon2）
        "foreign": "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$hashhashhash",
        # 有 bcrypt 前缀但长度不对（被截断 / 手工拼出来的）
        # 刻意不用「长度正确但校验位错」的哈希：那种值会让 passlib 打
        # PasslibHashWarning，污染整个测试套件的输出（已实测）。
        "truncated": "$2b$12$short",
    }
    for username, raw in broken.items():
        await create_user_with_raw_password(
            db_session, username=username, raw_password_in_db=raw, role=role
        )

    for username in broken:
        response = await login(client, username, "123456")
        assert response.status_code == 401, (username, response.text)
        assert _data(response)["code"] == ErrorCode.CREDENTIALS_INVALID


async def test_login_accepts_short_password_without_validation_error(
    client: httpx.AsyncClient, db_session: AsyncSession, login
) -> None:
    """
    登录接口不接受「密码至少 6 位」这类校验（`PasswordField` 的下限刻意是 1）。

    老账号的口令可能比现在的规则短；对登录请求做长度校验，会把
    「口令不对」变成「参数非法」，让这些用户连登录的机会都没有。
    """
    await create_admin(db_session)
    response = await login(client, "admin", "1")
    assert response.status_code == 401
    assert _data(response)["code"] == ErrorCode.CREDENTIALS_INVALID


async def test_login_missing_password_is_a_validation_error(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """字段缺失是**参数问题**（40001），不是认证失败（40107）。"""
    await create_admin(db_session)

    response = await client.post(LOGIN, json={"username": "admin"})
    assert response.status_code == 400

    body = _data(response)
    assert body["code"] == ErrorCode.PARAM_INVALID
    errors = body["data"]["errors"]
    assert errors and errors[0]["field"] == "password"


async def test_login_with_empty_body_is_a_validation_error(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(LOGIN, json={})
    assert response.status_code == 400
    fields = {item["field"] for item in response.json()["data"]["errors"]}
    assert fields == {"username", "password"}


# ==========================================================================
# /auth/info 的令牌校验
# ==========================================================================
async def test_info_without_token_returns_40101(client: httpx.AsyncClient) -> None:
    """
    没有 Authorization 头必须是 401 + 40101，**不是** 403。

    依赖里 `HTTPBearer(auto_error=False)` 就是为此：默认的 auto_error=True
    会抛 Starlette 的 403，与「未登录」的语义不符，前端会误判为「已登录但无权限」。
    """
    response = await client.get(INFO)
    assert response.status_code == 401
    assert _data(response)["code"] == ErrorCode.TOKEN_MISSING


async def test_info_with_malformed_authorization_header(
    client: httpx.AsyncClient,
) -> None:
    """`Authorization: admin`（没有 Bearer 前缀）按「缺令牌」处理。"""
    response = await client.get(INFO, headers={"Authorization": "admin"})
    assert response.status_code == 401
    assert _data(response)["code"] == ErrorCode.TOKEN_MISSING


async def test_info_with_forged_signature_returns_40102(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """用错误的密钥签出的令牌必须被拒 —— 这是整个鉴权的根基。"""
    user, _role = await create_admin(db_session)
    forged, _payload = create_token(user.id, "admin", TokenType.ACCESS, timedelta(minutes=5))

    # 篡改签名，模拟「被伪造 / 密钥被换过」。
    #
    # ⚠️ 必须动签名的**第一个**字符，不能动最后一个：
    # HS256 签名是 32 字节，base64url 编码后为 43 个字符；末字符只承载
    # 4 个有效比特，其低 2 位是补位、解码时被丢弃。所以当末字符恰好是
    # 高位为 0000 的那一类（实测只有 'A'）时，把它改成 'B' 解码出来的
    # 签名字节**完全不变**，令牌仍然有效 —— 用例会以约 1/16 的概率随机
    # 失败（2026-09-28 合并验证时即撞上该情形）。
    # 首字符的 6 个比特全部参与解码，改掉它必然验签失败。
    head, body, signature = forged.split(".")
    tampered = f"{head}.{body}.{'A' if signature[0] != 'A' else 'B'}{signature[1:]}"

    response = await client.get(INFO, headers={"Authorization": f"Bearer {tampered}"})
    assert response.status_code == 401
    assert _data(response)["code"] == ErrorCode.TOKEN_INVALID


async def test_info_with_garbage_token_returns_40102(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(INFO, headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401
    assert _data(response)["code"] == ErrorCode.TOKEN_INVALID


async def test_info_with_expired_access_token_returns_40103(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """
    过期令牌返回 40103 而不是 40102。

    前端靠这个区分处理方式：40103 → 静默调 `/auth/refresh` 续期，
    40102 → 直接跳登录页。两者混用会让用户在过期时被莫名登出。
    """
    user, _role = await create_admin(db_session)
    expired, _payload = create_token(user.id, "admin", TokenType.ACCESS, timedelta(seconds=-10))

    response = await client.get(INFO, headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401
    assert _data(response)["code"] == ErrorCode.TOKEN_EXPIRED


async def test_refresh_token_cannot_be_used_as_access_token(
    client: httpx.AsyncClient, db_session: AsyncSession, login, auth_headers
) -> None:
    """
    拿 refreshToken 调业务接口必须被拒（40104）。

    不校验 `type` 的话，有效期 7 天的 refreshToken 就能当 30 分钟的
    accessToken 用，等于把访问凭证的有效期放大 336 倍，
    且「accessToken 短有效期」这层设计彻底失效。
    """
    await create_admin(db_session)
    token = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]
    refresh_token = token["refreshToken"]

    response = await client.get(INFO, headers={"Authorization": f"Bearer {refresh_token}"})
    assert response.status_code == 401
    assert _data(response)["code"] == ErrorCode.TOKEN_TYPE_INVALID


async def test_token_of_deleted_user_returns_40100(
    client: httpx.AsyncClient, db_session: AsyncSession, login, auth_headers
) -> None:
    """签名有效但用户已被删除：用 40100 与「伪造令牌」区分开，便于排查。"""
    user, _role = await create_admin(db_session)
    token = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]

    await db_session.delete(await db_session.get(SysUser, user.id))
    # 必须显式提交：AUTOCOMMIT 只影响隔离级别，DELETE 仍需 flush 才会下发
    await db_session.commit()

    response = await client.get(INFO, headers=auth_headers(token))
    assert response.status_code == 401
    assert _data(response)["code"] == ErrorCode.UNAUTHORIZED


async def test_role_change_takes_effect_without_relogin(
    client: httpx.AsyncClient, db_session: AsyncSession, login, auth_headers
) -> None:
    """
    改角色后**立即**生效，不需要重新登录。

    这是「授权以数据库为准」的直接后果（app/api/deps.py）：令牌里的 `role`
    只用于日志，鉴权每次都从库里读。若有人为了省一次查询改成信任令牌里的
    `role`，这条用例会失败 —— 那时降权用户会拿着旧令牌继续拥有原权限。
    """
    user, _role = await create_admin(db_session)
    token = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]

    before = await client.get(INFO, headers=auth_headers(token))
    assert Permission.USER_VIEW in before.json()["data"]["permissions"]

    user_role = await create_role(db_session, name=ROLE_USER)
    user.role_id = user_role.id
    await db_session.commit()

    after = await client.get(INFO, headers=auth_headers(token))
    assert after.status_code == 200
    assert after.json()["data"]["role"] == ROLE_USER
    assert Permission.USER_VIEW not in after.json()["data"]["permissions"]


# ==========================================================================
# 续期
# ==========================================================================
async def test_refresh_rotates_tokens(
    client: httpx.AsyncClient, db_session: AsyncSession, login
) -> None:
    await create_admin(db_session)
    tokens = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]

    response = await client.post(REFRESH, json={"refreshToken": tokens["refreshToken"]})
    assert response.status_code == 200

    body = _data(response)
    assert body["message"] == "续期成功"
    data = body["data"]
    # 契约：refresh 返回的是令牌对，**不含** role（文档 5.3 未约定该字段）
    assert set(data) == {"accessToken", "refreshToken"}
    assert data["refreshToken"] != tokens["refreshToken"]


async def test_new_access_token_from_refresh_works(
    client: httpx.AsyncClient, db_session: AsyncSession, login, auth_headers
) -> None:
    await create_admin(db_session)
    tokens = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]

    refreshed = (await client.post(REFRESH, json={"refreshToken": tokens["refreshToken"]})).json()[
        "data"
    ]

    response = await client.get(INFO, headers=auth_headers(refreshed))
    assert response.status_code == 200
    assert response.json()["data"]["username"] == "admin"


async def test_old_refresh_token_replays_within_grace_period(
    client: httpx.AsyncClient, db_session: AsyncSession, login
) -> None:
    """
    旧 refreshToken 在宽限期内仍可再换一次 —— 这是**刻意**的。

    前端并发请求同时收到 401 时会各自触发续期；若严格「一次即废」，
    只有一个请求能成功，其余会把用户踢到登录页。宽限期把这个体验问题
    变成一次可接受的重复续期（代价见下一条用例：只放行一次，不可重放）。
    """
    await create_admin(db_session)
    tokens = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]
    old = tokens["refreshToken"]

    first = await client.post(REFRESH, json={"refreshToken": old})
    assert first.status_code == 200

    replay = await client.post(REFRESH, json={"refreshToken": old})
    assert replay.status_code == 200, replay.text


async def test_old_refresh_token_is_rejected_after_grace_period(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    login,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """把宽限期设为 0，旧令牌必须立刻失效（宽限期不是永久后门）。"""
    monkeypatch.setattr(settings, "JWT_REFRESH_GRACE_SECONDS", 0)
    await create_admin(db_session)
    old = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]["refreshToken"]

    assert (await client.post(REFRESH, json={"refreshToken": old})).status_code == 200

    replay = await client.post(REFRESH, json={"refreshToken": old})
    assert replay.status_code == 401
    assert _data(replay)["code"] == ErrorCode.REFRESH_TOKEN_INVALID


async def test_access_token_cannot_be_used_to_refresh(
    client: httpx.AsyncClient, db_session: AsyncSession, login
) -> None:
    await create_admin(db_session)
    access = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]["accessToken"]

    response = await client.post(REFRESH, json={"refreshToken": access})
    assert response.status_code == 401
    assert _data(response)["code"] == ErrorCode.TOKEN_TYPE_INVALID


async def test_refresh_with_expired_token_returns_40103(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user, _role = await create_admin(db_session)
    expired, _payload = create_token(user.id, "admin", TokenType.REFRESH, timedelta(seconds=-10))

    response = await client.post(REFRESH, json={"refreshToken": expired})
    assert response.status_code == 401
    assert _data(response)["code"] == ErrorCode.TOKEN_EXPIRED


async def test_refresh_with_unknown_token_returns_40106(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """
    签名合法、未过期，但从未登记进白名单（例如服务重启后内存实现清空）。
    必须被拒 —— 白名单是「令牌是否仍然有效」的唯一依据。
    """
    user, _role = await create_admin(db_session)
    unregistered, _payload = create_token(user.id, "admin", TokenType.REFRESH, timedelta(days=7))

    response = await client.post(REFRESH, json={"refreshToken": unregistered})
    assert response.status_code == 401
    assert _data(response)["code"] == ErrorCode.REFRESH_TOKEN_INVALID


async def test_refresh_fails_strictly_when_redis_is_unavailable(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    login,
    fake_redis: Any,
    application: Any,
) -> None:
    """
    Redis 不可用时续期**严格失败**（50301），不做降级（决策 7）。

    读不到白名单就没有任何依据证明令牌仍然有效；凭空签发新令牌等于
    让登出与强制下线同时失效 —— 这是安全优先于可用性的地方，
    与登录的降级策略（照常发令牌）刻意相反。

    这里刻意用 `RedisTokenStore`（**生产实现**）而不是内存实现：降级判断
    只在 Redis 实现里存在（`_translate_errors` 把连接异常转成
    `RedisUnavailableError`），用内存实现测不出这条路径。
    """
    from app.api.deps import get_token_store
    from app.core.token_store import RedisTokenStore

    store = RedisTokenStore(fake_redis)
    application.dependency_overrides[get_token_store] = lambda: store

    await create_admin(db_session)
    tokens = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]

    # 注入一次连接故障：refresh 的第一步 get_version 就会失败
    fake_redis.fail_next(1)

    response = await client.post(REFRESH, json={"refreshToken": tokens["refreshToken"]})
    assert response.status_code == 503
    assert _data(response)["code"] == ErrorCode.REDIS_UNAVAILABLE


async def test_login_still_succeeds_when_redis_is_unavailable(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    login,
    fake_redis: Any,
    application: Any,
) -> None:
    """
    与上一条相反：Redis 不可用时**登录仍然成功**（决策 7，可用性优先）。

    代价是这次会话的 refreshToken 没能登记进白名单，30 分钟后
    accessToken 过期时无法续期，用户需要重新登录。这个代价是可接受的；
    若把登记失败升级为登录失败，Redis 一挂整个系统就没人能登录了。
    """
    from app.api.deps import get_token_store
    from app.core.token_store import RedisTokenStore

    store = RedisTokenStore(fake_redis)
    application.dependency_overrides[get_token_store] = lambda: store
    await create_admin(db_session)

    # 故障要覆盖到整条登录链路：读版本号（get_version）与登记白名单
    # （register_refresh 的 pipeline）。只失败一次会被 `_read_version` 消化掉，
    # 登记反而成功，用例就测不到「登记失败仍能登录」这个降级点。
    fake_redis.fail_next(10)
    response = await login(client, "admin", ADMIN_PASSWORD)
    # 恢复连接，避免注入的失败次数继续影响后面的断言
    fake_redis.recover()

    assert response.status_code == 200
    assert response.json()["data"]["accessToken"]

    # 而这个 refreshToken 换不到新令牌 —— 白名单里从未有过它（40106）
    refreshed = await client.post(
        REFRESH, json={"refreshToken": response.json()["data"]["refreshToken"]}
    )
    assert refreshed.status_code == 401
    assert _data(refreshed)["code"] == ErrorCode.REFRESH_TOKEN_INVALID


# ==========================================================================
# 登出
# ==========================================================================
async def test_logout_revokes_only_the_given_session(
    client: httpx.AsyncClient, db_session: AsyncSession, login, auth_headers
) -> None:
    """
    带 refreshToken 登出 → 只吊销该会话。

    这就是「手机上退出登录，不该把办公室电脑踢下线」的语义。
    """
    await create_admin(db_session)
    phone = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]
    desktop = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]

    response = await client.post(
        LOGOUT, headers=auth_headers(phone), json={"refreshToken": phone["refreshToken"]}
    )
    assert response.status_code == 200
    assert _data(response)["data"] is None

    # 被登出的会话不能再续期（白名单已按 jti 删除）
    revoked = await client.post(REFRESH, json={"refreshToken": phone["refreshToken"]})
    assert revoked.status_code == 401
    assert _data(revoked)["code"] == ErrorCode.REFRESH_TOKEN_INVALID

    # 另一个会话不受影响
    other = await client.post(REFRESH, json={"refreshToken": desktop["refreshToken"]})
    assert other.status_code == 200


async def test_logout_without_refresh_token_revokes_all_sessions(
    client: httpx.AsyncClient, db_session: AsyncSession, login, auth_headers
) -> None:
    """
    不带 body 登出 → 吊销该用户全部会话（并递增令牌版本）。

    版本号递增后，旧 refreshToken 会先在「版本校验」这一步被拦下，
    因此错误码是 40105 而不是 40106 —— 两者对应不同的前端提示：
    40105 表示「账号已在别处被登出」，40106 表示「这个刷新令牌本身不可用」。
    """
    await create_admin(db_session)
    session_a = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]
    session_b = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]

    response = await client.post(LOGOUT, headers=auth_headers(session_a))
    assert response.status_code == 200

    for tokens in (session_a, session_b):
        rejected = await client.post(REFRESH, json={"refreshToken": tokens["refreshToken"]})
        assert rejected.status_code == 401
        assert _data(rejected)["code"] == ErrorCode.TOKEN_REVOKED


async def test_logout_with_unparsable_refresh_token_still_revokes_all(
    client: httpx.AsyncClient, db_session: AsyncSession, login, auth_headers
) -> None:
    """
    传了一个坏 refreshToken 时，退化为「吊销全部会话」而不是报错。

    登出的语义是「让我失去访问能力」；在无法精确定位会话时，
    多踢掉自己的几个会话是可接受的，返回成功却什么都没吊销是不可接受的。
    """
    await create_admin(db_session)
    tokens = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]

    response = await client.post(
        LOGOUT, headers=auth_headers(tokens), json={"refreshToken": "not-a-jwt"}
    )
    assert response.status_code == 200

    rejected = await client.post(REFRESH, json={"refreshToken": tokens["refreshToken"]})
    assert rejected.status_code == 401
    assert _data(rejected)["code"] == ErrorCode.TOKEN_REVOKED


async def test_logout_cannot_revoke_another_users_session(
    client: httpx.AsyncClient, db_session: AsyncSession, login, auth_headers
) -> None:
    """
    拿自己的 accessToken + 别人的 refreshToken 必须 403。

    少了这条检查，任何一个登录用户只要拿到别人的 refreshToken
    （日志泄漏、前端误存、共享设备）就能把对方踢下线。
    """
    role = await create_role(db_session, name="admin")
    await create_user(db_session, username="alice", password=DEFAULT_PASSWORD, role=role)
    await create_user(db_session, username="bob", password=DEFAULT_PASSWORD, role=role)

    alice = (await login(client, "alice", DEFAULT_PASSWORD)).json()["data"]
    bob = (await login(client, "bob", DEFAULT_PASSWORD)).json()["data"]

    response = await client.post(
        LOGOUT, headers=auth_headers(alice), json={"refreshToken": bob["refreshToken"]}
    )
    assert response.status_code == 403
    assert _data(response)["code"] == ErrorCode.FORBIDDEN

    # Bob 的会话必须完好无损
    assert (
        await client.post(REFRESH, json={"refreshToken": bob["refreshToken"]})
    ).status_code == 200


async def test_logout_requires_authentication(client: httpx.AsyncClient) -> None:
    response = await client.post(LOGOUT)
    assert response.status_code == 401
    assert _data(response)["code"] == ErrorCode.TOKEN_MISSING


async def test_logout_twice_is_idempotent(
    client: httpx.AsyncClient, db_session: AsyncSession, login, auth_headers
) -> None:
    """
    重复登出要成功。前端可能在超时后重试；返回 401 会让前端把
    「已登出」误判为「会话异常」而弹错误提示。
    """
    await create_admin(db_session)
    tokens = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]
    body = {"refreshToken": tokens["refreshToken"]}

    first = await client.post(LOGOUT, headers=auth_headers(tokens), json=body)
    second = await client.post(LOGOUT, headers=auth_headers(tokens), json=body)

    assert first.status_code == 200
    assert second.status_code == 200


async def test_access_token_survives_logout_until_it_expires(
    client: httpx.AsyncClient, db_session: AsyncSession, login, auth_headers
) -> None:
    """
    **已知限制，不是缺陷**：accessToken 无状态校验，登出后仍能用。

    这条用例把它显式记录下来。若要「登出即刻失效」，必须让每个请求都查
    Redis 版本号 —— 代价是每个请求多一次往返、且 Redis 挂掉时全站不可用。
    当前取舍是「压短有效期」（`JWT_EXPIRE_MINUTES`）而不是牺牲可用性。

    ⚠️ 若哪天这条用例失败（登出后访问 /auth/info 变成 401），说明有人改了
    校验策略 —— 那是好事，但必须同步更新 app/api/deps.py 的模块说明、
    docs/api.md 与汇报文档里的「强制下线时间窗」。
    """
    await create_admin(db_session)
    tokens = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]

    await client.post(LOGOUT, headers=auth_headers(tokens))

    still_valid = await client.get(INFO, headers=auth_headers(tokens))
    assert still_valid.status_code == 200
