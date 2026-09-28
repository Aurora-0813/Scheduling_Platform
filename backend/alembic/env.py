"""
Alembic 迁移环境配置（全异步）

项目文档 3.4 要求统一使用异步驱动 `asyncmy`、连接串固定 `mysql+asyncmy://`，
禁止使用同步驱动 PyMySQL / mysqlclient。因此本文件**不使用** `engine_from_config`
（同步），改用 `async_engine_from_config` 配合 `connection.run_sync()` 执行迁移。

本项目以 Alembic 作为 schema 的唯一来源（项目文档 6.5 / 6.7 的手工 DDL 流程
已由迁移取代），详见 docs/开发流程说明文档.md 的「Alembic 迁移规范」一节。

连接串只从 `.env` 读取（经 app.core.config），`alembic.ini` 中的 sqlalchemy.url
保持注释状态，禁止写入真实连接串（项目文档 9.4）。

调用方式
--------
一律使用 `alembic` 命令（conda 环境 `smart_dev` 的 Scripts 目录下），
**不要用 `python -m alembic`**：仓库根目录下有个名为 `alembic/` 的迁移目录
（无 `__init__.py`），从仓库根以 `python -m` 启动时它会作为命名空间包遮蔽
真正的 alembic 包，报 `No module named alembic.__main__`。
同样地，`scripts/dev.sh` 与 CI 里也必须走控制台脚本（见 docs/deploy.md）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from logging.config import fileConfig

import sqlalchemy as sa
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Windows 下 asyncmy + ProactorEventLoop 会在关闭时序上报
# "RuntimeError: Event loop is closed"。必须切换到 SelectorEventLoop，
# 且必须在任何 asyncio.run() 之前设置，否则无效。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 把项目根目录加入 sys.path，保证无论从哪个工作目录调用 alembic 都能导入 app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.database import Base
from app.models import *  # noqa: F403  确保所有模型被导入，Base.metadata 才完整

logger = logging.getLogger("alembic.env")

# Alembic 配置对象
config = context.config


def _resolve_database_url() -> str:
    """
    取本次迁移要用的连接串。

    默认来源是 `.env`（经 app.core.config 拼接），`alembic.ini` 里的
    sqlalchemy.url 始终保持注释状态。

    唯一例外是环境变量 `ALEMBIC_DATABASE_URL`，它是**仅供离线测试**的覆盖开关：
    `tests/integration/test_migrations.py` 用它把迁移指向临时 SQLite 库，
    以便在云库不可达时验证「迁移能建出索引」与「重复执行幂等」。
    该变量只接受 `sqlite` 开头的连接串 —— 否则报错退出。这条限制是刻意的：
    它保证这个开关**永远不可能**把迁移重定向到另一个 MySQL，
    从而排除「误设变量把迁移打到线上库」的风险。
    """
    override = os.environ.get("ALEMBIC_DATABASE_URL", "").strip()
    if not override:
        return settings.database_url

    if not override.startswith("sqlite"):
        raise RuntimeError(
            "ALEMBIC_DATABASE_URL 只允许用于离线测试，必须是以 sqlite 开头的连接串；"
            f"当前值为 {override!r}。若你需要切换 MySQL 目标，请修改 .env 的 DB_* 配置。"
        )
    logger.warning("检测到 ALEMBIC_DATABASE_URL，本次迁移将指向 SQLite（仅供测试）：%s", override)
    return override


# 配置日志。必须放在 _resolve_database_url() 之前：后者会用 logger 发告警，
# 此时日志还没按 alembic.ini 配好，告警会走 lastResort 或直接丢失。
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 用 .env 拼出的异步连接串覆盖 alembic.ini。
# 注意：密码中若含 %（例如 URL 编码后的 %40、%23），configparser 会把 % 当作
# 插值语法并抛 InterpolationSyntaxError，因此必须把 % 转义为 %%。
config.set_main_option("sqlalchemy.url", _resolve_database_url().replace("%", "%%"))

# 目标元数据：Alembic 靠它对比模型与数据库
target_metadata = Base.metadata


def _compare_type(
    context_,
    inspected_column,
    metadata_column,
    inspected_type,
    metadata_type,
):
    """
    列类型比较钩子。

    忽略 BIGINT 有无符号的差异：云库的列类型是 `BIGINT UNSIGNED`（项目文档 6.3），
    而 ORM 模型使用的是有符号 `BigInteger`。该差异不影响业务语义，
    但若不忽略，每次 `alembic revision --autogenerate` 都会生成大量
    `MODIFY COLUMN` 噪音，掩盖真正的结构变更。

    返回 False 表示「不视为差异」，返回 None 表示「交回默认比较逻辑」。
    """
    if isinstance(inspected_type, sa.BigInteger) and isinstance(metadata_type, sa.BigInteger):
        return False
    # 其余类型交回 Alembic 默认逻辑（含类型长度、精度等变化）
    return None


def _include_object(object_, name, type_, reflected, compare_to):
    """
    autogenerate 对象过滤钩子。

    作用：不生成 `drop_index`。

    原因：MySQL 会为每个外键自动创建索引（如 `sys_user.role_id`、各表的 FK 列），
    这些索引存在于数据库中，但不会出现在 ORM 模型声明里。若不拦截，
    autogenerate 会把它们当作「数据库中多余的索引」并生成 `drop_index`，
    执行后会连带影响外键约束。

    取舍：这也意味着「从模型中删除索引声明」不会自动生成删除语句，
    需要人工编写迁移。这是刻意的选择 —— 误删索引的代价远高于多写一条迁移。
    """
    if type_ == "index" and reflected and compare_to is None:
        return False
    return True


def do_run_migrations(connection: Connection) -> None:
    """在同步上下文中配置并执行迁移。由 `connection.run_sync()` 调用。"""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=_compare_type,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _force_utf8_stdout() -> None:
    """
    离线模式会把 SQL 写到 stdout。Windows 控制台上 Python 的 stdout 默认使用
    本地代码页（简体中文环境是 cp936），于是

        alembic upgrade head --sql > migrate.sql

    产出的文件是 GBK 编码。文件里的中文注释在 MySQL 客户端（按 utf-8 解析）
    和 `git diff` 里都会显示为乱码 —— 注释虽不影响 SQL 语义，
    但这份 SQL 是用来人工评审云库变更的，看不懂就失去了意义。

    这里把 stdout 显式切到 UTF-8，保证无论在哪台机器上生成，产物都是可读的。
    Python 3.7+ 的 TextIOWrapper 才有 reconfigure；若 stdout 被替换成
    不支持该方法的对象（例如某些测试夹具），则静默跳过，不因此中断迁移。
    """
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8")
    except (ValueError, OSError):  # stdout 已关闭 / 被替换为不可重配置对象
        pass


def run_migrations_offline() -> None:
    """
    离线模式：只生成 SQL，不实际连接数据库。

    用法：alembic upgrade head --sql > migrate.sql
    """
    _force_utf8_stdout()
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=_compare_type,
        include_object=_include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """在线模式：实际连接数据库执行迁移（全异步）。"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        # 必须用 run_sync 包裹。直接调 connection.run_migrations() 会报
        # MissingGreenlet: greenlet_spawn has not been called
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """在线模式入口：驱动上面的协程。"""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
