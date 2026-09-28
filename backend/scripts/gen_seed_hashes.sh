#!/usr/bin/env bash
# ============================================================================
# 生成 docs/seed.sql 所需的 bcrypt 口令哈希
# ----------------------------------------------------------------------------
# 用法：
#     bash scripts/gen_seed_hashes.sh                 # 生成种子数据默认口令的哈希
#     bash scripts/gen_seed_hashes.sh 'My@Pass123'    # 生成指定口令的哈希（可多个）
#
# 为什么要有这个脚本
# ----------------------------------------------------------------------------
# 1. bcrypt 是**加盐**的：同一口令每次算出来的哈希都不同，所以 docs/seed.sql
#    里写死的哈希只是「一份可用的示例」，不是唯一正确的值。想换一次演示口令
#    就得重新算哈希 —— 手工算很容易把 cost 或算法搞错（比如拿 sha256 顶替）。
#    本脚本直接调用**生产代码**的 app.core.security.hash_password，
#    算出来的哈希与登录校验走同一条路径，不会出现「哈希格式对但算法不对」。
# 2. 它只**打印** SQL，不连数据库、不执行任何写操作 —— 种子数据由人执行，
#    这是刻意的（详见脚本末尾说明）。
#
# 注意：哈希里的 `$` 在 SQL 里是普通字符，但在 shell 里会被当变量，因此
# 输出里已经做了转义提示；直接粘贴到 seed.sql 即可（单引号包裹）。
# ============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

# 进入项目环境（与 scripts/dev.sh 同样的处理，见该文件的说明）
CONDA_BASE="${CONDA_BASE:-$HOME/miniconda3}"
if [ -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
    # shellcheck disable=SC1091
    . "$CONDA_BASE/etc/profile.d/conda.sh"
elif command -v conda >/dev/null 2>&1; then
    eval "$(conda shell.bash hook)"
else
    echo "!! 找不到 conda。请设置 CONDA_BASE，或先手动 conda activate smart_dev。" >&2
    exit 1
fi

ENV_NAME="${ENV_NAME:-smart_dev}"
conda activate "$ENV_NAME"

# 把要算哈希的口令交给 python：有参数就用参数，否则用种子数据的默认口令。
# 用 heredoc 避免在命令行里留下明文口令（会进 shell 历史）。
python - "$@" <<'PY'
"""
打印口令对应的 bcrypt 哈希。

默认口令与 docs/seed.sql 的占位口令一一对应（决策：种子数据用显式占位口令，
首次部署后必须立即修改）。
"""
import asyncio
import sys

from app.core.config import settings
from app.core.security import hash_password

# (用户名, 角色, 默认占位口令) —— 改动时请同步 docs/seed.sql 与 docs/deploy.md
SEED_USERS = [
    ("admin", "admin", "Admin@123456"),
    ("resadmin", "resource_admin", "ResAdmin@123456"),
    ("user01", "user", "User@123456"),
]


async def main() -> None:
    rounds = settings.BCRYPT_ROUNDS
    print(f"# bcrypt cost = {rounds}")
    if rounds < 12:
        print(
            "# 警告：cost < 12。生产/演示库的种子数据请用 12（.env 里 BCRYPT_ROUNDS=12），\n"
            "#       否则明文口令的暴力破解成本远低于设计值。"
        )

    passwords = sys.argv[1:]
    if passwords:
        for password in passwords:
            print(f"{password} -> {await hash_password(password)}")
        return

    print("# ---- 可直接粘贴进 docs/seed.sql 的 UPDATE 语句 ----")
    for username, _role, password in SEED_USERS:
        hashed = await hash_password(password)
        print(f"# 用户名={username}  口令={password}")
        print(f"UPDATE sys_user SET password = '{hashed}' WHERE username = '{username}';")
    print(
        "# 只打印不执行：种子数据与迁移都属于数据库写操作，\n"
        "# 请按 docs/deploy.md 的步骤在隧道里人工执行。"
    )


asyncio.run(main())
PY
