"""测试数据盘点（**只读**，2026-10-14 新增）。

用途：演示/联调之后要清掉「跑出来的业务数据」（预约单、工单、通知…），
先把全库的真实情况列清楚，**再**决定删哪些。本脚本只执行 SELECT / SHOW，
不做任何写入，可以放心反复跑。

为什么不复用 `check_data.py`：
那个脚本盯的是「种子数据是否完整」（9 张固定表 + device_ids 格式核查），
而这里要回答的是另一个问题：**哪些表里有演示跑出来的脏数据、行数各是多少、
删的时候有没有外键挡住**。两者的观察点不同，混在一起会让两边都变形。

用法（在 backend/ 目录下执行）：

    .venv/Scripts/python.exe scripts/list_test_data.py

输出：
  1. 全库表清单与行数（按行数降序，一眼看出哪张表有数据）
  2. 每张表的列（便于确认哪些是流水表、哪些是固定数据表）
  3. 外键关系（决定删除顺序，避免被约束挡住）
  4. 业务流水表的抽样样本（确认「确实是测试数据」而不是别人正在用的）
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows 控制台默认 GBK，中文与 emoji 可能乱码甚至抛 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.core.config import settings  # noqa: E402

#: 固定数据（**不删**）：账号、角色、权限、场地、设备
FIXED_TABLES = {
    "sys_user",
    "sys_role",
    "sys_permission",
    "sys_role_permission",
    "sys_user_role",
    "space_resource",
    "device_resource",
}


def _q(name: str) -> str:
    """用反引号包住表名（MySQL 标识符引号）。

    单独写成一个函数而不是把反引号直接写进 f-string：
    直接在字符串里内嵌引号很容易被多转义一层（本脚本第一版就踩了，
    拼出 \\`table\\` 这种字面反斜杠，MySQL 直接 1064 语法错）。
    """
    return "\u0060" + name + "\u0060"


async def main() -> int:
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": int(settings.DB_CONNECT_TIMEOUT)},
    )

    try:
        async with engine.connect() as conn:
            print("=" * 72)
            print(f"库：{settings.DB_NAME} @ {settings.DB_HOST}:{settings.DB_PORT}")
            print("=" * 72)

            # ---------- 1. 表清单与行数 ----------
            tables = (
                await conn.execute(text("SHOW TABLES"))
            ).scalars().all()

            print("\n---------- 1. 全库表与行数（按行数降序） ----------")
            counts: list[tuple[str, int | str]] = []
            for t in tables:
                try:
                    n = (await conn.execute(text(f"SELECT COUNT(*) FROM {_q(t)}"))).scalar()
                    counts.append((t, int(n or 0)))
                except Exception as e:  # noqa: BLE001
                    counts.append((t, f"查询失败 {type(e).__name__}"))
            counts.sort(key=lambda x: (-(x[1] if isinstance(x[1], int) else -1), x[0]))

            print(f"  {'表名':<28} {'行数':>8}   类型")
            print("  " + "-" * 56)
            for name, n in counts:
                kind = "固定数据(不删)" if name in FIXED_TABLES else "业务流水"
                print(f"  {name:<28} {str(n):>8}   {kind}")

            # ---------- 2. 业务流水表的列 ----------
            print("\n---------- 2. 业务流水表的列 ----------")
            for name, n in counts:
                if name in FIXED_TABLES:
                    continue
                cols = (
                    await conn.execute(text(f"SHOW COLUMNS FROM {_q(name)}"))
                ).all()
                colnames = ", ".join(c[0] for c in cols)
                print(f"  {name}（{n} 行）:")
                print(f"      {colnames}")

            # ---------- 3. 外键 ----------
            print("\n---------- 3. 外键关系（决定删除顺序） ----------")
            fks = (
                await conn.execute(
                    text(
                        """
                        SELECT TABLE_NAME, COLUMN_NAME,
                               REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
                        FROM information_schema.KEY_COLUMN_USAGE
                        WHERE TABLE_SCHEMA = :db
                          AND REFERENCED_TABLE_NAME IS NOT NULL
                        ORDER BY TABLE_NAME, COLUMN_NAME
                        """
                    ),
                    {"db": settings.DB_NAME},
                )
            ).all()
            if not fks:
                print("  （无外键约束 —— 删除顺序不受限）")
            for r in fks:
                print(f"  {r[0]}.{r[1]}  ->  {r[2]}.{r[3]}")

            # ---------- 4. 业务流水的抽样 ----------
            print("\n---------- 4. 业务流水抽样（各 5 条） ----------")
            for name, n in counts:
                if name in FIXED_TABLES or not isinstance(n, int) or n == 0:
                    continue
                rows = (
                    await conn.execute(text(f"SELECT * FROM {_q(name)} LIMIT 5"))
                ).mappings().all()
                print(f"\n  --- {name} ---")
                for row in rows:
                    d = dict(row)
                    # 长字段截断，避免 agent_trace 这类大文本刷屏
                    items = []
                    for k, v in d.items():
                        s = str(v)
                        if len(s) > 40:
                            s = s[:40] + "…"
                        items.append(f"{k}={s}")
                    print("    " + ", ".join(items))

            print("\n" + "=" * 72)
            print("盘点完成（本次未做任何写入）")
            print("=" * 72)
            return 0
    except Exception as e:  # noqa: BLE001
        print(f"连库失败：{type(e).__name__}: {str(e)[:300]}")
        print("提示：确认 backend/.env 的 DB_* 正确、云库可达。")
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
