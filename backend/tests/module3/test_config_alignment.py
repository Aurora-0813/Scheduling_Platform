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
    # 30 分钟 = 团队基线（`docs/api.md` §1.7「accessToken 有效期 30 分钟」）。
    # 本模块此前取 1440（一天），与团队不一致；已随本轮重组对齐团队。
    assert fields["JWT_EXPIRE_MINUTES"].default == 30


def test_connection_string_is_async_only():
    """异步固定 mysql+asyncmy://（§3.4），且**不提供**同步串。

    团队曾为 Alembic 保留 `sync_database_url`（mysql+pymysql://），后因迁移改为
    全异步（`alembic/env.py` 用 async_engine_from_config）而删除。本用例把
    「同步路径已不存在」钉死：属性一旦被加回来，就说明有人重新引入了 PyMySQL ——
    那是 §3.4 明令禁止的同步驱动。
    """
    s = Settings(
        DATABASE_URL="", DB_HOST="h", DB_PORT=3308,
        DB_USER="u", DB_PASSWORD="p", DB_NAME="d",
    )
    assert s.database_url == "mysql+asyncmy://u:p@h:3308/d?charset=utf8mb4"
    assert not hasattr(s, "sync_database_url")
    assert not hasattr(s, "sync_engine")


def test_explicit_database_url_overrides_parts():
    """显式 DATABASE_URL（§13.1 应急/自测）优先于五项拼接。"""
    s = Settings(DATABASE_URL="sqlite+aiosqlite:///./x.db", DB_HOST="h")
    assert s.database_url == "sqlite+aiosqlite:///./x.db"


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


#: §6.6 索引规范 → 该索引应声明在哪张表上。
#: 不含 `sys_user.uk_username`：它是 UNIQUE **约束**（`uk_` 前缀），
#: 由列上的 `unique=True` 表达，不进 `table.indexes`，故单列一条断言。
_SPEC_6_6_INDEXES: dict[str, str] = {
    "idx_space_type": "space_resource",
    "idx_capacity": "space_resource",
    "idx_device_type": "device_resource",
    "idx_user_id": "reserve_order",
    "idx_space_time": "reserve_order",
    "idx_status": "reserve_order",
    "idx_space_id": "inspect_record",
    "idx_device_id": "repair_ticket",
    "idx_ticket_status": "repair_ticket",
    "idx_receiver_read": "notify_message",
}

#: §6.6 **之外**、经集成组确认补建的索引。**每条都要写明依据** ——
#: 这是「模型声明 == 规范」这条断言唯一的出口，往里加东西等于放宽规范，
#: 不写清楚就会被下一个人当成随手加的。
_EXTRA_INDEXES: dict[str, str] = {
    # main `98c54ea`（2026-09-28 集成组补）：§6.6 的索引在**设备维度**的时段统计上
    # 全部失效 —— 设备是全局资源，`device_resource` 没有 `space_id`，
    # `idx_space_time` 的最左前缀用不上；`device_ids` 又是 JSON 列，建不了普通索引。
    # 模块 3 `_device_conflicts` 的谓词是
    #     order_status IN (活跃) AND end_time > :start AND start_time < :end
    # 补这条后等值与范围都能走索引。迁移见 `b7f1c4a92e35` 的说明。
    "idx_status_start": "reserve_order",
}


def test_index_names_align_with_spec_6_6():
    """§6.6 的 10 个 `idx_*` 一个不少、且挂在正确的表上；规范之外的一律要登记。

    **方向已翻转。** 本用例此前断言的是「模型不声明 `idx_*`」—— 那是当时的事实：
    直查云库 `smart_scheduler_dev` 的 `information_schema.STATISTICS`，`idx_*`
    一个都没有，团队模型也没声明。新 main（`9f30d3a`）把这个缺口补上了：
    团队模型开始声明 `idx_*`，并配了幂等迁移
    `alembic/versions/b7f1c4a92e35_add_doc66_indexes_idempotent.py`。

    「不多」这一侧**不是死板的 10 个**：集成组可以补，但要登记进
    `_EXTRA_INDEXES` 并写明依据（`idx_status_start` 就是这么来的）。

    ⚠️ **本用例只验证「模型声明 == §6.6 规范」，不验证云库已建。**
    云库上这些索引是否真的存在，取决于上述迁移有没有在云库跑过 ——
    本轮**未复验**（需要 SSH 隧道 + 直查 `information_schema`）。
    在复验之前，不要把这行绿当成「云库已有索引」的证据。
    """
    declared = {
        i.name: table.name
        for table in Base.metadata.tables.values()
        for i in table.indexes
    }
    allowed = {**_SPEC_6_6_INDEXES, **_EXTRA_INDEXES}
    # 不多：规范之外、又没登记的 idx_* 一律拒绝（多出来的索引没人负责维护，
    # 而它会实打实占写入开销）
    assert set(declared) == set(allowed), (
        f"模型声明的 idx_* 与 §6.6（+ 已登记的补充索引）不一致：\n"
        f"  多了：{sorted(set(declared) - set(allowed))}\n"
        f"  少了：{sorted(set(allowed) - set(declared))}"
    )
    # 不少、且位置正确（规范内的与补充的都要挂对表）
    for name, table_name in allowed.items():
        assert declared[name] == table_name, (
            f"{name} 应声明在 {table_name} 上，实际在 {declared[name]}"
        )


def test_username_unique_constraint_aligns_with_spec_6_6():
    """§6.6 的 `uk_username` 由列级 UNIQUE 约束表达（登录查询靠它）。"""
    sys_user = Base.metadata.tables["sys_user"]
    unique_cols = {
        c.name for c in sys_user.columns if c.unique
    } | {
        tuple(sorted(c.name for c in con.columns))
        for con in sys_user.constraints
        if con.__class__.__name__ == "UniqueConstraint"
    }
    assert "username" in unique_cols or ("username",) in unique_cols


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
