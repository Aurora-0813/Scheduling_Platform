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
    而 SQLite 会选中 `NullPool`，这些参数一个都不接受，导入即抛
    `TypeError: Invalid argument(s) 'pool_size', 'max_overflow' sent to create_engine()`。
    触发条件是「`DATABASE_URL` 指向 SQLite」，目前有两条路走到那里：
    `§13.1` 的本地镜像库（演示应急），以及测试进程 —— 模块 3 的用例直接使用
    模块级的 `async_engine`（`services/order_service.create_order` 自管会话，
    §5.5），必须把 `DATABASE_URL` 指到临时 SQLite 才不会写脏云库，见
    `tests/conftest.py` 顶部那行覆盖。**团队自己的用例目前不会撞上**：它们的
    `DATABASE_URL` 仍是 `.env` 里的 MySQL，且自建的引擎不含池参数 ——
    所以这条不是「团队基线现在就跑不起来」，而是「一旦有人按 §13.1 切 SQLite
    就会启动即挂」。详见下方“SQLite 应急路径的引擎参数适配”一节。

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



# ⚠️ 关于 `pool_pre_ping`：**保持开启**，但必须先打上方 `patch_asyncmy_ping()` 补丁。
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
#    模块 4 一线原先的处置是**关掉 `pool_pre_ping` 绕开**（提交 f4d1a07）；本文件取模块 3
#    的处置——**把 ping 修好、保留健康检查**。补丁有单测
#    `tests/module3/test_asyncmy_ping_compat.py` 钉住，且只在 `mysql+asyncmy` 时生效；
#    关掉 pre_ping 只是把问题换成「空闲后复用旧连接报 500」。集成组在公用基线修好后
#    删掉补丁即可，本行不用改。

# ---------- SQLite 应急路径的引擎参数适配（必需，非临时补丁） ----------
# `settings.database_url` 有两条路径不是 mysql+asyncmy：`§13.1` 的本地 SQLite
# 应急镜像，以及测试进程 —— 模块 3 的用例直接用模块级 `async_engine`，必须把
# `DATABASE_URL` 指到临时 SQLite 才不会写脏云库（`tests/conftest.py` 顶部）。
#
# `sqlite+aiosqlite` 无论文件库还是 `:memory:` 都会选中 `NullPool`（实测；
# `:memory:` 是 `StaticPool`），二者的 `__init__` **都不接受** pool_size /
# max_overflow / pool_recycle。无条件传过去的话，`app.core.database` 在被
# import 的**那一刻**就抛：
#     TypeError: Invalid argument(s) 'pool_size', 'max_overflow' sent to create_engine()
# 症状是「任何一条用例都收集不到」—— 报错发生在 conftest 导入 app 时，
# 看起来像测试框架坏了，其实是引擎参数与方言不匹配。
#
# ⚠️ 准确的触发条件，别记成「团队基线现在就跑不起来」：
#    **团队自己的用例撞不上** —— 它们不覆盖 `DATABASE_URL`（仍是 `.env` 里的
#    MySQL），并自建不含池参数的引擎。所以这是「一旦有人按 §13.1 把
#    `DATABASE_URL` 切成 SQLite，服务就会启动即挂」，而不是当下的故障。
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
