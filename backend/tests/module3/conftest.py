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

from .helpers import MOCK_USER_ID


def _seed_spaces() -> list[SpaceResource]:
    """种子场地：2 个（id 固定，便于用例断言）。

    必须每个用例现构造：ORM 实例跨用例复用会变为 detached，再次 add 不会重新插入。
    """
    return [
        SpaceResource(
            id=1, space_name="会议室A", space_type=1, capacity=10, location="3F",
            open_start_time=time(8, 0), open_end_time=time(22, 0), status=1,
        ),
        SpaceResource(
            id=2, space_name="展厅B", space_type=2, capacity=40, location="1F",
            open_start_time=time(8, 0), open_end_time=time(22, 0), status=1,
        ),
    ]


def _seed_devices() -> list[DeviceResource]:
    """种子设备：2 台。"""
    return [
        DeviceResource(
            id=1, device_name="投影仪", device_type="投影", device_status=1,
            total_count=1, available_count=1,
        ),
        DeviceResource(
            id=2, device_name="音响系统", device_type="音频", device_status=1,
            total_count=1, available_count=1,
        ),
    ]


def _seed_users():
    """种子用户：1 个。

    团队的 `reserve_order.user_id` / `notify_message.receiver_id` 声明了指向
    `sys_user.id` 的真外键（与云库一致）。SQLite 默认不强制外键，但灌上更贴近真库，
    也能在有人打开 `PRAGMA foreign_keys` 时不让写路径莫名失败。
    """
    from app.models import SysUser

    return [
        SysUser(
            id=MOCK_USER_ID, username="zhangsan",
            password="$2b$12$WPAzHZb7EolabiZR5BLNMeZs1iYXMklXA9S0GRF4B4soj3Jmh45N.",
            role_id=None, status=1,
        ),
    ]


@pytest.fixture(autouse=True)
async def _fresh_db():
    """每个用例重建表并灌入种子数据，保证用例之间互不干扰（§10.2）。"""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        session.add_all(_seed_users())
        session.add_all(_seed_spaces())
        session.add_all(_seed_devices())
        await session.commit()

    yield


@pytest.fixture
async def client():
    """异步 ASGI 客户端，默认携带 mock 身份头 `X-User-Id`（§5.1）。

    需要切换身份时按请求覆盖：`client.get(url, headers={"X-User-Id": "2"})`。
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-User-Id": str(MOCK_USER_ID)},
    ) as c:
        yield c


@pytest.fixture
async def db_session():
    """直连测试库的会话，用于构造接口无法产生的数据（如越权消息、重叠订单）。"""
    async with AsyncSessionLocal() as session:
        yield session
