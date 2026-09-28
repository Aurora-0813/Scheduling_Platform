"""
API v1 路由汇总

`main.py` 只 include 这里导出的 `api_router`，各模块负责人把自己的 router
加进下面的 `_ROUTERS` 即可 —— 集中一处注册，避免 main.py 被改乱。

模块 1~8 的 router 由各自负责人按同样方式新增。当前已注册：

| 前缀                       | 模块 | 文件            |
| -------------------------- | ---- | --------------- |
| `/api/v1/voice`            | 1    | `voice.py`      |
| `/api/v1/image`            | 2    | `image.py`      |
| `/api/v1/auth`             | 9    | `auth.py`       |
| `/api/v1/health`、`/ready` | 10   | `health.py`     |
| `/api/v1/monitor`          | 10   | `monitor.py`    |
| `/api/v1/mock`             | 10   | `mock.py`（仅 `DEBUG=true` 注册，见 main.py） |

注意：各模块 router 自身**只写相对前缀**（如 `/image`），完整路径由这里
统一挂到 `API_V1_PREFIX` 下。模块 1/2 原先写的是带 `/api/v1` 的全前缀
（它们当时挂在临时 main.py 上），合并时已对齐，见各自文件顶部说明。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, health, image, monitor, voice

__all__ = ["api_router", "API_V1_PREFIX"]

API_V1_PREFIX = "/api/v1"

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(monitor.router)
api_router.include_router(voice.router)  # 模块 1 语音输入
api_router.include_router(image.router)  # 模块 2 摄像头空间感知
