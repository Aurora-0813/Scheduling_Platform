"""
Alembic 迁移测试（离线）

验证对象：`alembic/versions/b7f1c4a92e35_add_doc66_indexes_idempotent.py`
—— 为项目文档 6.6 补齐 10 个索引的**幂等**迁移。

为什么用 subprocess 而不是直接调 alembic 的 API
-----------------------------------------------
`alembic/env.py` 的在线模式内部调用 `asyncio.run()`。若在 pytest 已有事件循环的
上下文里调用，会抛 `RuntimeError: asyncio.run() cannot be called from a running
event loop`。改用独立进程执行 `alembic` 命令，既避开事件循环冲突，
又顺带验证了「队友按 docs/deploy.md 敲的那条命令」真的能跑通 —— 而不是只验证
某个内部函数。

为什么用 SQLite 而不是云库
-------------------------
云库与 SSH 隧道当前不可达。SQLite 临时库足以验证本迁移真正要保证的三条性质：

1. 缺索引时能建出来；
2. 索引已存在时**重复执行不报错**（这是本迁移存在的全部理由）；
3. 回滚只删自己建的索引，不误伤表与唯一约束。

云库实测由申云飞在隧道打通后执行，步骤见 docs/deploy.md。

为什么先 create_all 再 stamp，而不是直接 upgrade head
-----------------------------------------------------
初始迁移 `8969262c9d0c` 的建表语句里用的是 `server_default=sa.text('now()')`，
而 SQLite 不接受不带括号的 `DEFAULT now()`（只接受 `CURRENT_TIMESTAMP`
或带括号的表达式），直接跑初始迁移会以 `OperationalError: near "("` 失败。
初始迁移按既定决策不修改，所以：

- 用 ORM 元数据建表（SQLAlchemy 会把 `func.now()` 编译成 SQLite 的
  `CURRENT_TIMESTAMP`），再把 doc 6.6 的索引删掉，**模拟云库现状**；
- `alembic stamp 8969262c9d0c` 把版本位对齐到初始迁移之后；
- 于是 `upgrade head` 只会执行本迁移，测试聚焦、耗时也低。

代价（如实记录）：本文件**没有**验证初始迁移本身在云库上可执行。
那部分只能由云库实测覆盖。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

pytest.importorskip("aiosqlite", reason="迁移测试需要 aiosqlite 驱动 SQLite 临时库")

import app.models  # noqa: F401  导入以填充 Base.metadata
from app.core.database import Base

pytestmark = pytest.mark.migrations

REPO_ROOT = Path(__file__).resolve().parents[2]

INIT_REVISION = "8969262c9d0c"
HEAD_REVISION = "b7f1c4a92e35"

# 项目文档 6.6「索引规范」要求本迁移创建的索引。
# 这里刻意**手抄**而不是从迁移模块导入：测试的职责是用一份独立复述去核对实现，
# 若从被测代码导入常量，实现里漏写一个索引时测试会一起漏，失去意义。
DOC66_INDEXES: dict[str, tuple[str, tuple[str, ...]]] = {
    "idx_space_type": ("space_resource", ("space_type",)),
    "idx_capacity": ("space_resource", ("capacity",)),
    "idx_device_type": ("device_resource", ("device_type",)),
    "idx_user_id": ("reserve_order", ("user_id",)),
    "idx_space_time": ("reserve_order", ("space_id", "start_time", "end_time")),
    "idx_status": ("reserve_order", ("order_status",)),
    "idx_space_id": ("inspect_record", ("space_id",)),
    "idx_device_id": ("repair_ticket", ("device_id",)),
    "idx_ticket_status": ("repair_ticket", ("ticket_status",)),
    "idx_receiver_read": ("notify_message", ("receiver_id", "is_read")),
}

ALL_TABLES = (
    "device_resource",
    "inspect_record",
    "notify_message",
    "repair_ticket",
    "reserve_order",
    "space_resource",
    "sys_permission",
    "sys_role",
    "sys_user",
)


# --------------------------------------------------------------------------- #
# 基础设施
# --------------------------------------------------------------------------- #
class TempDb(NamedTuple):
    """临时 SQLite 库：同时给出异步连接串与文件路径。"""

    url: str
    path: Path


def _alembic_executable() -> str:
    """
    定位 alembic 命令行程序。

    先用与当前解释器同环境的那一个（`sys.executable` 旁边），保证跑 pytest 的
    环境就是跑迁移的环境；找不到再退回 PATH。

    注意：不要用 `python -m alembic` —— 本仓库根目录下有个名为 `alembic/` 的
    迁移目录（无 `__init__.py`），从仓库根执行时它会作为命名空间包遮蔽真正的
    alembic 包，`python -m alembic` 会报 "No module named alembic.__main__"。
    """
    if os.name == "nt":
        sibling = Path(sys.executable).parent / "Scripts" / "alembic.exe"
    else:
        sibling = Path(sys.executable).parent / "alembic"

    if sibling.exists():
        return str(sibling)

    found = shutil.which("alembic")
    if found:
        return found

    pytest.skip("未找到 alembic 命令行程序，跳过迁移测试")


def _run_alembic(
    *args: str,
    db_url: str | None = None,
    binary: bool = False,
    utf8_io: bool = True,
):
    """
    在独立进程里执行一条 alembic 命令。

    `db_url` 通过 ALEMBIC_DATABASE_URL 传给 env.py。该环境变量只接受 sqlite
    连接串（见 alembic/env.py 的 `_resolve_database_url`），因此这里不可能
    误把迁移指向云库。

    `utf8_io=True`（默认）会给子进程设 `PYTHONIOENCODING=utf-8`，让它的中文
    日志能按 UTF-8 读出来做断言。验证「离线 SQL 是合法 UTF-8」的用例必须传
    `utf8_io=False` —— 那一条要考的是 env.py 自己的 `_force_utf8_stdout()`
    有没有生效，若由外部环境变量兜住，测试就永远通过、失去意义。

    `binary=True` 时返回未解码的 CompletedProcess，供上述编码用例拿到原始字节。
    """
    env = os.environ.copy()
    env.pop("ALEMBIC_DATABASE_URL", None)
    if db_url is not None:
        env["ALEMBIC_DATABASE_URL"] = db_url
    if utf8_io:
        env["PYTHONIOENCODING"] = "utf-8"
    else:
        env.pop("PYTHONIOENCODING", None)

    completed = subprocess.run(
        [_alembic_executable(), *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        timeout=180,
    )
    if binary:
        return completed

    completed.stdout = completed.stdout.decode("utf-8", "replace")
    completed.stderr = completed.stderr.decode("utf-8", "replace")
    return completed


def _assert_ok(completed, what: str) -> None:
    """断言命令成功，失败时把子进程输出一并抛出便于定位。"""
    if completed.returncode != 0:
        raise AssertionError(
            f"{what} 失败（exit={completed.returncode}）\n"
            f"--- stdout ---\n{completed.stdout}\n"
            f"--- stderr ---\n{completed.stderr}"
        )


async def _create_schema(url: str) -> None:
    """按 ORM 元数据建出全部表（含模型声明的索引）。"""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


async def _read_schema(url: str) -> dict[str, object]:
    """读取索引名集合与各表的索引列定义，供断言使用。"""
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:

            def read(sync_conn):
                inspector = sa.inspect(sync_conn)
                tables = sorted(inspector.get_table_names())
                indexes: dict[str, tuple[str, tuple[str, ...]]] = {}
                unique_columns: set[tuple[str, ...]] = set()

                for table in tables:
                    for item in inspector.get_indexes(table):
                        if item.get("name"):
                            indexes[item["name"]] = (
                                table,
                                tuple(item.get("column_names") or ()),
                            )
                    # 唯一性可能落在「索引」或「约束」任一侧，两个都收
                    for item in inspector.get_indexes(table):
                        if item.get("unique"):
                            unique_columns.add(tuple(item.get("column_names") or ()))
                    for item in inspector.get_unique_constraints(table):
                        unique_columns.add(tuple(item.get("column_names") or ()))

                return {
                    "tables": tables,
                    "indexes": indexes,
                    "unique_columns": unique_columns,
                }

            return await conn.run_sync(read)
    finally:
        await engine.dispose()


async def _drop_doc66_indexes(url: str) -> None:
    """
    删掉 ORM 已建出的 doc 6.6 索引，把库还原成「表都在但 6.6 索引未建」的
    状态 —— 即项目文档 6.4 描述的云库现状。
    """
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            for name in DOC66_INDEXES:
                await conn.execute(sa.text(f"DROP INDEX IF EXISTS {name}"))
    finally:
        await engine.dispose()


async def _compare_against_models(url: str) -> list:
    """
    把库里的实际结构与 ORM 元数据对比，返回差异列表（空列表 = 一致）。

    等价于 `alembic revision --autogenerate` 的比对步骤，但不写任何文件 ——
    测试不该往 `alembic/versions/` 里扔临时迁移脚本。
    """
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:

            def read(sync_conn):
                context = MigrationContext.configure(sync_conn)
                return compare_metadata(context, Base.metadata)

            return await conn.run_sync(read)
    finally:
        await engine.dispose()


@pytest.fixture()
def fresh_db(tmp_path: Path) -> TempDb:
    """建好全部表、并移除 doc 6.6 索引的 SQLite 临时库。"""
    db_path = tmp_path / "migrate.db"
    db = TempDb("sqlite+aiosqlite:///" + db_path.as_posix(), db_path)
    asyncio.run(_create_schema(db.url))
    asyncio.run(_drop_doc66_indexes(db.url))
    return db


def _schema(db: TempDb) -> dict[str, object]:
    return asyncio.run(_read_schema(db.url))


def _stamp(db: TempDb, revision: str) -> None:
    """把 alembic 版本位摆到指定 revision（不执行迁移）。"""
    _assert_ok(
        _run_alembic("stamp", revision, db_url=db.url),
        f"alembic stamp {revision}",
    )


# --------------------------------------------------------------------------- #
# 前置条件自检：证明夹具真的模拟出了「缺索引」的云库现状
# --------------------------------------------------------------------------- #
def test_fixture_starts_without_doc66_indexes(fresh_db: TempDb) -> None:
    """
    夹具自检。

    没有这条用例，`test_upgrade_creates_doc66_indexes` 可能在「索引本来就存在」
    的情况下通过 —— 那样它其实什么都没验证。
    """
    state = _schema(fresh_db)
    assert state["tables"] == list(ALL_TABLES)
    assert not set(DOC66_INDEXES) & set(state["indexes"]), (
        "夹具应已删除 doc 6.6 的全部索引，实际仍存在："
        f"{sorted(set(DOC66_INDEXES) & set(state['indexes']))}"
    )


# --------------------------------------------------------------------------- #
# 在线：创建
# --------------------------------------------------------------------------- #
def test_upgrade_creates_doc66_indexes(fresh_db: TempDb) -> None:
    """缺索引时，upgrade 应当把文档 6.6 的 10 个索引全部建出来。"""
    _stamp(fresh_db, INIT_REVISION)

    completed = _run_alembic("upgrade", "head", db_url=fresh_db.url)
    _assert_ok(completed, "alembic upgrade head")
    assert HEAD_REVISION in completed.stderr, (
        "迁移日志里没有出现目标 revision，upgrade 可能没有真正执行本迁移"
    )

    indexes = _schema(fresh_db)["indexes"]
    for name, (table, columns) in DOC66_INDEXES.items():
        assert name in indexes, f"索引 {name} 未被创建"
        assert indexes[name] == (table, columns), (
            f"索引 {name} 定义不符：期望 {table}{columns}，实际 {indexes[name]}。"
            "复合索引的列顺序影响可用性（最左前缀），必须与文档 6.6 一致。"
        )


def test_upgrade_is_idempotent_when_indexes_already_exist(fresh_db: TempDb) -> None:
    """
    核心用例：索引已存在时重复执行不得报错。

    这正是本迁移不用 `op.create_index` 而先做存在性判断的原因 ——
    云库（项目文档 6.4 说明表已建好）大概率已有部分索引，
    朴素的 `op.create_index` 会在 `Duplicate key name` 上中断整条迁移链。
    """
    _stamp(fresh_db, INIT_REVISION)
    _assert_ok(_run_alembic("upgrade", "head", db_url=fresh_db.url), "首次 upgrade head")

    indexes_after_first = _schema(fresh_db)["indexes"]

    # 把版本位退回初始迁移，但**保留**已建好的索引 —— 模拟「云库里索引已存在，
    # 但 alembic_version 还没记录本迁移」的第二次执行场景。
    _stamp(fresh_db, INIT_REVISION)
    completed = _run_alembic("upgrade", "head", db_url=fresh_db.url)
    _assert_ok(completed, "重复 alembic upgrade head")

    assert "Duplicate key name" not in completed.stderr
    assert _schema(fresh_db)["indexes"] == indexes_after_first, (
        "重复执行后索引集合发生变化，说明幂等逻辑有漏洞"
    )


def test_migrated_schema_matches_models(fresh_db: TempDb) -> None:
    """
    迁移建出的索引必须与模型的 `__table_args__` 声明**逐列一致**。

    这条用例守住决策 2 的整个理由：迁移负责把索引建到云库，模型负责让
    `alembic revision --autogenerate` 知道这些索引是「预期存在的」。
    两者一旦不一致，下次 autogenerate 就会生成 `drop_index`（模型没声明）
    或 `create_index`（迁移漏建）的噪音，而这两类噪音都足以掩盖真正的结构变更。

    注意这里**刻意不传** env.py 的 `_include_object` 钩子。那个钩子会屏蔽
    「库里有、模型没有」的索引（MySQL 的外键自动索引需要它），传了就会把
    「迁移多建了索引」这类问题一起吞掉。SQLite 不会为外键自动建索引，
    因此不带钩子跑不会有假阳性 —— 于是这条用例是一次严格的双向核对。
    """
    _stamp(fresh_db, INIT_REVISION)
    _assert_ok(_run_alembic("upgrade", "head", db_url=fresh_db.url), "upgrade head")

    diffs = asyncio.run(_compare_against_models(fresh_db.url))

    assert diffs == [], "迁移后的库结构与 ORM 模型不一致，autogenerate 将产生噪音：\n" + "\n".join(
        f"  {diff!r}" for diff in diffs
    )


# --------------------------------------------------------------------------- #
# 在线：回滚
# --------------------------------------------------------------------------- #
def test_downgrade_drops_only_own_indexes(fresh_db: TempDb) -> None:
    """
    回滚只删本迁移建的索引，不误伤表结构与唯一约束。

    MySQL 会为外键自动建索引（名字形如 `<表>_ibfk_1`），若 downgrade 无条件
    按名字 drop，或误删 `uk_username`，会破坏数据完整性 —— 这条用例把
    「只动自己的东西」固化成断言。
    """
    _stamp(fresh_db, INIT_REVISION)
    _assert_ok(_run_alembic("upgrade", "head", db_url=fresh_db.url), "upgrade head")

    _assert_ok(
        _run_alembic("downgrade", INIT_REVISION, db_url=fresh_db.url),
        f"downgrade {INIT_REVISION}",
    )

    state = _schema(fresh_db)
    assert not set(DOC66_INDEXES) & set(state["indexes"]), (
        f"回滚后仍有本迁移的索引残留：{sorted(set(DOC66_INDEXES) & set(state['indexes']))}"
    )
    # 用「包含」而非「相等」：alembic 自己会在库里建一张 alembic_version 表，
    # 它属于 alembic 而非本迁移，不该出现在断言里。
    missing = set(ALL_TABLES) - set(state["tables"])
    assert not missing, f"回滚不应删除任何表，但以下表消失了：{sorted(missing)}"
    assert ("username",) in state["unique_columns"], "回滚不应影响 sys_user.username 的唯一性约束"


# --------------------------------------------------------------------------- #
# 离线模式（--sql）
# --------------------------------------------------------------------------- #
def test_offline_sql_lists_all_doc66_indexes(fresh_db: TempDb) -> None:
    """
    离线模式（`alembic upgrade head --sql`）应输出全部 10 条 CREATE INDEX。

    离线模式拿不到数据库连接（env.py 里是 MockConnection），无法做存在性判断，
    因此退化为无条件 CREATE INDEX —— 用途仅限于评审与备份参考，
    这一点必须在生成的 SQL 里写明，否则有人会把它直接灌进已建索引的库而报错。
    """
    completed = _run_alembic("upgrade", "head", "--sql", db_url=fresh_db.url, binary=True)
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")

    sql = completed.stdout.decode("utf-8")

    for name in DOC66_INDEXES:
        assert f"CREATE INDEX {name} " in sql, f"离线 SQL 缺少索引 {name}"

    assert "-- 离线模式" in sql, "离线 SQL 缺少「不做存在性判断」的警示注释"
    assert "uk_username" in sql, "离线 SQL 应说明 uk_username 只检查不创建"


def test_offline_sql_is_utf8(fresh_db: TempDb) -> None:
    """
    离线 SQL 必须是合法 UTF-8。

    Windows 控制台上 Python 的 stdout 默认使用本地代码页（简体中文环境为
    cp936），若不干预，`alembic upgrade head --sql > migrate.sql` 产出的文件
    会是 GBK，中文注释在 MySQL 客户端与 `git diff` 里全部变乱码。
    env.py 的 `_force_utf8_stdout()` 负责修正，这条用例守住它。
    """
    completed = _run_alembic(
        "upgrade", "head", "--sql", db_url=fresh_db.url, binary=True, utf8_io=False
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")

    try:
        sql = completed.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:  # pragma: no cover - 仅在回归时触发
        raise AssertionError(
            f"离线 SQL 不是合法 UTF-8（{exc}）。"
            "说明 env.py 的 _force_utf8_stdout() 失效，"
            "生成的中文注释在评审时会变成乱码。"
        ) from exc

    assert "索引" in sql


# --------------------------------------------------------------------------- #
# 安全护栏
# --------------------------------------------------------------------------- #
def test_non_sqlite_override_is_rejected(tmp_path: Path) -> None:
    """
    ALEMBIC_DATABASE_URL 只接受 sqlite，防止这个测试开关把迁移指向真实 MySQL。

    这是刻意设成「硬失败」的：一个能被随手设成生产连接串的环境变量，
    迟早会有人在错误的终端里导出它，然后把索引建到不该建的地方。
    """
    completed = _run_alembic(
        "upgrade", "head", "--sql", db_url="mysql+asyncmy://u:p@127.0.0.1:3306/other"
    )
    assert completed.returncode != 0, "非 sqlite 的 ALEMBIC_DATABASE_URL 必须被拒绝"
    assert "只允许用于离线测试" in completed.stderr
