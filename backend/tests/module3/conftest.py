"""模块 3 夹具：异步 ASGI 客户端 + 种子数据（§3.7 / §6.8 / §10.2）。

测试库的隔离（把 `DATABASE_URL` 指向临时 SQLite）在**顶层** `tests/conftest.py` 完成 ——
那段必须先于任何 `app` 导入执行。这里只负责建表、灌种子与提供客户端。
"""

from datetime import time

import httpx
import pytest

from app import models  # noqa: F401  确保模型注册后再建表
from app.core.database import AsyncSessionLocal, Base, async_engine
from app.main import app
from app.models import DeviceResource, SpaceResource

from .helpers import MOCK_USER_ID, OTHER_USER_ID, ROLE_NAME, auth_headers

#: 种子角色的主键，供 `sys_user.role_id` 引用
ROLE_ID = 1


def _seed_spaces() -> list[SpaceResource]:
    """种子场地：2 个（id 固定，便于用例断言）。

    必须每个用例现构造：ORM 实例跨用例复用会变为 detached，再次 add 不会重新插入。
    """
    return [
        SpaceResource(
            id=1,
            space_name="会议室A",
            space_type=1,
            capacity=10,
            location="3F",
            open_start_time=time(8, 0),
            open_end_time=time(22, 0),
            status=1,
        ),
        SpaceResource(
            id=2,
            space_name="展厅B",
            space_type=2,
            capacity=40,
            location="1F",
            open_start_time=time(8, 0),
            open_end_time=time(22, 0),
            status=1,
        ),
    ]


def _seed_devices() -> list[DeviceResource]:
    """种子设备：2 台。"""
    return [
        DeviceResource(
            id=1,
            device_name="投影仪",
            device_type="投影",
            device_status=1,
            total_count=1,
            available_count=1,
        ),
        DeviceResource(
            id=2,
            device_name="音响系统",
            device_type="音频",
            device_status=1,
            total_count=1,
            available_count=1,
        ),
    ]


def _seed_role():
    """种子角色：`sys_user.role_id` 指向它。

    必须有，且**必须连用户一起灌**（见 `_seed_users`）：`get_current_user`
    在 `role_name_of(user) is None` 时抛 `RoleMissingError`（403 / 40302），
    只灌用户不灌角色会让每一条用例都变成 403。
    """
    from app.models import SysRole

    return [SysRole(id=ROLE_ID, role_name=ROLE_NAME, permissions=["*"])]


def _seed_users():
    """种子用户：2 个（本人 + 越权用例用的另一人），都挂在 `_seed_role` 的角色上。

    团队的 `reserve_order.user_id` / `notify_message.receiver_id` 声明了指向
    `sys_user.id` 的真外键（与云库一致）。SQLite 默认不强制外键，但灌上更贴近真库，
    也能在有人打开 `PRAGMA foreign_keys` 时不让写路径莫名失败。

    第二个人不只是为了越权用例：`services/order_service.create_order` 会先校验
    预约人存在（云库上 user_id 是真外键），只种一个人的话，「替他人下单」这条
    路径会因为查不到人而失败，测出来的就不是越权行为了。
    """
    from app.models import SysUser

    password = "$2b$12$WPAzHZb7EolabiZR5BLNMeZs1iYXMklXA9S0GRF4B4soj3Jmh45N."
    return [
        SysUser(id=MOCK_USER_ID, username="zhangsan", password=password, role_id=ROLE_ID, status=1),
        SysUser(id=OTHER_USER_ID, username="lisi", password=password, role_id=ROLE_ID, status=1),
    ]


@pytest.fixture(autouse=True)
async def _fresh_db():
    """每个用例重建表并灌入种子数据，保证用例之间互不干扰（§10.2）。"""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        # 角色必须先于用户：sys_user.role_id 指向它
        session.add_all(_seed_role())
        await session.flush()
        session.add_all(_seed_users())
        session.add_all(_seed_spaces())
        session.add_all(_seed_devices())
        await session.commit()

    yield


@pytest.fixture
async def client():
    """异步 ASGI 客户端，默认以 `MOCK_USER_ID` 的真实 JWT 登录（§5.1）。

    需要切换身份时按请求覆盖 `headers=auth_headers(OTHER_USER_ID)` ——
    注意 `headers=` 是**整体替换**客户端默认头，不是合并，所以覆盖时
    `Authorization` 必须一并给出（`auth_headers()` 就负责这件事）。
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers=auth_headers(MOCK_USER_ID),
    ) as c:
        yield c


@pytest.fixture
async def db_session():
    """直连测试库的会话，用于构造接口无法产生的数据（如越权消息、重叠订单）。"""
    async with AsyncSessionLocal() as session:
        yield session
