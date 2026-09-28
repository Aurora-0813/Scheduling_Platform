"""
数据库引擎与会话管理

本模块提供两套引擎，边界必须分清：

- **同步引擎**（`sync_engine` / `SyncSessionLocal`，驱动 pymysql）
  —— 仅供 Alembic 迁移使用。Alembic 的迁移环境是同步的，见 alembic/env.py。
  这两个名字**惰性创建**（首次访问才建引擎），原因见下方注释：
  在导入时创建会把 pymysql 变成应用与离线测试的硬依赖。
- **异步引擎**（`async_engine` / `AsyncSessionLocal`，驱动 asyncmy）
  —— 应用运行时一律走这一套。开发流程.md 3.4 禁止同步驱动，
  针对的就是业务链路；任何 API / service / Agent 代码都不得使用同步引擎。

会话获取有三条路径，按调用场景选：
- `get_db()`      请求级依赖注入（FastAPI Depends）
- `session_scope()` 后台任务 / 定时扫描 / Agent Tool 用的独立会话
- `with_session`  装饰器，让 service 函数同时兼容上面两种调用方
"""
from __future__ import annotations

import functools
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, TypeVar

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类，Alembic 靠 Base.metadata 识别所有模型"""


# ---------- 同步引擎（仅供 Alembic，惰性创建） ----------
# 驱动是 pymysql，连接串由 settings.sync_database_url 拼出。
# 这里不设连接池上限：迁移是一次性任务，用完即退。
#
# ⚠️ 刻意**不在模块导入时创建**，而是首次访问 `sync_engine` 时才建（见 __getattr__）。
# 原因是 create_engine() 在调用那一刻就按连接串解析 DBAPI，而这条串用的
# 是同步驱动（唯一拼装处见 core/config.py 的 sync_database_url），
# 一旦写在模块顶层，「import app.core.database」就要求本机装了 pymysql。
# 实测过后果：未装 pymysql 的环境下，7 个测试模块在收集阶段直接
# ModuleNotFoundError: No module named 'pymysql'，整套离线测试跑不起来。
# 而按 3.4 的本意，业务链路本就不该碰同步驱动，pymysql 不应成为
# 应用运行与离线测试的依赖。
#
# 惰性化之后：
#   - 应用启动、跑单元测试 → 完全不碰 pymysql
#   - `alembic upgrade head` → alembic/env.py 用 engine_from_config +
#     settings.sync_database_url 自建引擎，本就不读这两个变量；
#     真要有人手动用它们，那时才需要 pymysql（它属于迁移依赖）
_sync_engine: Engine | None = None
_SyncSessionFactory: sessionmaker | None = None


def _get_sync_engine() -> Engine:
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(
            settings.sync_database_url,
            echo=settings.DEBUG,           # 开发时打印 SQL
            pool_pre_ping=True,            # 使用前先 ping
            pool_recycle=3600,             # 1 小时回收连接
        )
    return _sync_engine


def _get_sync_sessionmaker() -> sessionmaker:
    global _SyncSessionFactory
    if _SyncSessionFactory is None:
        _SyncSessionFactory = sessionmaker(
            bind=_get_sync_engine(),
            autoflush=False,
            expire_on_commit=False,
        )
    return _SyncSessionFactory


def __getattr__(name: str) -> Any:
    """
    模块级惰性属性（PEP 562）。

    保持 `sync_engine` / `SyncSessionLocal` 与原版同名可用，
    但把 pymysql 的解析推迟到真正访问它们的时候。

    注意这两个名字**不会**被写进模块字典（写的是 `_sync_engine`），
    因此 `vars(app.core.database)` 里永远没有 `sync_engine` ——
    tests/unit/test_config.py 正是靠这一点断言引擎没有被提前创建。
    """
    if name == "sync_engine":
        return _get_sync_engine()
    if name == "SyncSessionLocal":
        return _get_sync_sessionmaker()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------- 异步引擎（应用运行时） ----------
async_engine = create_async_engine(
    settings.database_url,
    echo=settings.DEBUG,
    # 连接池刻意保守：目标部署环境是 2 核 2G，
    # 10+20 会在并发请求下把连接数顶到 MySQL 的 max_connections 附近
    pool_size=5,
    max_overflow=10,
    # MySQL 侧空闲断连后自动重连，避免取到失效连接
    pool_pre_ping=True,
    # MySQL 默认 wait_timeout 8 小时，回收周期必须小于它
    pool_recycle=3600,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    # 关掉 autoflush：本项目的写操作由 services 层显式 flush/commit，
    # 隐式 flush 会在「先占去重名额再写库、失败则归还」这类流程中
    # 提前落库，破坏事务边界的可控性
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """
    FastAPI 依赖注入用的请求级会话。

    事务边界沿用主干口径：请求正常结束时提交，异常回滚。
    这是主干的既有契约，模块 7 合并时**未改动**它 —— 若把这里的
    提交去掉，将来任何用 `Depends(get_db)` 写库的端点都会静默丢数据
    （关闭会话即隐式回滚，不报错），改动收益为零而风险不为零。

    ⚠️ 模块 7 的两个端点**不使用本依赖**：`api/v1/conflict.py` 与
    `api/v1/notify.py` 中途要等大模型 3~20 秒，不能一直握着连接，
    它们走 `session_scope()` 并自行显式 commit。所以本函数的提交语义
    与模块 7 的三段式去重（占名额 → 写库 → 失败归还）**互不影响**。
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """
    后台任务 / LangChain Tool 用的独立会话。

    定时扫描与 Tool 都不在请求上下文里，拿不到 get_db，
    必须自建会话；同时避免它们在函数签名上暴露 AsyncSession。
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


F = TypeVar("F", bound=Callable[..., Any])


def with_session(fn: F) -> F:
    """
    让同一个 service 函数既能被请求复用外部会话，也能被 Tool / 后台任务调用。

    满足开发流程.md 9.3「Agent 只能通过 Tool 调用 services 层」且
    「Tool 不直接操作数据库」：Tool 只写 session 参数为可选，
    由本装饰器决定是自建会话还是复用调用方传入的会话。
    """

    @functools.wraps(fn)
    async def wrapper(*args: Any, session: AsyncSession | None = None, **kwargs: Any) -> Any:
        if session is not None:
            return await fn(*args, session=session, **kwargs)
        async with session_scope() as own_session:
            return await fn(*args, session=own_session, **kwargs)

    return wrapper  # type: ignore[return-value]


async def dispose_engine() -> None:
    """
    应用关闭时释放连接池。

    同步引擎只在**确实被创建过**时才释放：应用运行时不会碰它，
    不能为了 dispose 反而去创建一次（那会把 pymysql 重新拉回启动路径）。
    """
    await async_engine.dispose()
    if _sync_engine is not None:
        _sync_engine.dispose()
