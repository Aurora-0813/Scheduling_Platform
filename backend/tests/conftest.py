"""pytest 公共引导（§3.7 / §6.8 / §10.2）。

**测试库隔离**：在导入 `app` 之前把 `DATABASE_URL` 覆盖为临时 SQLite
（§13.1 自测路径），确保**任何子目录**的用例全程不触碰云库 `smart_scheduler_dev`。
环境变量优先级高于 `.env`，因此不会被 `.env` 里的云库配置覆盖。

这段必须放在顶层、而不是某个模块子目录：它要**先于任何 `app` 导入**执行，
而 pytest 会先导入外层 conftest、再进入子目录。

用例按模块分目录（团队 `backend/tests/` 由各模块共用同一目录）：
- `tests/module3/`  移动端预约与通知模块（本模块，含独立测试库夹具与 86 条用例）
- `tests/module4/`  核心调度 Agent（团队骨架，待模块 4 补齐）
"""
import os
import pathlib
import sys
import tempfile

# ① 必须先于任何 app 导入执行
TEST_DB = pathlib.Path(tempfile.gettempdir()) / "smart_scheduler_test.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB.as_posix()}"

# ② 兜底把 backend/ 加入 sys.path，保证 `import app` 可用
BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
