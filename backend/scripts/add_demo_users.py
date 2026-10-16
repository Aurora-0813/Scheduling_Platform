"""
添加演示账号（2026-10-14）。

账号 = 姓名拼音（全小写、连写），密码统一 Demo@123。

⚠️ 密码用 app.core.security.hash_password（bcrypt, cost 取 settings.BCRYPT_ROUNDS），
   **不要**自己 new CryptContext —— seed.py 的注释记了一个坑：
   passlib 1.7.4 必须搭配 bcrypt 4.0.1，直接用可能触发后端探测失败。

幂等：以 username 为键，已存在则更新 password / role_id / status，不存在才插入。
这样重复执行不会报唯一键冲突，也便于「重置这几个账号的密码」。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf-8')

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.security import hash_password

PASSWORD = 'Demo@123'
ROLE_ADMIN_ID = 2      # sys_role: 管理员
ROLE_USER_ID = 1       # sys_role: 普通用户

ADMINS = [
    ('xuchuan', '徐川'),
    ('huangsong', '黄嵩'),
    ('shenyunfei', '申云飞'),
    ('liutingting', '刘婷婷'),
    ('caiyuli', '蔡玉礼'),
    ('yangruikun', '杨睿坤'),
    ('zhengyuhao', '郑宇豪'),
]
USERS = [
    ('jiashijie', '贾世杰'),
]


async def main():
    eng = create_async_engine(settings.database_url)
    try:
        # 先核验角色 id 存在，避免把用户挂到不存在的角色上
        async with eng.connect() as c:
            roles = {r[0]: r[1] for r in (await c.execute(text('SELECT id, role_name FROM sys_role'))).all()}
        print('现有角色:', roles)
        for rid in (ROLE_ADMIN_ID, ROLE_USER_ID):
            if rid not in roles:
                print(f'❌ 角色 id={rid} 不存在，中止')
                return

        plan = [(u, n, ROLE_ADMIN_ID, '管理员') for u, n in ADMINS] + [
            (u, n, ROLE_USER_ID, '普通用户') for u, n in USERS
        ]
        print(f'\n准备写入 {len(plan)} 个账号（密码统一 {PASSWORD}）:')
        for u, n, rid, rn in plan:
            print(f'  {u:<14} {n:<8} → {rn}')

        print('\n开始哈希密码并写入…')
        inserted = updated = 0
        async with eng.begin() as t:
            for username, realname, role_id, role_name in plan:
                pwd = await hash_password(PASSWORD)
                exists = (
                    await t.execute(
                        text('SELECT id FROM sys_user WHERE username = :u'), {'u': username}
                    )
                ).scalar()
                if exists:
                    await t.execute(
                        text(
                            'UPDATE sys_user SET password = :p, role_id = :r, status = 1 WHERE username = :u'
                        ),
                        {'p': pwd, 'r': role_id, 'u': username},
                    )
                    updated += 1
                    print(f'  更新 {username:<14} ({realname})')
                else:
                    await t.execute(
                        text(
                            'INSERT INTO sys_user (username, password, role_id, status) '
                            'VALUES (:u, :p, :r, 1)'
                        ),
                        {'u': username, 'p': pwd, 'r': role_id},
                    )
                    inserted += 1
                    print(f'  新增 {username:<14} ({realname})')
        print(f'\n完成：新增 {inserted} 个，更新 {updated} 个')
    finally:
        await eng.dispose()


asyncio.run(main())