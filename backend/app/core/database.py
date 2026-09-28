"""
数据库连接模块

项目文档 3.4：统一使用异步驱动 `asyncmy`，禁止使用同步驱动 PyMySQL / mysqlclient。
因此本模块**只提供异步引擎与异步会话**，不提供同步引擎。

（历史说明：本模块原先同时提供同步引擎供 Alembic 使用。为满足 3.4 的硬约束，
已移除同步引擎，Alembic 亦改为全异步迁移，见 `alembic/env.py`。）

本模块在团队基线上**额外保留两处补丁**，以下方 `[临时补丁]` 标记标明：

    `patch_asyncmy_ping`（临时）—— 修复团队版 `pool_pre_ping` 与 asyncmy 的
    `ping` 崩溃。完整触发链见下方补丁注释，已作为问题反馈给集成组，
    **集成组在公用基线修复后应移除**。

    SQLite 引擎参数适配（**不能移除**）—— 团队基线的 `create_async_engine`
    无条件传了 `pool_size` / `max_overflow` / `pool_recycle` / `connect_timeout`，
    而 SQLite（`§13.1` 的本地镜像库，以及**团队自己的 `tests/conftest.py`**）
    会选中 `NullPool`，这些参数一个都不接受，导入即抛
    `TypeError: Invalid argument(s) 'pool_size', 'max_overflow' sent to create_engine()`。
    这处适配不是为模块 3 打的：在新 main 上跑**任何**用例都会撞上，
    详见下方“SQLite 应急路径的引擎参数适配”一节。

⚠️ 关于 SQLite 下主键自增：团队基线的做法是在**测试进程内**把 BIGINT 编译成
INTEGER（见 `tests/conftest.py` 的 `SQLiteTypeCompiler` 垫片），因此模型一律用裸
`BigInteger`，本模块**不再提供** `PK_TYPE`。模块 3 此前那套 `PK_TYPE` 已随本轮
重组整体丢弃 —— 两种做法等价，团队的更集中。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


# ---------- [临时补丁] asyncmy 与 pool_pre_ping 的兼容补丁（连真库必须） ----------
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
    """所有 ORM 模型的基类。Alembic 依靠 Base.metadata 识别全部模型。"""


# ---------- SQLite 应急路径的引擎参数适配（必需，非临时补丁） ----------
# `settings.database_url` 有两条路径不是 mysql+asyncmy：`§13.1` 的本地 SQLite
# 应急镜像，以及**测试期 —— 团队自己的 `tests/conftest.py` 就把 DATABASE_URL
# 指向临时 SQLite**。
#
# SQLite 的 aiosqlite 方言在这种连接串下选中 `NullPool`，而 `NullPool.__init__`
# **不接受** pool_size / max_overflow / pool_recycle / connect_timeout。
# 无条件传过去的话，`app.core.database` 在被 import 的**那一刻**就抛：
#     TypeError: Invalid argument(s) 'pool_size', 'max_overflow' sent to create_engine()
# 症状是「任何一条用例都收集不到」—— 报错发生在 conftest 导入 app 时，
# 看起来像测试框架坏了，其实是引擎参数与方言不匹配。
#
# ⚠️ 这不是模块 3 的私事：在新 main 上跑**任何**模块的用例都会撞上，
#    与模块 3 的 `order_service.create_order` 自管会话（§5.5）无关。
#    集成组在公用基线修这一处时，直接照抄下面的条件分支即可。
_is_sqlite = settings.database_url.startswith("sqlite")

async_engine = create_async_engine(
    settings.database_url,
    echo=settings.SQL_ECHO,
    pool_pre_ping=True,
    **(
        {}
        if _is_sqlite
        else {
            "pool_size": 5,
            "max_overflow": 10,
            "pool_recycle": 3600,
            # 建连超时。不设时隧道未启动 / 云库不可达要等操作系统的 TCP 超时，
            # 表现为进程启动卡住、`GET /ready` 长时间无响应。
            # `connect_timeout` 是 asyncmy 的参数，因此只能走 connect_args。
            "connect_args": {"connect_timeout": settings.DB_CONNECT_TIMEOUT},
        }
    ),
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
