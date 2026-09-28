"""
认证服务（模块 9）

职责边界
--------
本模块只做**认证**（你是谁）与**令牌生命周期**，不做**授权**（你能干什么）。
授权（`require_permission`）在 app/api/deps.py，两者分开是为了让
「登录/续期/登出」这套逻辑能被独立测试，不必构造权限上下文。

调用约定
--------
- 入参是**已解析的原始值**，不是 Request 对象。这样 service 可以在
  curl / 管理脚本 / 定时任务里直接复用，行为与走 HTTP 时完全一致；
- 出参是 `app/schemas/auth.py` 的模型，router 直接包进统一响应体即可；
- 业务失败一律抛 `BizError` 子类，由 app/core/response.py 的异常处理器
  统一转成响应体。本模块**不构造 HTTP 响应**。

本模块不写数据库
----------------
登录/续期/登出只读 `sys_user` 与 `sys_role`，不产生任何写入，
因此不需要 `await db.commit()`（`get_db` 已不再兜底提交，见
app/core/database.py）。将来在这里加「更新最后登录时间」之类的写入时，
**必须显式提交**，否则数据会静默丢失。

降级策略（决策 7）
------------------
| 场景                     | Redis 不可用时                          |
| ------------------------ | --------------------------------------- |
| `login`                  | 仅记 warning，**照常发令牌**（可用性优先）|
| `refresh` / `logout`     | **严格失败**，返回 50301（安全优先）      |

理由：登录时 Redis 只用于「登记白名单」，登记失败的最坏后果是这次会话无法续期；
而续期/登出必须读白名单才能判断「是否已登出/已强制下线」，读不到就没有任何
依据可以证明令牌仍然有效 —— 此时凭空签发新令牌等于让登出彻底失效。

强制下线的时间窗（必须知道）
----------------------------
accessToken 保持**无状态校验**（只验签名与过期，不查 Redis），因此
`revoke_all()` 之后：refreshToken **立即**失效，但已经签发的 accessToken
最多还能用 `JWT_EXPIRE_MINUTES`（默认 30 分钟）。
这是 JWT 的固有取舍；把 accessToken 设短（30 分钟）就是为了压住这个窗口。
若业务上需要「立即踢出」，必须改为每次请求都查 Redis 版本号 ——
代价是每个请求多一次 Redis 往返，且 Redis 挂掉时全站不可用。当前不做。
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.exceptions import (
    AccountLockedError,
    BizError,
    CredentialsInvalidError,
    ForbiddenError,
    RedisUnavailableError,
    RefreshTokenInvalidError,
    RoleMissingError,
    TokenRevokedError,
    UnauthorizedError,
    UserDisabledError,
)
from app.core.logging import get_logger
from app.core.permissions import effective_permissions
from app.core.security import (
    TokenType,
    create_token,
    decode_token,
    fake_verify_password,
    verify_password,
)
from app.core.token_store import RotationOutcome, TokenStore
from app.models.system import SysUser
from app.schemas.auth import LoginOut, TokenPairOut, UserInfoOut
from app.services import risk_service

__all__ = [
    "role_name_of",
    "get_user_by_id",
    "get_user_by_username",
    "build_user_info",
    "authenticate",
    "login",
    "refresh",
    "logout",
]

logger = get_logger(__name__)

# 状态字段语义（文档 6.3）：1 正常，0 禁用
USER_STATUS_ACTIVE = 1


# --------------------------------------------------------------------------- #
# 有效期读取
#
# 刻意写成函数而不是模块级常量：常量会在 import 时就固化，测试无法通过
# monkeypatch settings 来构造「令牌已过期」的场景，只能去改 .env。
# --------------------------------------------------------------------------- #
def _access_expires() -> timedelta:
    return timedelta(minutes=settings.JWT_EXPIRE_MINUTES)


def _refresh_expires() -> timedelta:
    return timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS)


def _refresh_ttl_seconds() -> int:
    """refreshToken 在白名单里的 TTL，与 JWT 自身的有效期保持一致。"""
    return int(_refresh_expires().total_seconds())


# --------------------------------------------------------------------------- #
# 用户读取
# --------------------------------------------------------------------------- #
def _user_query():
    """
    带角色预加载的查询。

    必须 `selectinload(SysUser.role)`：`SysUser.role` 是懒加载关系，在异步
    Session 里访问未加载的关系会抛 `MissingGreenlet`（异步场景下无法隐式
    发起 IO）。这里一次性把角色查出来，后续 `user.role` 是普通属性访问。
    """
    return select(SysUser).options(selectinload(SysUser.role))


def role_name_of(user: SysUser) -> str | None:
    """取用户角色名。未加载出角色或未分配角色时返回 None。"""
    role = user.role
    return role.role_name if role is not None else None


def permissions_of(user: SysUser) -> set[str]:
    """
    取用户的最终权限集合。

    以数据库 `sys_role.permissions` 为准（决策 3）；为空时回落到静态角色映射，
    回落时记 debug 日志 —— 云库里 `permissions` 列还没填数据时，鉴权不会
    整个失效，但排查「为什么他有这个权限」时需要知道发生了回落。
    """
    role_name = role_name_of(user)
    raw = user.role.permissions if user.role is not None else None
    permissions = effective_permissions(role_name, raw)
    if not raw and permissions:
        logger.debug(
            "角色 %s 的 permissions 为空，已回落到静态权限映射（%d 项）",
            role_name,
            len(permissions),
        )
    return permissions


async def get_user_by_id(db: AsyncSession, user_id: int) -> SysUser | None:
    """按主键取用户（含角色）。"""
    result = await db.execute(_user_query().where(SysUser.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> SysUser | None:
    """
    按登录名取用户（含角色）。

    用 `scalar_one_or_none()` 而不是 `first()`：`sys_user.username` 上有唯一
    约束（ORM `unique=True` + 初始迁移的 UNIQUE），出现多行说明云库违反了自身
    约束。此时**宁可抛 MultipleResultsFound 变成 500**，也不要静默挑一行登录 ——
    「以哪个身份登录」不能由行顺序决定。该 500 会暴露数据问题，
    而幂等索引迁移里对 `uk_username` 的检查可以用来定位它。
    """
    result = await db.execute(_user_query().where(SysUser.username == username))
    return result.scalar_one_or_none()


# --------------------------------------------------------------------------- #
# 登录
# --------------------------------------------------------------------------- #
async def authenticate(
    db: AsyncSession, token_store: TokenStore, *, username: str, password: str
) -> SysUser:
    """
    校验账号密码，返回**已通过全部校验**的用户。

    校验顺序是刻意的：密码 → 状态 → 角色。
    状态与角色放在密码之后，是为了不让「没有密码的人」通过错误码枚举出
    系统里有哪些账号被禁用、哪些账号没分配角色（40108 / 40302 只在
    密码正确时才可能出现）。

    失败时统计风控计数并抛 `CredentialsInvalidError`（文案不区分
    「用户不存在」与「密码错误」，同理防枚举）。
    """
    if await risk_service.is_locked_out(token_store, username):
        logger.warning("登录被拒：账号处于临时锁定状态 username=%s", username)
        raise AccountLockedError()

    user = await get_user_by_username(db, username)
    if user is None:
        # 走一遍等价的 bcrypt 运算，让「用户不存在」与「密码错误」耗时接近。
        # 否则响应耗时的差异本身就泄露了账号是否存在。
        await fake_verify_password()
        await risk_service.record_failure(token_store, username)
        raise CredentialsInvalidError()

    if not await verify_password(password, user.password):
        attempts = await risk_service.record_failure(token_store, username)
        logger.info(
            "登录失败：密码错误 username=%s 连续失败=%s",
            username,
            attempts,
            extra={"extra_fields": {"username": username, "failedAttempts": attempts}},
        )
        raise CredentialsInvalidError()

    if user.status != USER_STATUS_ACTIVE:
        logger.info("登录被拒：账号已禁用 userId=%s", user.id)
        raise UserDisabledError()

    if role_name_of(user) is None:
        logger.warning("登录被拒：账号未分配角色 userId=%s", user.id)
        raise RoleMissingError()

    return user


async def _read_version(token_store: TokenStore, user_id: int) -> int:
    """
    读取令牌版本号。Redis 不可用时返回 0 并记 warning（决策 7：登录优先保可用）。

    返回 0 的后果：这次会话签出的令牌 `ver=0`。若该用户此前被强制下线过
    （Redis 里的版本号 > 0），Redis 恢复后这个令牌的版本对不上，续期会被拒 ——
    这正是我们想要的保守结果。
    """
    try:
        return await token_store.get_version(user_id)
    except RedisUnavailableError as exc:
        logger.warning("读取令牌版本失败，本次按 0 处理（userId=%s）：%s", user_id, exc)
        return 0


async def _register_refresh(
    token_store: TokenStore, user_id: int, jti: str, role_name: str, version: int
) -> None:
    """
    登记 refreshToken 白名单。失败只记 warning（决策 7）。

    失败后果要讲清楚：这次登录仍然成功、accessToken 正常可用，但这个
    refreshToken **无法续期**（白名单里没有它，refresh 会判定为已失效）。
    用户表现为「用着用着到 30 分钟后突然要重新登录」，而不是登录不了。
    这是可用性与安全之间的取舍：若把登记失败升级为登录失败，
    Redis 一挂整个系统就没人能登录了。
    """
    try:
        await token_store.register_refresh(
            user_id,
            jti,
            role=role_name,
            ttl_seconds=_refresh_ttl_seconds(),
            version=version,
        )
    except RedisUnavailableError as exc:
        logger.warning(
            "登记 refreshToken 白名单失败：本次登录仍成功，但该令牌无法续期（userId=%s）：%s",
            user_id,
            exc,
        )


async def login(
    db: AsyncSession,
    token_store: TokenStore,
    *,
    username: str,
    password: str,
    client_ip: str | None = None,
) -> LoginOut:
    """
    登录：校验账号密码并签发令牌对。

    返回文档 5.3 约定的 `{accessToken, refreshToken, role}`。
    """
    user = await authenticate(db, token_store, username=username, password=password)

    # 走到这里密码已经对了，可以安全地做风控判定与计数清零
    await risk_service.clear_on_success(token_store, username)
    await risk_service.assess_login_risk(token_store, user.id, username, client_ip)

    role_name = role_name_of(user)
    if role_name is None:
        # authenticate() 已用同样的条件拦过一次，这里是防御性重复检查：
        # 不用 assert，因为 assert 在 `python -O` 下会被整个删掉，
        # 届时 role_name 会以 None 流进 JWT，等于签出一个没有角色的令牌。
        raise RoleMissingError()

    version = await _read_version(token_store, user.id)

    access_token, _ = create_token(user.id, role_name, TokenType.ACCESS, _access_expires(), version)
    refresh_token, refresh_payload = create_token(
        user.id, role_name, TokenType.REFRESH, _refresh_expires(), version
    )
    await _register_refresh(token_store, user.id, refresh_payload.jti, role_name, version)

    logger.info(
        "登录成功 userId=%s username=%s role=%s",
        user.id,
        user.username,
        role_name,
        extra={"extra_fields": {"userId": user.id, "role": role_name}},
    )
    return LoginOut(access_token=access_token, refresh_token=refresh_token, role=role_name)


# --------------------------------------------------------------------------- #
# 续期
# --------------------------------------------------------------------------- #
async def refresh(db: AsyncSession, token_store: TokenStore, *, refresh_token: str) -> TokenPairOut:
    """
    用 refreshToken 换取新的令牌对（轮换）。

    与 `login` 不同，本函数在 Redis 不可用时**严格失败**（决策 7）：
    `get_version` 与 `rotate_refresh` 抛出的 `RedisUnavailableError` 直接向上
    传播，由异常处理器转成 50301。绝不能「读不到就当作有效」——
    那会让登出与强制下线同时失效。
    """
    payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)

    # 版本号校验 = 强制下线检查。refresh 不递增版本，只有 logout/强制下线才递增。
    current_version = await token_store.get_version(payload.user_id)
    if payload.version != current_version:
        logger.warning(
            "续期被拒：令牌版本不符（该账号已被强制下线）userId=%s tokenVer=%s currentVer=%s",
            payload.user_id,
            payload.version,
            current_version,
        )
        raise TokenRevokedError()

    user = await get_user_by_id(db, payload.user_id)
    if user is None:
        logger.info("续期被拒：账号已不存在 userId=%s", payload.user_id)
        raise UnauthorizedError("账号已不存在，请重新登录")
    if user.status != USER_STATUS_ACTIVE:
        logger.info("续期被拒：账号已禁用 userId=%s", payload.user_id)
        raise UserDisabledError()

    role_name = role_name_of(user)
    if role_name is None:
        logger.warning("续期被拒：账号未分配角色 userId=%s", payload.user_id)
        raise RoleMissingError()

    access_token, _ = create_token(
        user.id, role_name, TokenType.ACCESS, _access_expires(), current_version
    )
    new_refresh, new_payload = create_token(
        user.id, role_name, TokenType.REFRESH, _refresh_expires(), current_version
    )

    # 先造令牌再轮换：轮换被拒时这两个令牌没有被返回，而它们也没有进白名单，
    # 因此即使泄漏也无法使用，不需要额外回收。
    result = await token_store.rotate_refresh(
        payload.user_id,
        payload.jti,
        new_payload.jti,
        role=role_name,
        ttl_seconds=_refresh_ttl_seconds(),
        version=current_version,
        grace_seconds=settings.JWT_REFRESH_GRACE_SECONDS,
    )

    if not result.ok:
        # 已登出 / 已被轮换过 / 已过期清理 / 被窃取后重放 —— 这几种情形在
        # 只有白名单的情况下形态相同，无法区分，一律拒绝。记 WARN 保留审计线索
        # （不吊销整个令牌家族的原因见 app/core/token_store.py 的模块说明）。
        logger.warning(
            "续期被拒：refreshToken 不在白名单 userId=%s jti=%s",
            payload.user_id,
            payload.jti,
            extra={"extra_fields": {"userId": payload.user_id, "jti": payload.jti}},
        )
        raise RefreshTokenInvalidError()

    if result.outcome is RotationOutcome.GRACE_REPLAY:
        # 正常情况：前端并发 401 重试，第一个请求轮换成功，其余命中宽限期。
        # 异常情况：旧 token 被窃取后重放。两者无法区分，因此只记日志不阻断。
        logger.warning(
            "续期命中宽限期（同一 refreshToken 被重复使用）userId=%s jti=%s。"
            "若前端未实现单例 Promise 去重刷新，请按 docs/api.md 的要求整改。",
            payload.user_id,
            payload.jti,
        )

    logger.info("续期成功 userId=%s outcome=%s", payload.user_id, result.outcome.value)
    return TokenPairOut(access_token=access_token, refresh_token=new_refresh)


# --------------------------------------------------------------------------- #
# 登出
# --------------------------------------------------------------------------- #
async def logout(
    token_store: TokenStore, *, user_id: int, refresh_token: str | None = None
) -> None:
    """
    登出。

    规则（一句话）：**能确定具体会话就只吊销它，否则吊销该用户的全部会话。**

    | `refreshToken` 的情况                    | 行为                      |
    | ---------------------------------------- | ------------------------- |
    | 缺失 / 解析失败 / 已过期 / 类型不对       | `revoke_all(user_id)`     |
    | 有效，但属于**别的用户**                  | 抛 `ForbiddenError`       |
    | 有效且属于本人                            | `revoke_refresh` 仅该会话 |

    第二行是必须的：不加这条检查，任何人拿自己的 accessToken + 别人的
    refreshToken 就能把别人踢下线（跨用户会话吊销）。

    其余情况一律吊销全部会话，是刻意的「fail-safe 而非 fail-open」：
    登出的语义就是「让我失去访问能力」，在无法精确定位会话时，
    多踢几个自己的会话是可接受的，而返回成功却什么都没吊销是不可接受的。

    ⚠️ 已知限制：accessToken 是无状态的，登出后它仍能用到自然过期
    （≤ `JWT_EXPIRE_MINUTES`，默认 30 分钟）。详见模块文档的「强制下线的时间窗」。
    """
    if refresh_token:
        try:
            payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)
        except BizError as exc:
            # 只捕 BizError（decode_token 只会抛 TokenExpired/TokenInvalid/
            # TokenTypeInvalid 三种，都是 BizError 子类）。刻意不捕 Exception ——
            # 那会把代码缺陷也伪装成「令牌不可用」而静默放过。
            logger.info(
                "登出：refreshToken 不可用（%s），退化为吊销全部会话 userId=%s",
                type(exc).__name__,
                user_id,
            )
        else:
            if payload.user_id != user_id:
                # 不记 jti：避免把别人的会话标识写进日志
                logger.warning(
                    "登出被拒：refreshToken 属于其他用户 tokenUserId=%s currentUserId=%s",
                    payload.user_id,
                    user_id,
                )
                raise ForbiddenError("不能吊销其他用户的会话")
            await token_store.revoke_refresh(user_id, payload.jti)
            logger.info("登出成功（仅本次会话）userId=%s", user_id)
            return

    version = await token_store.revoke_all(user_id)
    logger.info("登出成功（全部会话，版本号 -> %s）userId=%s", version, user_id)


# --------------------------------------------------------------------------- #
# 用户信息
# --------------------------------------------------------------------------- #
def build_user_info(user: SysUser) -> UserInfoOut:
    """
    构造 `GET /auth/info` 的出参。

    `permissions` 排序后输出：集合的迭代顺序在不同进程间不稳定，排序能让
    前端缓存与接口测试的对比结果稳定。若角色权限是通配符 `*`，
    这里会输出 `["*"]` —— 前端应把 `*` 视为「拥有全部权限」
    （见 app/core/permissions.py），种子数据刻意不使用它。
    """
    return UserInfoOut(
        id=user.id,
        username=user.username,
        role=role_name_of(user),
        avatar=user.avatar,
        permissions=sorted(permissions_of(user)),
    )
