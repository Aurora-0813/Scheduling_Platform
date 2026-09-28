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


# ⚠️ 异步引擎**故意不设 `pool_pre_ping`**，不是漏写。TODO(集成组)：方言缺陷修好后加回来。
#
#    SQLAlchemy 2.0.35 的 `MySQLDialect_asyncmy` 基类是 `MySQLDialect_pymysql`
#    （MRO 实测：MySQLDialect_asyncmy → MySQLDialect_pymysql → MySQLDialect_mysqldb → …），
#    而它**没有覆盖** `do_ping`（实测 `MySQLDialect_asyncmy.do_ping.__qualname__`
#    仍是 `MySQLDialect_pymysql.do_ping`），于是走的是 pymysql 那一份：
#        conn.ping(False) if self._send_false_to_ping else conn.ping()
#    pymysql 自己的 `Connection.ping(self, reconnect=False)` 有默认值，所以无事；
#    而 asyncmy 的 DBAPI 适配层是 `AsyncAdapt_asyncmy_connection.ping(self, reconnect)`
#    （`sqlalchemy/dialects/mysql/asyncmy.py:198`，**无默认值**，体内 `assert not reconnect`），
#    因此上面那句无参调用必抛：
#        TypeError: AsyncAdapt_asyncmy_connection.ping()
#                   missing 1 required positional argument: 'reconnect'
#
#    实测（2026-09-27，隧道通、库有数据）是**确定性**的，不是偶发：连续发查询，
#    **奇数次成功、偶数次必炸**，一次不多一次不少。影响面是**全后端**，不只 Agent 模块——
#    任何第二次复用连接的请求都会 500。两边 `requirements.txt` 都钉
#    `sqlalchemy==2.0.35` / `asyncmy==0.2.10`，说明本缺陷与依赖版本无关地存在。
#
#    2026-09-28 合并 `origin/main`（`9f30d3a`）时，正式版本文件仍是 `pool_pre_ping=True`，
#    故此处**未随「整份取正式版」一起替换**，保留本模块已验证的修复（见提交 f4d1a07）。
#    集成组修好方言缺陷后，删掉本段并打开下面这行即可。
async_engine = create_async_engine(
    settings.database_url,
    echo=settings.SQL_ECHO,
    pool_size=5,
    max_overflow=10,
    # pool_pre_ping=True,          # ← 见上方说明：方言缺陷修好前不要打开
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
