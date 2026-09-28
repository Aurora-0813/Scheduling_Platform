"""add doc 6.6 indexes (idempotent)

为项目文档 6.6「索引规范」补齐索引。

为什么是幂等迁移而不是普通的 op.create_index
--------------------------------------------
项目文档 6.4 说明「所有表已在云服务器 smart_scheduler_dev 中创建完成」，
也就是说云库里**已经有数据、也已经有别人建的索引**。我们无法确认云库里
究竟已有哪些索引（当前网络不可达，无法核对），因此：

- 直接 `op.create_index` 会在索引已存在时报 `Duplicate key name` 而中断迁移；
- 只看索引名做判断也不够 —— 文档 6.6 里 `uk_username` 这种索引，
  在库里的实际名字可能是 MySQL 按列名自动生成的 `username`。

所以本迁移在**创建前逐个检查**，存在则跳过并记日志。无论云库现状如何，
重复执行都安全（可反复 `alembic upgrade head`）。

`uk_username` 为什么不在本迁移的创建清单里
------------------------------------------
`sys_user.username` 在 ORM 里已声明 `unique=True`（app/models/system.py），
初始迁移 `8969262c9d0c` 也已在建表时建出唯一索引。再建一个名为
`uk_username` 的唯一索引，会在同一列上留下两个唯一索引（纯浪费），
而且若云库里存在重复用户名，建唯一索引会直接失败并中断迁移。

因此本迁移只**检查并告警**，不创建。若检查发现缺失，说明云库的表结构与
项目文档不一致，需要集成组人工确认后再处理 —— 这属于数据库结构变更，
按约定必须先在群里确认。

Revision ID: b7f1c4a92e35
Revises: 8969262c9d0c
Create Date: 2026-09-27
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.engine import Inspector

revision: str = "b7f1c4a92e35"
down_revision: str | None = "8969262c9d0c"
branch_labels: str | None = None
depends_on: str | None = None

logger = logging.getLogger("alembic.runtime.migration")

# 项目文档 6.6 中需要本迁移创建的索引：(索引名, 表名, 列序列)
INDEX_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("idx_space_type", "space_resource", ("space_type",)),
    ("idx_capacity", "space_resource", ("capacity",)),
    ("idx_device_type", "device_resource", ("device_type",)),
    ("idx_user_id", "reserve_order", ("user_id",)),
    ("idx_space_time", "reserve_order", ("space_id", "start_time", "end_time")),
    ("idx_status", "reserve_order", ("order_status",)),
    ("idx_space_id", "inspect_record", ("space_id",)),
    ("idx_device_id", "repair_ticket", ("device_id",)),
    ("idx_ticket_status", "repair_ticket", ("ticket_status",)),
    ("idx_receiver_read", "notify_message", ("receiver_id", "is_read")),
)

# 只需检查、不创建的唯一索引（原因见模块文档）：(表名, 列序列, 文档中的名字)
UNIQUE_INDEX_CHECKS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("sys_user", ("username",), "uk_username"),
)


def _index_names(inspector: Inspector, table: str) -> set[str]:
    """取表上已存在的索引名。表不存在时返回空集合（不让迁移硬失败）。"""
    try:
        return {item["name"] for item in inspector.get_indexes(table) if item.get("name")}
    except sa.exc.NoSuchTableError:
        # 返回空集合而不是抛错：表不存在时后续的 create_index 会以更清晰的
        # 错误暴露问题，而这里让检查逻辑继续走完，不影响其它表。
        logger.warning("索引迁移：表 %s 不存在，跳过其索引检查", table)
        return set()


# 数据库把唯一性约束报为「无名字」时的占位描述。见 _find_unique_index_on。
_UNNAMED_UNIQUE = "(数据库未命名该约束)"


def _find_unique_index_on(
    inspector: Inspector, table: str, columns: tuple[str, ...]
) -> str | None:
    """
    查找覆盖指定列的唯一索引，返回其名字；找不到返回 None。

    同时检查 `get_indexes`（显式 CREATE UNIQUE INDEX）与
    `get_unique_constraints`（列级 UNIQUE / UNIQUE 约束）：
    MySQL 把两者都反映为唯一索引，但 SQLAlchemy 分别放在两个方法里返回，
    只查一个会漏判。

    关于「找到了但没有名字」：MySQL 会为列级 UNIQUE 自动起名（`username`），
    而 SQLite 的行内 `UNIQUE (username)` 反映出来是 `{"name": None}`。
    若直接返回这个名字，调用方 `if found:` 会因为 None 为假值而误报
    「唯一索引缺失」。所以这里把「无名字」也映射成一个真值占位串
    （_UNNAMED_UNIQUE），保证判定结果只取决于「有没有」，与命名无关。
    """
    target = list(columns)

    try:
        for item in inspector.get_indexes(table):
            if item.get("unique") and list(item.get("column_names") or []) == target:
                return item.get("name") or _UNNAMED_UNIQUE
    except sa.exc.NoSuchTableError:
        return None

    try:
        for item in inspector.get_unique_constraints(table):
            if list(item.get("column_names") or []) == target:
                return item.get("name") or _UNNAMED_UNIQUE
    except sa.exc.NoSuchTableError:
        return None

    return None


def _upgrade_offline() -> None:
    """
    离线模式（`alembic upgrade head --sql`）：无法查询数据库，因此不做存在性判断。

    离线模式拿到的连接是 `MockConnection`，`sa.inspect()` 会直接抛
    `NoInspectionAvailable`。这里退化为无条件 `CREATE INDEX`，并插入一行
    醒目注释：生成的 SQL 只用于**评审与备份参考**，直接重放到已有索引的库上
    会报 `Duplicate key name`。真正执行请用在线模式（本函数的在线分支是幂等的）。
    """
    op.execute(
        sa.text(
            "-- 离线模式：无法查询 information_schema，以下索引未做存在性判断。\n"
            "-- 仅供评审参考；实际执行请用在线模式 `alembic upgrade head`（幂等）。"
        )
    )
    for name, table, columns in INDEX_SPECS:
        op.create_index(name, table, list(columns))

    for table, columns, doc_name in UNIQUE_INDEX_CHECKS:
        op.execute(
            sa.text(
                f"-- 唯一索引检查（仅告警，不创建）：{table}({', '.join(columns)}) "
                f"在文档 6.6 中名为 {doc_name}"
            )
        )
    logger.info("索引迁移（离线模式）：已输出 %d 条 CREATE INDEX 语句", len(INDEX_SPECS))


def _upgrade_online() -> None:
    """在线模式：逐个检查后按需创建，可反复执行。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    created: list[str] = []
    skipped: list[str] = []

    for name, table, columns in INDEX_SPECS:
        if name in _index_names(inspector, table):
            # 已存在：幂等跳过。云库大概率已由建表脚本建好部分索引。
            skipped.append(f"{table}.{name}")
            continue

        # 复合索引的列顺序即定义顺序，op.create_index 会原样保留
        op.create_index(name, table, list(columns))
        created.append(f"{table}.{name}")

    if created:
        logger.info("索引迁移：已创建 %d 个索引 -> %s", len(created), ", ".join(created))
    if skipped:
        logger.info("索引迁移：已存在，跳过 %d 个 -> %s", len(skipped), ", ".join(skipped))

    # 唯一索引只检查不创建
    for table, columns, doc_name in UNIQUE_INDEX_CHECKS:
        found = _find_unique_index_on(inspector, table, columns)
        if found:
            logger.info(
                "索引检查：%s(%s) 的唯一索引已存在（实际名称 %s，文档中名为 %s）",
                table,
                ", ".join(columns),
                found,
                doc_name,
            )
        else:
            # 刻意只告警不创建：建唯一索引可能因存量重复数据失败而中断迁移，
            # 且属于表结构变更，需集成组确认后另行处理。
            logger.warning(
                "索引检查：%s(%s) 上未找到唯一索引（文档 6.6 中的 %s）。"
                "该列在 ORM 中为 unique=True、初始迁移也应已建出，"
                "缺失说明云库表结构与文档不一致，请先与集成组确认再处理。",
                table,
                ", ".join(columns),
                doc_name,
            )


def upgrade() -> None:
    """按运行模式分派。"""
    if context.is_offline_mode():
        _upgrade_offline()
    else:
        _upgrade_online()


def downgrade() -> None:
    """
    回滚：只删除本迁移清单里的索引。

    不碰 `uk_username`（本迁移从未创建）与 MySQL 为外键自动创建的索引 ——
    后者名字形如 `reserve_order_ibfk_1`，若误删会影响外键约束。
    删除前同样做存在性预检，保证可重复执行。
    """
    if context.is_offline_mode():
        for name, table, _columns in reversed(INDEX_SPECS):
            op.drop_index(name, table_name=table)
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    dropped: list[str] = []
    for name, table, _columns in reversed(INDEX_SPECS):
        if name in _index_names(inspector, table):
            op.drop_index(name, table_name=table)
            dropped.append(f"{table}.{name}")

    if dropped:
        logger.info("索引迁移回滚：已删除 %d 个索引 -> %s", len(dropped), ", ".join(dropped))
