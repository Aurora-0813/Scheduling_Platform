"""
数据库连接模块

项目文档 3.4：统一使用异步驱动 `asyncmy`，禁止使用同步驱动 PyMySQL / mysqlclient。
因此本模块**只提供异步引擎与异步会话**，不提供同步引擎。

（历史说明：本模块原先同时提供同步引擎供 Alembic 使用。为满足 3.4 的硬约束，
已移除同步引擎，Alembic 亦改为全异步迁移，见 `alembic/env.py`。）
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。Alembic 依靠 Base.metadata 识别全部模型。"""


async_engine = create_async_engine(
    settings.database_url,
    echo=settings.SQL_ECHO,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600,
    # 建连超时。不设时隧道未启动 / 云库不可达要等操作系统的 TCP 超时，
    # 表现为进程启动卡住、`GET /ready` 长时间无响应。
    # `connect_timeout` 是 asyncmy 的参数，因此只能走 connect_args。
    connect_args={"connect_timeout": settings.DB_CONNECT_TIMEOUT},
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 依赖注入用：每个请求一个异步数据库会话。

    ⚠️ 本依赖只负责「异常回滚」与「关闭会话」，**不负责提交**。

    项目文档 5.5 要求资源锁定必须在单个事务内完成
    `BEGIN → SELECT ... FOR UPDATE → 校验 → 插入 → COMMIT`。
    若由依赖在请求末尾兜底提交，事务边界与行锁的持有范围就不在业务层手中，
    第 3/4 步校验失败时无法可靠地放弃整个事务。

    因此：**`services/` 层必须在业务结尾显式 `await session.commit()`**。
    忘记提交**不会报错**，但数据不会落库 —— 这是本项目最容易踩的坑，
    详见 docs/开发流程说明文档.md 的「事务边界」一节。
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        # 此处刻意没有 commit，见上方说明。
