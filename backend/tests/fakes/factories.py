"""
测试对象工厂：造角色、造用户、造令牌对

为什么要有工厂
--------------
认证测试需要一个「密码能校验通过」的用户。若每个用例自己写
`hash_password(...)` 再拼 `SysUser(...)`，会出现三种典型问题：
1. 有人忘了 `await hash_password`，把明文写进 `password` 列，用例照样绿，
   但它其实没在测 bcrypt 路径；
2. 有人忘了 `selectinload` 的关系需要 `refresh`，退出用例时才炸 MissingGreenlet；
3. 角色权限清单写得五花八门，`permissions` 列时而 `[]` 时而 `None`，
   鉴权用例的结果取决于谁最后改的。

集中到这里之后，这些约定只有一份。

密码与成本
----------
`DEFAULT_PASSWORD` 是**测试专用**的假口令，不是任何真实账号的密码
（项目文档 9.4：禁止在代码里留存真实管理员密码）。
`tests/conftest.py` 已把 `BCRYPT_ROUNDS` 设为 4，哈希一次约 1 毫秒；
若沿用生产值 12，每个登录用例都要白等约 250 毫秒。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import ROLE_ADMIN, ROLE_USER, permissions_for_role
from app.core.security import hash_password
from app.models.system import SysRole, SysUser

__all__ = [
    "DEFAULT_PASSWORD",
    "ADMIN_PASSWORD",
    "create_role",
    "create_user",
    "create_user_with_raw_password",
    "create_admin",
    "create_multiple_users",
]

# 测试专用的占位口令。故意包含大小写、数字与符号，以便顺带覆盖
# 「口令里有特殊字符时不会在 JSON/日志里出问题」。
DEFAULT_PASSWORD = "Test@123456"
ADMIN_PASSWORD = "TestAdmin@123456"


async def create_role(
    session: AsyncSession,
    *,
    name: str = ROLE_ADMIN,
    permissions: Any = ...,
    commit: bool = True,
) -> SysRole:
    """
    创建角色。

    :param permissions: 写入 `sys_role.permissions` 的原始值。
        **默认（省略不传）**取 `app/core/permissions.py` 的静态映射，
        与种子数据的形态一致 —— 鉴权主路径（决策 3：以数据库为准）因此
        被真实覆盖。传 `None` 或 `[]` 可以构造「数据库没填权限」的场景，
        用于验证静态映射回落。
        传 dict/字符串等形态可用于验证 `normalize_permissions` 的容错。
    """
    if permissions is ...:
        permissions = list(permissions_for_role(name))

    role = SysRole(role_name=name, permissions=permissions)
    session.add(role)
    if commit:
        await session.commit()
    else:
        await session.flush()
    return role


async def create_user(
    session: AsyncSession,
    *,
    username: str = "admin",
    password: str = DEFAULT_PASSWORD,
    role: SysRole | None = None,
    status: int = 1,
    avatar: str | None = None,
    commit: bool = True,
) -> SysUser:
    """
    创建用户。

    `password` 传的是**明文**，由本函数负责哈希 —— 这样调用方不可能
    忘记哈希。若确实想构造「库里存着明文/坏哈希」的历史数据，
    请显式用 `create_user_with_raw_password()`（见下）。
    """
    hashed = await hash_password(password)
    return await _insert_user(
        session,
        username=username,
        hashed_password=hashed,
        role=role,
        status=status,
        avatar=avatar,
        commit=commit,
    )


async def create_user_with_raw_password(
    session: AsyncSession,
    *,
    username: str,
    raw_password_in_db: str | None,
    role: SysRole | None = None,
    status: int = 1,
    commit: bool = True,
) -> SysUser:
    """
    直接写入 `password` 列（不哈希）。仅用于构造**历史脏数据**：
    明文密码、空串、`None`、被截断的哈希。

    登录接口遇到这类数据必须返回 401 而不是 500（见
    `app.core.security.verify_password`），本函数就是用来验证这一点的。
    """
    return await _insert_user(
        session,
        username=username,
        hashed_password=raw_password_in_db,  # type: ignore[arg-type]
        role=role,
        status=status,
        avatar=None,
        commit=commit,
    )


async def _insert_user(
    session: AsyncSession,
    *,
    username: str,
    hashed_password: str | None,
    role: SysRole | None,
    status: int,
    avatar: str | None,
    commit: bool,
) -> SysUser:
    user = SysUser(
        username=username,
        password=hashed_password,
        role_id=role.id if role is not None else None,
        status=status,
        avatar=avatar,
    )
    session.add(user)
    if commit:
        await session.commit()
    else:
        await session.flush()
    return user


async def create_admin(
    session: AsyncSession,
    *,
    username: str = "admin",
    password: str = ADMIN_PASSWORD,
    commit: bool = True,
) -> tuple[SysUser, SysRole]:
    """一步造出「管理员账号 + 角色」。认证测试最常用的组合。"""
    role = await create_role(session, name=ROLE_ADMIN, commit=commit)
    user = await create_user(
        session, username=username, password=password, role=role, commit=commit
    )
    return user, role


async def create_multiple_users(
    session: AsyncSession, *, count: int, role: SysRole | None = None
) -> list[SysUser]:
    """批量造普通用户，用于分页、权限隔离、跨用户会话吊销等用例。"""
    if role is None:
        role = await create_role(session, name=ROLE_USER)
    return [
        await create_user(
            session,
            username=f"user{index + 1:03d}",
            password=DEFAULT_PASSWORD,
            role=role,
            commit=True,
        )
        for index in range(count)
    ]
