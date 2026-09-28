#!/usr/bin/env bash
# ============================================================================
# 一键启动后端开发服务（项目文档 8.9）
# ----------------------------------------------------------------------------
# 用法（在任意目录都可以，脚本会自己切到仓库根）：
#     bash scripts/dev.sh
#
# 可用环境变量：
#     ENV_NAME=smart_dev   conda 环境名
#     HOST=0.0.0.0         监听地址（0.0.0.0 允许同一局域网内的手机调试小程序）
#     PORT=8000            监听端口
#     RELOAD=1             1=代码改动自动重启（默认）；0=不重启
#     MIGRATE=1            启动前先跑 alembic upgrade head（默认不跑）
#     SKIP_INSTALL=1       跳过 pip install（日常重启不必每次装依赖）
#
# 与项目文档 8.9 的差异
# ----------------------------------------------------------------------------
# 文档里的脚本假定它位于**仓库根**的 scripts/ 下（`cd "$(dirname "$0")/../backend"`）。
# 本仓库当前定位是 monorepo 的 backend/ 子目录，脚本在 backend/scripts/ 下，
# 因此改成 `cd "$(dirname "$0")/.."` —— 无论 scripts/ 在 backend/ 里还是在
# monorepo 根，只要它与 app/ 同级，两种位置都能正确工作。
# ============================================================================
set -euo pipefail

ENV_NAME="${ENV_NAME:-smart_dev}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
RELOAD="${RELOAD:-1}"

# 切到仓库根：本脚本在 <root>/scripts/ 下，上一级就是根
cd "$(dirname "$0")/.."

echo "==> 工作目录: $(pwd)"

# ---------------------------------------------------------------------------
# 1. 检查 .env
# ---------------------------------------------------------------------------
# 启动时缺 DB_PASSWORD 不会报错，只会让 /ready 显示 db=error、登录接口 500，
# 新手很容易在这里绕远路。所以缺文件就直接停住并说清楚该做什么。
if [ ! -f .env ]; then
    echo "!! 缺少 .env 文件。它不会进仓库（见 .gitignore），每人需要自己建一份：" >&2
    echo "     cp .env.example .env" >&2
    echo "   然后至少填写 DB_PASSWORD 与 JWT_SECRET_KEY（后者生成方式见 .env.example 注释）。" >&2
    exit 1
fi

# 日志里有中文，Git Bash / MSYS 下手动指定编码可以少一类 mojibake
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

# ---------------------------------------------------------------------------
# 2. 进入 conda 环境
# ---------------------------------------------------------------------------
# 非交互式 bash 里 `conda activate` 默认不可用（conda 的 shell 函数没被加载），
# 所以先把 conda.sh 载进来。优先用固定路径（Windows 上的 Git Bash 常常找不到
# conda 命令，但安装目录是确定的），找不到再退回 `conda shell.bash hook`。
CONDA_BASE="${CONDA_BASE:-$HOME/miniconda3}"
if [ -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
    # shellcheck disable=SC1091
    . "$CONDA_BASE/etc/profile.d/conda.sh"
elif command -v conda >/dev/null 2>&1; then
    eval "$(conda shell.bash hook)"
else
    echo "!! 找不到 conda。请设置 CONDA_BASE，或改用已激活环境的 shell 直接执行：" >&2
    echo "     conda activate $ENV_NAME && uvicorn app.main:app --reload" >&2
    exit 1
fi

conda activate "$ENV_NAME"
echo "==> 已激活 conda 环境: $ENV_NAME ($(python -V 2>&1))"

# ---------------------------------------------------------------------------
# 3. 安装依赖
# ---------------------------------------------------------------------------
if [ "${SKIP_INSTALL:-0}" = "1" ]; then
    echo "==> 跳过依赖安装（SKIP_INSTALL=1）"
else
    # 用 lock 文件而不是 requirements.txt：间接依赖也必须一致，
    # 否则会出现「我这能跑、你那报 AttributeError」这种最难查的问题。
    echo "==> 安装依赖（requirements.lock）"
    pip install -r requirements.lock
fi

# ---------------------------------------------------------------------------
# 4. 数据库迁移（可选）
# ---------------------------------------------------------------------------
if [ "${MIGRATE:-0}" = "1" ]; then
    echo "==> 执行数据库迁移（alembic upgrade head）"
    # 必须用 `alembic` 控制台脚本，**不要**用 `python -m alembic`：
    # 仓库根目录下有个同名的 alembic/ 迁移目录，从仓库根用 -m 启动时
    # 它会作为命名空间包遮蔽真正的 alembic 包，报 No module named alembic.__main__。
    # 迁移会连 .env 里的库；隧道没起时这里会失败 —— 这是预期行为，先起隧道。
    alembic upgrade head
fi

# ---------------------------------------------------------------------------
# 5. 启动
# ---------------------------------------------------------------------------
cat <<EOF
==> 启动 uvicorn
    接口文档   http://127.0.0.1:$PORT/docs
    存活探针   http://127.0.0.1:$PORT/api/v1/health
    就绪探针   http://127.0.0.1:$PORT/api/v1/ready   (M1 验收看这个)

    提示：RELOAD=1 时进程会随代码改动重启。若 REDIS_ENABLED=false，
    刷新令牌白名单在内存里，每次重启都会让已登录用户掉线 ——
    演示或联调时请用 SKIP_INSTALL=1 RELOAD=0 bash scripts/dev.sh。
EOF

uvicorn_args=(app.main:app --host "$HOST" --port "$PORT")
if [ "$RELOAD" = "1" ]; then
    uvicorn_args+=(--reload)
fi

exec uvicorn "${uvicorn_args[@]}"
