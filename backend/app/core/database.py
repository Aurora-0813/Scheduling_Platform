"""数据库连接模块（开发流程 §3.4 / §7.3）。

同时提供：
- 同步引擎：给 Alembic 迁移和同步脚本用
- 异步引擎：给 FastAPI 运行时用

与团队公用 `backend/app/core/database.py` 对齐：导出 `async_engine` / `sync_engine` /
`AsyncSessionLocal` / `SyncSessionLocal` / `Base` / `get_db`，采用绝对导入
`from app.core.config import settings`，引擎参数 `pool_size=5`、`max_overflow=10`、
`pool_pre_ping`、`pool_recycle=3600`、`echo=settings.DEBUG`。
（SQLite 不支持连接池参数，自测覆盖时自动跳过。）

本模块在此之上**额外保留两处临时补丁**，二者都不改变上述对团队的接口，
均以下方 `[临时补丁 N/2]` 标记标明，**集成组在公用基线修复后应移除**：
1. `PK_TYPE` —— SQLite 下主键降级为 INTEGER（原因见下方常量注释）；
2. `patch_asyncmy_ping` —— 修复团队版 `pool_pre_ping` + asyncmy 的 `ping` 崩溃
   （完整触发链见下方补丁注释，已作为问题反馈给集成组）。

`get_db` 必须为 `async def`：请求结束提交、异常回滚、最终关闭。
"""
from sqlalchemy import BigInteger, Integer, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

# ---------- [临时补丁 1/2] SQLite 主键自增（团队基线无此常量，可移除） ----------
# 主键类型：MySQL 下为 BIGINT（与公用 backend 及云库一致，§6.3）。
# SQLite 下退化为 INTEGER —— SQLite 只有 `INTEGER PRIMARY KEY` 是 rowid 别名才会自增，
# `BIGINT PRIMARY KEY` 不会。§13.1 应急用本地 SQLite 镜像演示依赖这一降级，
# 本模块的用例也跑在临时 SQLite 上（见 tests/module3/conftest.py）。
PK_TYPE = BigInteger().with_variant(Integer, "sqlite")

# SQLite 不接受 MySQL 风格的连接池参数，且需关闭同线程校验
_is_sqlite = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False} if _is_sqlite else {}
pool_args = {} if _is_sqlite else {"pool_size": 5, "max_overflow": 10, "pool_recycle": 3600}


# ---------- [临时补丁 2/2] asyncmy 与 pool_pre_ping 的兼容补丁（真库启动必须） ----------
# 仅本模块打；公用 backend 未修，见 docs/公用后端问题反馈.md 第五节。
# 待集成组在公用基线修好后，删除本函数与「导入时接线」那段 if，回归团队原样。
# 触发链（SQLAlchemy 2.0.35 + asyncmy 0.2.10 + PyMySQL 1.2.3，已逐环验证）：
#   `MySQLDialect_asyncmy(MySQLDialect_pymysql)` 继承自 pymysql 方言，因此沿用其
#   `do_ping()`；该方法用 `_send_false_to_ping` 去 introspect **pymysql** 的
#   `Connection.ping` 签名来决定传不传参。新版 PyMySQL 是 `ping(self, reconnect=False)`
#   （默认值由 True 改为 False），判定结果变为 False，于是走无参分支
#   `dbapi_connection.ping()`。而 asyncmy 自己的包装器是 `ping(self, reconnect)`
#   —— reconnect 为**必传**参数，两者对不上，报：
#       TypeError: AsyncAdapt_asyncmy_connection.ping() missing 1 required
#                  positional argument: 'reconnect'
# 该 ping 只由 `pool_pre_ping` 在检查**复用**连接时触发，故现象是同一接口
# 200/500 交替（新连接不 ping、复用连接必炸）。其余用例跑在临时 SQLite（aiosqlite）上，
# 走的是另一套 `do_ping`，因此整套用例全绿也照不出这个问题——由
# `tests/module3/test_asyncmy_ping_compat.py` 单独盯住。
# 修法：给包装器的 reconnect 补上默认值 False —— 与 SQLAlchemy 想表达的
# “ping 一下、但不要自动重连”语义一致；保留 pool_pre_ping 不降级，
# 不动 §3.1 锁定版本，也不影响团队公用 backend 的配置。
# 团队版公用 backend 目前**没有**这个补丁，详见 docs/公用后端问题反馈.md 第五节。
def patch_asyncmy_ping() -> bool:
    """给 asyncmy 连接包装器的 `ping` 补上 `reconnect` 默认值（幂等）。

    返回本次是否真的打了补丁：False 表示上游已自带默认值（或已打过），无需包装。
    用例默认跑在 SQLite 上、走不到这条路径，所以由
    `tests/module3/test_asyncmy_ping_compat.py` 单独把它固化成断言。
    """
    from sqlalchemy.dialects.mysql.asyncmy import (
        AsyncAdapt_asyncmy_connection as _AsyncmyConnection,
    )

    # 上游若已补默认值（或日后升级修好）则跳过，避免无谓包装
    if _AsyncmyConnection.ping.__defaults__ == (False,):
        return False

    _asyncmy_ping = _AsyncmyConnection.ping

    def _ping(self, reconnect=False):
        """兼容版 ping：reconnect 可选，缺省等价于 False（不自动重连）。"""
        return _asyncmy_ping(self, reconnect)

    # AsyncAdaptFallback_asyncmy_connection 继承本类，一并生效
    _AsyncmyConnection.ping = _ping
    return True


if settings.database_url.startswith("mysql+asyncmy"):
    patch_asyncmy_ping()


class Base(DeclarativeBase):
    """所有 ORM 模型的基类，Alembic 靠 Base.metadata 识别所有模型"""
    pass


# ---------- 同步引擎 ----------
# 用于 Alembic 迁移、同步脚本等场景，驱动是 pymysql
sync_engine = create_engine(
    settings.sync_database_url,    # 从 .env 拼接出来的同步连接串
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
    connect_args=connect_args,
    pool_pre_ping=True,
    **pool_args,
)

# 异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


async def get_db():
    """FastAPI 依赖注入用。

    每个请求一个异步数据库会话，正常结束提交、异常回滚、最终关闭。
    路由内如需读取数据库侧生成的字段值（如 `create_time`），显式 `commit` 后
    `refresh` 即可。
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
