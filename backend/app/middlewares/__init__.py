"""
中间件（纯 ASGI 实现）

为什么手写纯 ASGI 而不是用 `BaseHTTPMiddleware`
------------------------------------------------
`starlette.middleware.base.BaseHTTPMiddleware` 的实现方式是：把下游应用跑在
一个独立任务里，用 anyio 的内存对象流把请求体与响应体**逐块搬运**。

副作用有两个，都踩在本项目的要害上：

1. **contextvar 不传播**。`BaseHTTPMiddleware` 在另一个任务里执行下游，
   `app/core/logging.py` 的 `request_id_var` 以及 SQLAlchemy 的会话上下文
   都会在跨越这个边界后失效。如果本中间件用 `BaseHTTPMiddleware`，
   业务日志里就**不会**带上 requestId —— 而带 requestId 正是它的全部意义。
   纯 ASGI 中间件与下游共享同一个协程上下文，contextvar 天然可见。
2. **流式响应被缓冲**。`BaseHTTPMiddleware` 会消费整个响应体再重新分段，
   模块 4 的 SSE（大模型逐字输出）会因此在中间件里卡住直到生成结束，
   「流式」退化成一次性返回。

代价是必须自己处理 `send` 消息协议，代码略长 —— 换来的正确性值这个价。

编写纯 ASGI 中间件的三条纪律
----------------------------
1. 只处理 `scope["type"] == "http"`，其余（`lifespan`、`websocket`）
   必须原样透传，否则 uvicorn 的 lifespan 协议会被打断、启动即失败。
2. 想改响应头必须**重建 message 字典**再 `await send(...)`，不要原地改
   （`message` 可能被其他中间件共享）。
3. 中间件里抛异常会变成 500，因此凡是非核心逻辑（日志、埋点）都要自己
   兜住异常 —— 可观测性设施绝不能把业务请求带崩。
"""

from __future__ import annotations

from app.middlewares.agent_metrics import AgentMetricsMiddleware
from app.middlewares.request_context import RequestContextMiddleware

__all__ = ["RequestContextMiddleware", "AgentMetricsMiddleware"]
