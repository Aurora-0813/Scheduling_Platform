"""
清除测试期间产生的业务数据：预约单 / 维修工单 / 巡检记录 / 通知。

⚠️ **只删业务数据，不动固定数据**（用户、角色、场地、设备、alembic 版本）。

删除顺序由外键决定（必须先删子表）：
    notify_message -> reserve_order        (notify_message.order_id)
    repair_ticket  -> inspect_record       (repair_ticket.inspect_id)
    inspect_record -> sys_user/space_resource （父表，最后删）

默认 **dry-run**（只报告不删）；加 --yes 才真删。
删前把整表内容导出成 JSON 备份，失败可据此恢复。
"""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf-8')

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

# 只删这些（顺序即删除顺序，子表在前）
DELETE_ORDER = ['notify_message', 'repair_ticket', 'inspect_record', 'reserve_order']
# 这些**绝不动**，仅打印出来确认没被波及
KEEP = ['sys_user', 'sys_role', 'space_resource', 'device_resource', 'alembic_version']


async def main():
    do_delete = '--yes' in sys.argv
    eng = create_async_engine(settings.database_url)
    try:
        async with eng.connect() as c:
            print('=== 删除前 ===')
            for t in DELETE_ORDER + KEEP:
                n = (await c.execute(text(f'SELECT COUNT(*) FROM {t}'))).scalar()
                tag = '（将清空）' if t in DELETE_ORDER else '（保留）'
                print(f'  {t:18s} {n:>5}  {tag}')

            # 备份
            backup = {}
            for t in DELETE_ORDER:
                rows = (await c.execute(text(f'SELECT * FROM {t}'))).mappings().all()
                backup[t] = [
                    {k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in r.items()}
                    for r in rows
                ]
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            out = Path('backups') / f'business_data_backup_{stamp}.json'
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(backup, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
            print(f'\n已备份到 {out}')
            print('  备份行数: ' + ', '.join(f'{k}={len(v)}' for k, v in backup.items()))

            if not do_delete:
                print('\n[DRY-RUN] 未删除任何数据。确认无误后加 --yes 执行。')
                return

            print('\n=== 开始删除 ===')
            async with eng.begin() as t:
                for tbl in DELETE_ORDER:
                    r = await t.execute(text(f'DELETE FROM {tbl}'))
                    print(f'  {tbl:18s} 删除 {r.rowcount} 行')

        async with eng.connect() as c:
            print('\n=== 删除后 ===')
            for t in DELETE_ORDER + KEEP:
                n = (await c.execute(text(f'SELECT COUNT(*) FROM {t}'))).scalar()
                print(f'  {t:18s} {n:>5}')
    finally:
        await eng.dispose()


asyncio.run(main())