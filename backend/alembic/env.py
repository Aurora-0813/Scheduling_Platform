"""
Alembic 迁移环境配置
连接数据库，读取模型元数据
"""
import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# 把项目根目录加入路径，保证能导入 app
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.config import settings
from app.core.database import Base
from app.models import *  # noqa: F401, F403  确保所有模型被导入

# Alembic 配置对象
config = context.config

# 用同步连接串覆盖 alembic.ini 里的配置
config.set_main_option("sqlalchemy.url", settings.sync_database_url)

# 配置日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 目标元数据，Alembic 靠它对比模型和数据库
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL，不实际连接数据库"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：实际连接数据库执行迁移"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,  # 检测字段类型变化
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()