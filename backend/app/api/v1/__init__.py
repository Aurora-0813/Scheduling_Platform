"""
API v1 路由汇总

`main.py` 只 include 这里导出的 `api_router`，各模块负责人把自己的 router
加进下面的注册区即可 —— 集中一处注册，避免 main.py 被改乱。

模块 1~8 的 router 由各自负责人按同样方式新增。当前已注册：

| 前缀                       | 模块 | 文件            |
| -------------------------- | ---- | --------------- |
| `/api/v1/voice`            | 1    | `voice.py`      |
| `/api/v1/image`            | 2    | `image.py`      |
| `/api/v1/orders` 等        | 3    | `app/api/*.py`（见下） |
| `/api/v1/agent`            | 4    | `agent.py`      |
| `/api/v1/dashboard`        | 8    | `dashboard.py`  |
| `/api/v1/auth`             | 9    | `auth.py`       |
| `/api/v1/health`、`/ready` | 10   | `health.py`     |
| `/api/v1/monitor`          | 10   | `monitor.py`    |
| `/api/v1/mock`             | 10   | `mock.py`（仅 `DEBUG=true` 注册，见 main.py） |

模块 3 的路由文件放在 **`app/api/`**（不在 `v1/` 下）：`orders.py`、`resources.py`、
`messages.py`、`agent.py`、`conflicts.py`。它们自身已带相对前缀
（`/orders`、`/resources`…），在这里注册即可挂到 `API_V1_PREFIX` 下，
最终路径与团队其它模块一致，**不要**再额外加 `/api/v1` 前缀。

模块 3 另有一条 WebSocket 推送通道 `/ws/notify`，**不走** `API_V1_PREFIX`，
单独注册在 `main.py`。

注意：各模块 router 自身**只写相对前缀**（如 `/image`），完整路径由这里
统一挂到 `API_V1_PREFIX` 下。模块 1/2 原先写的是带 `/api/v1` 的全前缀
（它们当时挂在临时 main.py 上），合并时已对齐，见各自文件顶部说明。

⚠️ **本目录下唯一不存在的路由类别是 `/api/v1/tools/*`，且必须永远不存在**
（主文档 5.3 / 9.3、阶段 6 §3.1 第 4 条）。

`app/agent/tools/` 下那 5 个函数的形状（入参是简单类型、返回 dict）**看起来**
就像可以直接暴露成一排 HTTP 接口，很容易顺手 `include_router` 上去。不能这么做：
那些 Tool 的身份来自调用上下文（`app/agent/context.py`），一旦变成 HTTP 端点，
调用者的 `user_id` 就没有来源，只能从请求体读——那等于把「替谁预约」交给客户端决定，
与主文档 5.1/9.1 直接冲突。阶段 6 的验收第 ⑥ 步专门请求 `/api/v1/tools/query_spaces`
确认返回 404。

**2026-09-28 合并 `origin/main`（`9f30d3a`）时在这里做了两处并集**

1. **补回 `agent.router` 的注册**：正式版此前没有 `agent.py`（模块 4 的端点还在这条分支上），
   两条分支各自实现了一个注册中枢，正式版是**本文件**，模块 4 是 `api/v1/router.py`。
2. **`api/v1/router.py` 已删除**：同一份路由集合存在两个中枢是隐患——两者都自称
   `api_router`，只是前缀与 DEBUG 门控的写法不同，谁 import 错谁就换一套路由。
   现以本文件为唯一中枢；mock 的 `DEBUG` 门控按正式版保留在 `main.py`（`if settings.DEBUG:`），
   不在本文件重复判断。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import conflicts, messages, orders, resources
from app.api.v1 import agent, auth, dashboard, health, image, monitor, voice

__all__ = ["api_router", "API_V1_PREFIX"]

API_V1_PREFIX = "/api/v1"

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(monitor.router)
api_router.include_router(voice.router)  # 模块 1 语音输入
api_router.include_router(image.router)  # 模块 2 摄像头空间感知

# 模块 3 移动端预约与通知（路由文件在 app/api/，前缀写在各自 router 上）
# ⚠️ 模块 3 的 app/api/agent.py **不注册**：其 /agent/schedule 与模块 4 的
#    app/api/v1/agent.py 路径重复（后者是走 LangChain 的真实调度实现），
#    其 /agent/transcribe、/agent/recognize 是文件内自述的占位实现，已由
#    /api/v1/voice/asr 与 /api/v1/image/analyze 取代。
api_router.include_router(orders.router)
api_router.include_router(resources.router)
api_router.include_router(messages.router)

api_router.include_router(agent.router)  # 模块 4 核心调度 Agent
api_router.include_router(dashboard.router)  # 模块 8 AI 数据洞察面板
