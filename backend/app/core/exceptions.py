"""统一异常处理：所有异常转成 {code, message, data} 响应体（§5.2 / §7.3）。

同时落日志：500 与校验失败均记录，避免生产环境「静默失败」难排查。
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.status_code, "message": str(exc.detail), "data": None},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        msg = first.get("msg", "参数校验失败")
        if isinstance(msg, str):
            msg = msg.replace("Value error, ", "")
        loc = first.get("loc", [])
        field = loc[-1] if loc else None
        detail = f"{field}: {msg}" if field and str(field) != "body" else str(msg)
        logger.warning("参数校验失败 %s %s -> %s", request.method, request.url.path, detail)
        return JSONResponse(
            status_code=422,
            content={"code": 422, "message": detail, "data": None},
        )

    @app.exception_handler(Exception)
    async def _generic(request: Request, exc: Exception):
        logger.exception("未捕获异常 %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"code": 500, "message": "服务器内部错误", "data": None},
        )

    # 状态机非法流转兜底 -> 409（正常流程已先 can_transition 拦截）
    from ..state_machine import IllegalTransitionError

    @app.exception_handler(IllegalTransitionError)
    async def _illegal(request: Request, exc: IllegalTransitionError):
        return JSONResponse(
            status_code=409,
            content={"code": 409, "message": str(exc), "data": None},
        )
