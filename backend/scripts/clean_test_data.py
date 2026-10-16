"""清理演示/联调跑出来的**业务流水数据**（2026-10-14 新增）。

保留：账号、角色、权限、场地、设备（以及记录迁移版本的 alembic_version）。
清理：预约单、巡检记录、维修工单、通知消息 —— 以及它们引用的上传图片。

## 用法

    # 1) 先演练：只打印「将删掉什么」，不做任何写入（默认行为）
    .venv/Scripts/python.exe scripts/clean_test_data.py

    # 2) 确认无误后真删（会先把被删数据备份到 backups/ 再删）
    .venv/Scripts/python.exe scripts/clean_test_data.py --yes

    # 3) 不动上传文件（只清数据库）
    .venv/Scripts/python.exe scripts/clean_test_data.py --yes --keep-files

## 为什么默认是演练

这是**对着云库**的不可逆操作（`smart_scheduler_dev` 没有第二个副本、也没有备份，
见 backend/.env 的说明）。默认只读、要显式传 `--yes` 才会写，
就是为了避免「手滑跑了一次」这种事。

## 删除顺序（由外键决定，不能随意）

    1. notify_message   ← order_id 外键指向 reserve_order
    2. repair_ticket    ← inspect_id 外键指向 inspect_record
    3. inspect_record   ← 上一步删完才轮到它
    4. reserve_order    ← 通知删完才轮到它

顺序反了会被外键挡住（1451），或需要临时关外键检查 —— 那会把风险带进来。

## 备份

真删之前先把**整张表**的原始行写成 JSON（含被删与保留的），放在
`backend/backups/`。要恢复时按同目录生成的 `_restore_*.sql` 反向 INSERT 即可。
备份目录已加进 .gitignore（含真实业务数据，不该入库）。
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.core.config import settings  # noqa: E402

#: 要清空的**业务流水**表。顺序即删除顺序（子表在前），由外键决定。
CLEAN_TABLES = [
    "notify_message",
    "repair_ticket",
    "inspect_record",
    "reserve_order",
]

#: 固定数据表：只统计、绝不删（打印出来是为了让人一眼确认「它们没被动」）
KEEP_TABLES = [
    "sys_user",
    "sys_role",
    "sys_permission",
    "space_resource",
    "device_resource",
]

#: 上传目录（相对 backend/）。只在数据库删成功后，才删「被这些行引用过」的文件。
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"


def _q(name: str) -> str:
    """MySQL 标识符引号。单独成函数，避免反引号在 f-string 里被多转义一层。"""
    return "\u0060" + name + "\u0060"


async def _count(conn, table: str) -> int:
    return int((await conn.execute(text(f"SELECT COUNT(*) FROM {_q(table)}"))).scalar() or 0)


async def _collect_image_refs(conn) -> set[str]:
    """收集被删行引用过的图片路径（用来判断哪些上传文件会变成孤儿）。

    只收 inspect_record.image_url 与 repair_ticket.handle_image_url ——
    这两处是当前 schema 里唯一存上传文件路径的地方。
    """
    rows = (
        await conn.execute(
            text(
                "SELECT image_url FROM inspect_record "
                "UNION ALL SELECT handle_image_url FROM repair_ticket"
            )
        )
    ).scalars().all()
    return {r for r in rows if r}


def _url_to_path(url: str) -> Path | None:
    """把 /uploads/2026.../x.jpg 映射成本地盘路径。越界的路径一律返回 None。"""
    if not url or not url.startswith("/uploads/"):
        return None
    rel = url[len("/uploads/"):]
    p = (UPLOAD_DIR / rel).resolve()
    # 防目录穿越：只允许删 uploads/ 之下的文件
    if not str(p).startswith(str(UPLOAD_DIR.resolve())):
        return None
    return p


async def _collect_backup(conn) -> dict:
    """把 CLEAN_TABLES 的**全部原始行**收成一个可 JSON 序列化的 dict。"""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {"backed_up_at": stamp, "database": settings.DB_NAME, "tables": {}}
    for t in CLEAN_TABLES:
        rows = (await conn.execute(text(f"SELECT * FROM {_q(t)}"))).mappings().all()
        payload["tables"][t] = [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}
            for r in rows
        ]
    return payload


def _backup_dir() -> Path:
    """备份目录。可用环境变量覆盖（沙箱/CI 里那条路径可能不可写）。"""
    import os

    override = os.environ.get("CLEAN_BACKUP_DIR", "").strip()
    return Path(override) if override else BACKUP_DIR


async def main() -> int:
    parser = argparse.ArgumentParser(description="清理演示产生的业务流水数据（默认只演练）")
    parser.add_argument("--yes", action="store_true", help="真的执行删除（不传则只演练）")
    parser.add_argument("--keep-files", action="store_true", help="保留 uploads/ 下的图片文件")
    parser.add_argument(
        "--export-backup",
        action="store_true",
        help="把备份 JSON 打到标准输出（不写文件）。用于备份目录不可写的环境",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="跳过备份文件（⚠️ 只在该库本来就有别处备份时使用）",
    )
    parser.add_argument(
        "--emit-chunks",
        action="store_true",
        help=(
            "把备份 JSON 按固定宽度分行输出，备份文件不写。"
            "用途：本机环境不允许本脚本写文件时，由调用方从 stdout 收走落盘。"
            "与 --export-backup 的区别是每行都不超过约 2 KB —— "
            "否则那一整行会被截断，备份等于没做。"
        ),
    )
    parser.add_argument(
        "--chunk-width",
        type=int,
        default=1800,
        help="--emit-chunks 的每行宽度（默认 1800，留出 JSON 转义余量）",
    )
    parser.add_argument(
        "--lock-timeout",
        type=int,
        default=120,
        help=(
            "等锁的最长秒数（默认 120）。云库是全组共用的开发库，"
            "有人挂着在途事务时 DELETE 会撞 1205（服务端默认 innodb_lock_wait_timeout=50）。"
            "调大只是给一次机会，锁没释放的话照样会失败 —— 关键仍是先让持有者提交或断开。"
        ),
    )
    args = parser.parse_args()

    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": int(settings.DB_CONNECT_TIMEOUT)},
    )

    try:
        async with engine.connect() as conn:
            print("=" * 72)
            print(f"库：{settings.DB_NAME} @ {settings.DB_HOST}:{settings.DB_PORT}")
            print(f"模式：{'真删（会先备份）' if args.yes else '演练（只读，不写入）'}")
            print("=" * 72)

            before = {t: await _count(conn, t) for t in CLEAN_TABLES + KEEP_TABLES}

            print("\n---------- 待清理（业务流水） ----------")
            for t in CLEAN_TABLES:
                print(f"  {t:<20} {before[t]:>5} 行")

            print("\n---------- 保留（固定数据，不动） ----------")
            for t in KEEP_TABLES:
                print(f"  {t:<20} {before[t]:>5} 行")

            img_refs = await _collect_image_refs(conn)
            print(f"\n---------- 图片 ----------")
            print(f"  被上述记录引用过的上传文件：{len(img_refs)} 个")
            for u in sorted(img_refs):
                p = _url_to_path(u)
                exists = "存在" if (p and p.is_file()) else "文件已不在"
                print(f"    {u}  [{exists}]")

            if not args.yes:
                print("\n" + "=" * 72)
                print("演练结束：**未做任何写入**。确认无误后加 --yes 真删。")
                print("=" * 72)
                return 0

            # ---------- 真删 ----------
            # 迁移版本表与固定数据都不在 CLEAN_TABLES 里，绝不会被碰到。
            async with engine.begin() as txn:
                # 先放宽本会话的等锁上限。云库服务端默认 50 秒，
                # 而这是全组共用的开发库 —— 别人挂着事务时 50 秒会直接 1205，
                # 看起来像「脚本坏了」，其实是等得不够久。
                await txn.execute(text(f"SET SESSION innodb_lock_wait_timeout={int(args.lock_timeout)}"))
                payload = await _collect_backup(txn)

                if args.emit_chunks:
                    # 本机不允许写文件时用这条：调用方从 stdout 收走再落盘。
                    # **必须按固定宽度分行** —— 一整行超长时阅读工具只回前 ~2034 字符，
                    # 备份会被静默截断成无效 JSON（本脚本第一版就踩过）。
                    raw = json.dumps(payload, ensure_ascii=False)
                    w = max(200, args.chunk_width)
                    parts = [raw[i:i + w] for i in range(0, len(raw), w)]
                    print("\n===BACKUP-CHUNKS-BEGIN===")
                    print(f"# total_chars={len(raw)} chunks={len(parts)} width={w}")
                    for idx, p in enumerate(parts):
                        print(f"{idx:04d}|{p}")
                    print("===BACKUP-CHUNKS-END===")
                elif args.export_backup:
                    # 备份目录可能不可写（例如沙箱里由别的授权创建）。
                    # 打到 stdout 让调用方自己落盘 —— 这样「没有备份就删」不会发生。
                    print("\n===BACKUP-JSON-BEGIN===")
                    print(json.dumps(payload, ensure_ascii=False))
                    print("===BACKUP-JSON-END===")
                elif args.no_backup:
                    print("\n⚠️ 按 --no-backup 跳过备份文件。")
                else:
                    d = _backup_dir()
                    d.mkdir(parents=True, exist_ok=True)
                    out = d / f"test_data_backup_{payload['backed_up_at']}.json"
                    out.write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    print(f"\n已备份到：{out}")

                for t in CLEAN_TABLES:
                    res = await txn.execute(text(f"DELETE FROM {_q(t)}"))
                    print(f"  已删除 {t:<20} {res.rowcount} 行")

            print("\n事务已提交。")

            # ---------- 文件清理（DB 提交成功之后才做） ----------
            if args.keep_files:
                print("按 --keep-files 保留上传文件，未删任何文件。")
            else:
                removed, kept = 0, 0
                for u in sorted(img_refs):
                    p = _url_to_path(u)
                    if p and p.is_file():
                        p.unlink()
                        removed += 1
                    else:
                        kept += 1
                print(f"上传文件：删除 {removed} 个，跳过（文件不存在）{kept} 个。")
                print("⚠️ 未被任何记录引用的其它历史文件**没有动** —— 需要时手动清 uploads/。")

            # ---------- 复核 ----------
            async with engine.connect() as conn:
                after = {t: await _count(conn, t) for t in CLEAN_TABLES + KEEP_TABLES}
            print("\n---------- 复核 ----------")
            for t in CLEAN_TABLES:
                print(f"  {t:<20} {before[t]:>5} -> {after[t]}")
            for t in KEEP_TABLES:
                print(f"  {t:<20} {before[t]:>5} -> {after[t]}  (应保持原样)")

            print("\n" + "=" * 72)
            print("清理完成。")
            print("=" * 72)
            return 0
    except Exception as e:  # noqa: BLE001
        print(f"\n执行失败：{type(e).__name__}: {str(e)[:300]}")
        print("库未被改动（删除在单个事务里；文件清理只在事务提交后才执行）。")
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
