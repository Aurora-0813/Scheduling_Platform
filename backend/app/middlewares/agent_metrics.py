"""
Agent 调用埋点中间件（模块 10 的 `/monitor/agent` 数据来源）

为什么做成中间件
----------------
文档 5.3 要求 `/monitor/agent` 返回「大模型调用次数、成功率、平均耗时」。
最直接的实现是在模块 4 的每个 Agent 接口里加一行 `record(...)`，
但那样有三个问题：

1. **改动面扩散到 4 个人的代码**，任何一处漏加就少统计一次，且不报错；
2. 新增 Agent 接口时容易忘；
3. 埋点代码进入业务函数后，一旦它抛异常就是业务接口 500 ——
   本项目的答辩现场正需要 Agent 接口稳定。

中间件放在 HTTP 层，**只依赖状态码与耗时**，因此对业务代码零侵入：
模块 4 新加多少个 Agent 接口都自动被统计，一行都不用改。

口径（与 app/core/metrics.py、app/schemas/monitor.py 保持一致）
--------------------------------------------------------------
| 项           | 口径                                                      |
| ------------ | --------------------------------------------------------- |
| 统计范围      | 路径等于 `/api/v1/agent` 或以 `/api/v1/agent/` 开头        |
| `totalCalls` | **HTTP 请求数**（不是 token 数；流式响应算 1 次）           |
| 成功判定      | HTTP 状态码 `< 400`（只看传输层，不看业务码）              |
| 耗时          | 从进入本中间件到响应头发出（含下游全部处理时间）           |
| 降级          | 由下游响应头 `X-Agent-Degraded: 1` 显式标记（见下）         |

为什么按状态码判成功、而不是看业务码
------------------------------------
中间件拿到的是 ASGI 消息，**看不到响应体** —— 要读业务码就必须把整个响应体
缓冲下来解析，那样会破坏模块 4 的 SSE 流式响应。按状态码判定：
- 不用缓冲，流式安全；
- 与「服务可用性」的常规口径一致（5xx/4xx 即不健康）。

代价是「HTTP 200 但业务上失败」计为成功。业务层的失败率请由各自的
业务日志/告警覆盖，不要试图塞进这个指标 —— 那会让口径变得没人说得清。

降级次数为什么由下游用响应头标记
--------------------------------
「本次是大模型降级返回」只有业务代码知道（比如 JSON 解析失败后改用自然语言）。
中间件无法从状态码推断。约定模块 4 在降级时加一个响应头：

    response.headers["X-Agent-Degraded"] = "1"

读头是零成本的（响应头本来就在 ASGI 消息里），不破坏流式。模块 4 没加这个头
时降级次数恒为 0 —— 这是**已知的、可接受的**现状，`docs/api.md` 里会写明
调用方只需自行加上该头即可生效，无需改动本文件。
"""

from __future__ import annotations

import time
from typing import Any

from app.core.logging import get_logger
from app.core.metrics import get_metric_store

__all__ = [
    "AgentMetricsMiddleware",
    "AGENT_PATH_PREFIX",
    "AGENT_PATH_ROOT",
    "DEGRADED_HEADER",
    "DEGRADED_HEADER_BYTES",
]

# 与 app/api/v1/__init__.py 的 API_V1_PREFIX 拼接后的结果。
# 这里写死字符串而不是 import：中间件在 ASGI 栈上，避免为了拼一个前缀
# 而把整个路由模块（含所有 service）拉进 import 图。
AGENT_PATH_ROOT = "/api/v1/agent"
AGENT_PATH_PREFIX = AGENT_PATH_ROOT + "/"

DEGRADED_HEADER = "X-Agent-Degraded"
DEGRADED_HEADER_BYTES = DEGRADED_HEADER.lower().encode("latin-1")

# 视为「降级」的取值。刻意只认这几种，不把 "0"/"false" 误判成真。
_TRUTHY = frozenset({"1", "true", "yes", "y"})

logger = get_logger(__name__)


class AgentMetricsMiddleware:
    """纯 ASGI 中间件。理由见 app/middlewares/__init__.py 的模块说明。"""

    def __init__(
        self,
        app: Any,
        *,
        root_path: str = AGENT_PATH_ROOT,
        path_prefix: str = AGENT_PATH_PREFIX,
    ) -> None:
        self.app = app
        # 允许注入，便于测试直接构造独立的路径范围
        self.root_path = root_path
        self.path_prefix = path_prefix

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not self.matches(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code = 500
        degraded = False

        async def send_inspect(message: dict) -> None:
            nonlocal status_code, degraded
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                degraded = self._is_degraded(message.get("headers") or ())
            await send(message)

        try:
            await self.app(scope, receive, send_inspect)
        except Exception:
            # 下游抛异常时状态码保持 500，仍要计一次失败 ——
            # 漏计会让成功率虚高，比多计一次失败危险得多。
            # 异常本身原样抛给上层：统一响应体由 response.py 的处理器生成，
            # 中间件不自己造 500 响应，否则会出现两套响应结构。
            raise
        finally:
            latency_ms = (time.perf_counter() - start) * 1000.0
            await self._record(
                latency_ms=latency_ms,
                success=status_code < 400,
                degraded=degraded,
                path=scope.get("path", ""),
            )

    def matches(self, path: str) -> bool:
        """是否属于 Agent 接口。`/api/v1/agentx` 不算（前缀必须带 `/`）。"""
        return path == self.root_path or path.startswith(self.path_prefix)

    # ------------------------------------------------------------------
    @staticmethod
    def _is_degraded(headers: Any) -> bool:
        for name, value in headers:
            if name.lower() == DEGRADED_HEADER_BYTES:
                return value.decode("latin-1", errors="replace").strip().lower() in _TRUTHY
        return False

    @staticmethod
    async def _record(*, latency_ms: float, success: bool, degraded: bool, path: str) -> None:
        """
        写一次埋点。**永不抛异常**。

        这里连 `get_metric_store()` 一起包住：它内部会惰性创建 Redis 客户端，
        而连接池构造在配置异常时也会抛。埋点故障绝不能把 Agent 接口带崩 ——
        这条保证由 `tests/api/test_monitor_api.py` 的故障隔离回归测试守住。
        """
        try:
            store = get_metric_store()
            await store.record_agent_call(latency_ms=latency_ms, success=success, degraded=degraded)
        except Exception as exc:  # noqa: BLE001 - 埋点不得影响业务
            # 不能用 logger.exception：栈信息在这里没有价值（原因总是
            # 「Redis 不可用」），而每次 Agent 调用都打一次栈会把日志刷爆。
            logger.warning("Agent 埋点失败（已忽略）path=%s: %s: %s", path, type(exc).__name__, exc)
