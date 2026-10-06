"""add repair ticket handling photo and verify columns (idempotent)

为「处理工单」补上「处理后照片 + AI 核验结论」三个字段。

背景
----
模块 6 原先只有 `PUT /tickets/{ticketId}/status` —— 它只改一个状态数字，
**不接受任何照片**。而业务上「处理完成」需要有凭据：维修后拍一张照片，
由 AI 核验是否真的修好了。因此新增 `POST /tickets/{ticketId}/handle`，
本迁移为它落三个字段：

    handle_image_url  VARCHAR(512)  处理后照片地址（可空 —— 落盘失败不阻断核验）
    verify_status     VARCHAR(16)   AI 核验结论，取值同 deviceStatus 四值
    verify_report     VARCHAR(1000) AI 核验说明（给处理人看「为什么没通过」）

为什么核验口径复用 deviceStatus 的四个取值
----------------------------------------
`装置是否修好` 与 `设备是否完好` 是同一件事的两种问法。另立一套
「处理成功 / 处理失败」的二值口径，等于把同一判断标准写两遍 ——
而本仓库反复踩过的坑正是「同一件事两处实现、改一处漏一处」。
故核验结果直接沿用 `inspect_service.DEVICE_STATUSES` 白名单，
「完好」即通过，其余（损坏 / 缺失配件 / 无法识别）即未通过。

为什么是幂等迁移而不是普通 op.add_column
--------------------------------------
与 `b7f1c4a92e35` 同样的理由，且更硬：真实执行路径是本机 SQLite 镜像
（`DATABASE_URL=sqlite+aiosqlite:///./.local_mirror.db`，见 backend/.env），
而团队共享的 MySQL 上这些列**可能已由别人先加过**。直接 `op.add_column`
在列已存在时会报 `Duplicate column name` 并中断整个迁移链。
故本迁移在**添加前逐个检查**，已存在则跳过并记日志，可反复执行。

SQLite 的 `ALTER TABLE ADD COLUMN` 能力有限（一次一列、不支持改类型），
本迁移只做「加列」，因此两种方言下都能跑通。

Revision ID: c4d8e1f0a2b7
Revises: b7f1c4a92e35
Create Date: 2026-10-06
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy.engine import Inspector

from alembic import context, op

revision: str = "c4d8e1f0a2b7"
down_revision: str | None = "b7f1c4a92e35"
branch_labels: str | None = None
depends_on: str | None = None

logger = logging.getLogger("alembic.runtime.migration")

TABLE = "repair_ticket"

#: 要新增的列：(列名, 类型, 注释)。
#: 类型刻意与 `app/models/inspection.py` 的 ORM 声明保持一致 ——
#: 两处不一致会让 `alembic check` / autogenerate 永远报「有待生成的迁移」。
COLUMN_SPECS: tuple[tuple[str, sa.types.TypeEngine, str], ...] = (
    (
        "handle_image_url",
        sa.String(length=512),
        "处理结果照片地址",
    ),
    (
        "verify_status",
        sa.String(length=16),
        "AI 核验结论：完好/损坏/缺失配件/无法识别",
    ),
    (
        "verify_report",
        sa.String(length=1000),
        "AI 核验说明",
    ),
)


def _existing_columns(inspector: Inspector, table: str) -> set[str]:
    """取表上已存在的列名。表不存在时返回空集合（不让迁移硬失败）。"""
    try:
        return {item["name"] for item in inspector.get_columns(table)}
    except sa.exc.NoSuchTableError:
        logger.warning("处理核验列迁移：表 %s 不存在，跳过", table)
        return set()


def _upgrade_offline() -> None:
    """
    离线模式（`alembic upgrade head --sql`）：无法查询表结构，退化为无条件加列。

    生成的 SQL 仅用于**评审与备份参考**；重放到已加过列的库上会报
    `Duplicate column name`。真正执行请用在线模式（在线分支是幂等的）。
    """
    op.execute(
        sa.text(
            "-- 离线模式：无法查询表结构，以下加列未做存在性判断。\n"
            "-- 仅供评审参考；实际执行请用在线模式 `alembic upgrade head`（幂等）。"
        )
    )
    for name, type_, comment in COLUMN_SPECS:
        op.add_column(TABLE, sa.Column(name, type_, nullable=True, comment=comment))
    logger.info("处理核验列迁移（离线模式）：已输出 %d 条 ADD COLUMN", len(COLUMN_SPECS))


def _upgrade_online() -> None:
    """在线模式：逐个检查后按需添加，可反复执行。"""
    inspector = sa.inspect(op.get_bind())
    existing = _existing_columns(inspector, TABLE)

    added: list[str] = []
    skipped: list[str] = []

    for name, type_, comment in COLUMN_SPECS:
        if name in existing:
            skipped.append(name)
            continue
        op.add_column(TABLE, sa.Column(name, type_, nullable=True, comment=comment))
        added.append(name)

    if added:
        logger.info("处理核验列迁移：已添加 -> %s", ", ".join(added))
    if skipped:
        logger.info("处理核验列迁移：已存在，跳过 -> %s", ", ".join(skipped))


def upgrade() -> None:
    """按运行模式分派。"""
    if context.is_offline_mode():
        _upgrade_offline()
    else:
        _upgrade_online()


def downgrade() -> None:
    """
    回滚：删掉本迁移添加的三列。

    同样是幂等的 —— 列不在就跳过，不报错。SQLite 3.35+ 支持 DROP COLUMN；
    更低版本会在这里报错，这属于已知限制（回滚只在本地镜像上可能用到）。
    """
    if context.is_offline_mode():
        for name, _type, _comment in reversed(COLUMN_SPECS):
            op.drop_column(TABLE, name)
        return

    inspector = sa.inspect(op.get_bind())
    existing = _existing_columns(inspector, TABLE)

    dropped: list[str] = []
    for name, _type, _comment in reversed(COLUMN_SPECS):
        if name in existing:
            op.drop_column(TABLE, name)
            dropped.append(name)

    if dropped:
        logger.info("处理核验列迁移回滚：已删除 -> %s", ", ".join(dropped))
