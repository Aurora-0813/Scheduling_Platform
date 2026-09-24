"""
数据库连接模块
同时提供：
- 同步引擎：给 Alembic 迁移和同步脚本用
- 异步引擎：给 FastAPI 运行时用
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类，Alembic 靠 Base.metadata 识别所有模型"""
    pass


# ---------- 同步引擎 ----------
# 用于 Alembic 迁移、同步脚本等场景，驱动是 pymysql
sync_engine = create_engine(
    settings.sync_database_url,   # 从 .env 拼接出来的同步连接串
    echo=settings.DEBUG,           # 开发时打印 SQL
    pool_pre_ping=True,            # 使用前先 ping
    pool_recycle=3600,             # 1 小时回收连接
)

# 同步会话工厂
SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autoflush=False,
    expire_on_commit=False,
)


# ---------- 异步引擎 ----------
# 用于 FastAPI 运行时，驱动是 asyncmy
async_engine = create_async_engine(
    settings.database_url,         # 从 .env 拼接出来的异步连接串
    echo=settings.DEBUG,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600,
)

# 异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    """
    FastAPI 依赖注入用
    每个请求一个异步数据库会话，自动提交、回滚、关闭
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()