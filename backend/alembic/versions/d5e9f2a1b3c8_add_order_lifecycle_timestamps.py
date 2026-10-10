"""add completed_at / cancelled_at to reserve_order（幂等）

Revision ID: d5e9f2a1b3c8
Revises: c4d8e1f0a2b7
Create Date: 2026-10-10

为什么加这两列
--------------
「预约时段已过 → 自动结单」需要一个**业务时刻**，而这张表原本只有
`create_time` / `update_time`。

⚠️ 不能用 `update_time` 代替：
  它是「这一行最后一次被改动的时刻」，等于**定时任务跑的时刻**。
  扫描每 300 秒一轮，订单 22:00 结束、22:04 才被扫到，用户会看到
  「完成于 22:04」——那是扫描时间，不是完成时间。而且任何无关改动都会刷新它。

所以单独立两个可空字段，只在**终态落定时**写一次：
  · `completed_at`  自动完成取订单的 `end_time`；人工完成取操作时刻
  · `cancelled_at`  用户取消（状态 3）与超时过期（状态 5）都写

⚠️ 同时把 `order_status` 的取值范围扩到 **5 已过期**（待确认超时未确认）。
   这是**业务语义变更**，不是本迁移引入的 DDL 约束 —— 该列是 `INT`、无 CHECK
   约束（见 8969262c9d0c 的建表），所以新增取值**不需要改列类型**。
   本迁移只加两列，并更新列注释以便后来者知道 5 的含义。

幂等口径（与 c4d8e1f0a2b7 一致）
--------------------------------
团队共享的 MySQL 上这两列**可能已由别人先加过**，所以先 `inspect` 再 `add_column`，
重复执行不会报 `Duplicate column name`。降级同样先查再删。

⚠️ 本迁移**只加两列**，刻意不碰 `order_status` 的列注释
-----------------------------------------------------
原打算顺手把该列注释补成「…4已完成，5已过期」，但 `op.alter_column(comment=...)`
在 **SQLite 上必然失败** —— `SQLiteDDLCompiler` 没有 `ColumnComment` 的编译处理器
（`tests/integration/test_migrations.py` 就是在 SQLite 上跑的）：

    UnsupportedCompilationError: SQLiteDDLCompiler can't render element of
    type <class 'alembic.ddl.base.ColumnComment'>

而 `op.add_column(..., comment=...)` 是 OK 的（`c4d8e1f0a2b7` 已验证，且本迁移
的集成用例通过）。为一行**纯文档性**的注释去写方言分支不划算，所以：

  · 库里的 `order_status` 注释仍停在「1待确认，2已确认，3已取消，4已完成」；
  · 新取值 5 的语义记在**代码**里 —— `app/state_machine.py::OrderStatus.EXPIRED`
    与 `app/models/reservation.py` 的列注释都已写明。

⚠️ 另外：新增取值 5 **不需要改列类型**。该列是 `INT`、建表时没有 CHECK 约束
   （见 `8969262c9d0c`），取值范围是业务约定而非 DDL 约束。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "d5e9f2a1b3c8"
down_revision: str | None = "c4d8e1f0a2b7"
branch_labels: str | None = None
depends_on: str | None = None

TABLE = "reserve_order"

#: 要加的列：(列名, 类型, 注释)
_NEW_COLUMNS: tuple[tuple[str, sa.types.TypeEngine, str], ...] = (
    (
        "completed_at",
        sa.DateTime(),
        "完成时刻（自动完成取 end_time，人工完成取操作时刻）",
    ),
    (
        "cancelled_at",
        sa.DateTime(),
        "取消/过期时刻（状态 3 或 5）",
    ),
)


def _is_offline() -> bool:
    """是否在生成离线 SQL（`alembic upgrade head --sql`）。"""
    return bool(op.get_context().as_sql)


def _existing_columns() -> set[str] | None:
    """
    已存在哪些列；**离线模式下返回 None**（表示「无法探测」）。

    ⚠️ 离线模式（`--sql`）下没有真连接，只有 SQLAlchemy 的 `MockConnection`，
    `sa.inspect()` 会直接抛：

        No inspection system is available for object of type MockConnection

    而 `tests/integration/test_migrations.py` 有两条用例正是跑
    `alembic upgrade head --sql`（模块 3 的离线 SQL 校验）。所以这里必须分叉：
    离线时无从判断列是否已存在，只能**无条件生成 `ADD COLUMN`** ——
    这与「离线 SQL 是给人看/给 DBA 审的脚本」这一用途相符，DBA 自己会判断。
    """
    if _is_offline():
        return None
    inspector = sa.inspect(op.get_bind())
    return {c["name"] for c in inspector.get_columns(TABLE)}


def upgrade() -> None:
    existing = _existing_columns()
    for name, type_, comment in _NEW_COLUMNS:
        # existing 为 None（离线）时不过滤，一律生成 DDL
        if existing is not None and name in existing:
            continue
        op.add_column(TABLE, sa.Column(name, type_, nullable=True, comment=comment))


def downgrade() -> None:
    existing = _existing_columns()
    for name, _type, _comment in reversed(_NEW_COLUMNS):
        if existing is not None and name not in existing:
            continue
        op.drop_column(TABLE, name)
