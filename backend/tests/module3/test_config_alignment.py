"""参数对齐的回归保护。

本模块的配置必须与团队公用 `backend/` 保持一致（团队连同一个云库）。
这里把「对齐」固化为断言：端口、驱动、主键类型一被改动就会失败。
"""
import pathlib

import pytest
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.schema import CreateTable

import app.models as models  # noqa: F401  确保模型注册
from app.core.config import Settings, settings
from app.core.database import Base

# 本文件位于 tests/module3/，上溯三层才是 backend/（用例下沉一层后此处曾算错）
BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
PUBLIC_BACKEND_ENV = BACKEND_DIR.parent.parent / "backend" / ".env"


# ------------------------------------------------------------ 配置项默认值


def test_config_defaults_align_with_public_backend():
    """默认值须与公用 backend/app/core/config.py 一致。"""
    fields = Settings.model_fields

    assert fields["DB_HOST"].default == "127.0.0.1"
    assert fields["DB_PORT"].default == 3308      # SSH 隧道本地端口（-> 服务器 3307）
    assert fields["DB_NAME"].default == "smart_scheduler_dev"
    assert fields["DB_USER"].default == "smart_dev"

    assert fields["APP_NAME"].default == "SmartScheduler"
    assert fields["APP_ENV"].default == "dev"
    assert fields["JWT_ALGORITHM"].default == "HS256"
    assert fields["JWT_EXPIRE_MINUTES"].default == 1440


def test_connection_string_schemes():
    """异步固定 mysql+asyncmy://（§3.4），同步为 mysql+pymysql://（与公用一致）。"""
    s = Settings(
        DATABASE_URL="", DB_HOST="h", DB_PORT=3308,
        DB_USER="u", DB_PASSWORD="p", DB_NAME="d",
    )
    assert s.database_url == "mysql+asyncmy://u:p@h:3308/d?charset=utf8mb4"
    assert s.sync_database_url == "mysql+pymysql://u:p@h:3308/d?charset=utf8mb4"


def test_explicit_database_url_overrides_parts():
    """显式 DATABASE_URL（§13.1 应急/自测）优先于五项拼接。"""
    s = Settings(DATABASE_URL="sqlite+aiosqlite:///./x.db", DB_HOST="h")
    assert s.database_url == "sqlite+aiosqlite:///./x.db"
    assert s.sync_database_url == "sqlite:///./x.db"


# ------------------------------------------------------------ 测试库隔离


def test_tests_run_on_isolated_database():
    """§10.2：用例必须跑在独立测试库，不得触碰云库 smart_scheduler_dev。"""
    assert settings.database_url.startswith("sqlite"), "测试库应是临时 SQLite"
    assert "smart_scheduler_dev" not in settings.database_url


# ------------------------------------------------------------ 模型类型


def _pk_type(table, dialect) -> str:
    """取出建表 DDL 中主键列的类型名。"""
    for line in str(CreateTable(table).compile(dialect=dialect)).splitlines():
        text = line.strip()
        if text.startswith("id "):
            return text.split()[1]
    raise AssertionError("未找到主键列")


def test_primary_key_is_bigint_on_mysql_integer_on_sqlite():
    """主键对齐云库 BIGINT；SQLite 降级 INTEGER 以保留自增（§13.1 应急路径）。"""
    for name in ("space_resource", "device_resource", "reserve_order", "notify_message"):
        table = Base.metadata.tables[name]
        assert _pk_type(table, mysql.dialect()) == "BIGINT", name
        assert _pk_type(table, sqlite.dialect()) == "INTEGER", name


def test_foreign_keys_align_with_spec():
    """外键须与云库一致：含指向 `sys_user` 的两个真外键（本模块此前用软引用）。

    `user_id` / `receiver_id` 的外键是随团队模型带进来的。云库
    `information_schema.STATISTICS` 显示这两列上确有索引（外键自动生成），
    可佐证云库本来就是真外键 —— 团队模型才是与云库一致的一方。
    """
    order = Base.metadata.tables["reserve_order"]
    assert {c.name for c in order.columns if c.foreign_keys} == {"space_id", "user_id"}

    message = Base.metadata.tables["notify_message"]
    assert {c.name for c in message.columns if c.foreign_keys} == {
        "receiver_id", "order_id"
    }


def test_index_names_align_with_spec_6_6():
    """§6.6 的 `idx_*` 索引**云库里并不存在**，模型也不声明 —— 此处固化「未声明」这一事实。

    §6.7 第 7 步的 `CREATE INDEX idx_*` 注明「由基础支撑与集成组统一执行」。但直查云库
    `smart_scheduler_dev` 的 `information_schema.STATISTICS`，9 个 `idx_*` 一个都没有：
    除主键外，库里的索引全是外键/唯一约束自动生成、与外键列同名的那些
    （`reserve_order.space_id`、`notify_message.order_id`、`sys_user.username` …）。

    团队模型亦无任何索引声明，本模块跟随团队，故断言「不声明 `idx_*`」。将来集成组
    若补建这些索引，应同步在模型里声明，并把本用例改成正向断言。
    """
    declared = {
        i.name for table in Base.metadata.tables.values() for i in table.indexes
    }
    assert not {n for n in declared if n.startswith("idx_")}, (
        f"模型声明了 §6.6 的 idx_* 索引，但云库实际没有：{sorted(declared)}"
    )


# ------------------------------------------------------------ 与公用后端一致性


@pytest.mark.skipif(
    not PUBLIC_BACKEND_ENV.exists(),
    reason="公用 backend/.env 不存在（模块被拆分出去时跳过）",
)
def test_database_params_match_public_backend():
    """本模块与公用 backend 必须连同一个云库（只比对连接定位项，不涉及口令）。"""

    def read(path, keys):
        found = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                if k.strip() in keys:
                    found[k.strip()] = v.strip()
        return found

    keys = {"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER"}
    ours = read(BACKEND_DIR / ".env", keys)
    theirs = read(PUBLIC_BACKEND_ENV, keys)

    if not ours:
        pytest.skip("本模块 .env 不存在，无法比对")

    assert ours == theirs, f"与公用 backend/.env 不一致：{ours} != {theirs}"
