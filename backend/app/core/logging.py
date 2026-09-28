"""
结构化日志（项目文档 12.6）

格式为单行 JSON，便于云服务器上用 `jq` 过滤，也便于后续接入日志采集。
示例：

    {"time":"2026-09-27 15:04:05.123","level":"INFO","logger":"app.api.v1.auth",
     "message":"用户登录成功","requestId":"c1f2...","userId":1,"elapsedMs":312.4}

请求 ID
-------
`request_id_var` 是 contextvar，由 `RequestContextMiddleware`（app/middlewares/
request_context.py）在请求进入时设置、退出时重置。日志格式器会自动把它写进
每条日志，因此排查问题时可以用一个 requestId 串起一次请求的全部日志。

刻意**不使用** `python-json-logger`：文档 3.6 的依赖清单里没有它，
自己实现只需十几行，且能保证键名与项目约定一致。
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar, Token
from datetime import datetime
from typing import Any

# 请求 ID 上下文变量。未在请求上下文中时值为 None。
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# 日志中允许直接透传为顶层键的额外字段白名单，防止随意字段污染日志结构
_EXTRA_FIELD_KEY = "extra_fields"


class JsonLogFormatter(logging.Formatter):
    """把日志记录序列化为单行 JSON。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = request_id_var.get()
        if request_id:
            payload["requestId"] = request_id

        # 业务侧通过 logger.info("...", extra={"extra_fields": {...}}) 附加结构化信息
        extra = getattr(record, _EXTRA_FIELD_KEY, None)
        if isinstance(extra, dict):
            payload.update(extra)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # ensure_ascii=False：中文直接可读；出错时降级为原始消息，绝不让
        # 日志格式化本身抛异常（那会把业务请求也带崩）
        try:
            return json.dumps(payload, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return json.dumps(
                {
                    "time": payload["time"],
                    "level": payload["level"],
                    "logger": payload["logger"],
                    "message": str(record.getMessage()),
                    "logFormatError": True,
                },
                ensure_ascii=False,
            )


def setup_logging(level: str | int | None = None) -> None:
    """
    初始化全局日志：根 logger 挂 JSON 格式器，并接管 uvicorn 自身的日志。

    uvicorn 默认给 `uvicorn.*` 设置 `propagate = False`，不清掉它们的 handler
    并打开 propagate 的话，uvicorn 的输出仍是原生格式，日志会一半 JSON
    一半纯文本。
    """
    if level is None:
        level = logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
        uvicorn_logger.setLevel(level)

    # SQLAlchemy 的 echo 走 app.core.database 的 engine(echo=SQL_ECHO)，
    # 这里把 sqlalchemy 自身的 level 提到 WARNING，避免连接池心跳刷屏
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取 logger。用法：`logger = get_logger(__name__)`"""
    return logging.getLogger(name)


def set_request_id(request_id: str) -> Token:
    """设置当前请求的 requestId，返回 token 供后续 reset。"""
    return request_id_var.set(request_id)


def reset_request_id(token: Token) -> None:
    """恢复上一个 requestId（由中间件在 finally 中调用）。"""
    request_id_var.reset(token)


def get_request_id() -> str | None:
    """读取当前请求的 requestId。"""
    return request_id_var.get()
