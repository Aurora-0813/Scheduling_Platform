"""
请求上下文中间件：requestId + 访问日志

职责
----
1. 为每个请求确定一个 `requestId`（上游带了 `X-Request-Id` 就复用，否则
   生成一个 UUID4），放进 contextvar，于是**该请求内的每条日志都自动带上它**；
2. 把它回写到响应头 `X-Request-Id`，前端报错时可以直接把这个值贴给后端；
3. 记一条访问日志，含方法、路径、状态码、耗时、客户端 IP。

requestId 为什么复用上游的值而不是无条件生成
--------------------------------------------
用户入口是 **Nginx**（部署在云服务器上），将来还可能加网关。若链路里的每一跳
都自己生成，那这个 ID 就只能在单机的日志里用，一旦请求跨进程就串不起来。
复用上游 ID 才能做到「一个 ID 串起 Nginx → uvicorn → MySQL」。
**这么做的前提是 Nginx 已经设了它**；若没有，本中间件生成的 UUID 就是源头。

注意：`X-Request-Id` 是**客户端可控的**输入，因此
- 要限制长度并过滤不可打印字符，否则日志里可以注入任意内容（甚至伪造成
  多行、把后续日志搅乱）；
- 它只用于日志关联，**绝不能**用于鉴权或限流的分组键。

未处理异常的堆栈在哪
--------------------
`ServerErrorMiddleware`（Starlette 的最外层）会记下堆栈，它在**本中间件之外**，
因此那一条日志里没有 requestId。排查方式：本中间件在请求失败时也会记一条
**ERROR 级**访问日志（带 requestId 与状态码 500），它与堆栈日志在时间上相邻，
按 `method + path` 即可对上。
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any

from app.core.logging import get_logger, reset_request_id, set_request_id

__all__ = ["RequestContextMiddleware", "REQUEST_ID_HEADER", "REMOTE_IP_HEADER"]

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-Id"
REQUEST_ID_HEADER_BYTES = REQUEST_ID_HEADER.lower().encode("latin-1")

# 反向代理传递真实客户端 IP 的头。仅在**可信代理**（本项目为自建 Nginx）之后
# 才有意义：直连时客户端可以随便伪造它。
REMOTE_IP_HEADER = "X-Real-IP"

# 上游 requestId 的合法形态：只允许可见 ASCII，长度 8~128。
# 太短容易撞车，太长说明对方在灌垃圾；正则同时挡掉了换行、制表符等
# 可以伪造日志行的字符。
_REQUEST_ID_PATTERN = re.compile(r"^[!-~]{8,128}$")

# 最大的 requestId 长度，用于生成时的自检（UUID4 十六进制是 32 字符）
_MAX_HEADER_BYTES = 128


class RequestContextMiddleware:
    """纯 ASGI 中间件。理由见 app/middlewares/__init__.py 的模块说明。"""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        # 非 HTTP（lifespan / websocket）原样透传，否则启动阶段会卡住
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = self._extract_request_id(scope)
        token = set_request_id(request_id)
        start = time.perf_counter()
        status_code = 500  # 应用抛异常时不会走到 response.start，兜底为 500

        async def send_with_request_id(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = [
                    (name, value)
                    for name, value in (message.get("headers") or [])
                    # 下游若已设过同名头则替换，避免出现两个 X-Request-Id
                    if name.lower() != REQUEST_ID_HEADER_BYTES
                ]
                headers.append((REQUEST_ID_HEADER_BYTES, request_id.encode("latin-1")))
                # 不原地改 message：它可能被其他中间件或 ASGI 实现共享
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            self._log_access(scope, status_code, elapsed_ms, request_id)
            # 必须恢复：本中间件可能在一个长生命周期任务里被连续调用多次
            # （测试里的 ASGITransport 就是如此），不恢复会让 requestId 串到
            # 下一个请求的日志上，排查时会被带偏。
            reset_request_id(token)

    # ------------------------------------------------------------------
    def _extract_request_id(self, scope: dict) -> str:
        """取上游的 X-Request-Id（合法时）或生成一个新的。"""
        raw = self._header(scope, REQUEST_ID_HEADER)
        if raw and _REQUEST_ID_PATTERN.match(raw):
            return raw
        return uuid.uuid4().hex

    @staticmethod
    def _header(scope: dict, name: str) -> str | None:
        """
        从 ASGI 的 `scope["headers"]` 里取头。

        ASGI 的头是 `list[tuple[bytes, bytes]]`，且**键是小写的**，
        因此比较前要 lower()；值用 latin-1 解码（ASGI 头不是 UTF-8）。
        """
        target = name.lower().encode("latin-1")
        for key, value in scope.get("headers") or ():
            if key.lower() == target:
                return value.decode("latin-1", errors="replace")
        return None

    def _client_ip(self, scope: dict) -> str | None:
        """
        客户端 IP，仅用于访问日志。

        优先 `X-Real-IP`（Nginx 会设），其次 ASGI 的 `client`（直连时的对端）。
        与 `app/api/v1/auth.py` 的 `_client_ip` 一样：**只进日志**，
        绝不作为鉴权或风控的唯一依据 —— 这两个值都可以伪造。
        """
        real_ip = self._header(scope, REMOTE_IP_HEADER)
        if real_ip:
            return real_ip.strip()
        client = scope.get("client")
        if isinstance(client, (tuple, list)) and client:
            return str(client[0])
        return None

    def _log_access(
        self, scope: dict, status_code: int, elapsed_ms: float, request_id: str
    ) -> None:
        """记一条访问日志。刻意吞掉所有异常：日志失败不能影响响应。"""
        try:
            # query string 可能是 bytes；只在有值时拼接+解码
            raw_query = scope.get("query_string") or b""
            query = raw_query.decode("latin-1") if raw_query else ""
            full_path = scope.get("path", "")
            if query:
                full_path = f"{full_path}?{query}"

            # 5xx 用 ERROR，便于在日志里按级别直接捞；其余 INFO
            log = logger.error if status_code >= 500 else logger.info
            log(
                "请求完成 %s %s -> %s (%sms)",
                scope.get("method", "-"),
                full_path,
                status_code,
                elapsed_ms,
                extra={
                    "extra_fields": {
                        "method": scope.get("method"),
                        "path": scope.get("path"),
                        "query": query,
                        "status": status_code,
                        "elapsedMs": elapsed_ms,
                        "clientIp": self._client_ip(scope),
                        "requestId": request_id,
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001 - 访问日志不能影响请求
            logger.warning("访问日志写入失败: %s: %s", type(exc).__name__, exc)
