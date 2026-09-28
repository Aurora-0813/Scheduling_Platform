"""
统一响应体（API 层入口）

实现放在 `app/core/response.py`：异常处理器要在那里注册，它必须能在不 import
任何 router 的前提下拿到 `ApiResponse`。本模块把它转发出来，并补一个
`ErrorResponse` —— 用于在 router 上声明 `responses={401: {"model": ErrorResponse}}`，
让 `/docs` 里每个接口都展示统一的错误信封（项目文档 5.2）。
"""

from __future__ import annotations

from app.core.camel import CamelModel
from app.core.response import ApiResponse, ok

__all__ = ["ApiResponse", "ErrorResponse", "FieldError", "ok"]


class FieldError(CamelModel):
    """
    参数校验失败时的单条错误。

    `field` 已转成 camelCase（与请求体字段名一致），前端可直接定位表单项。
    """

    field: str
    message: str


class ErrorResponse(CamelModel):
    """
    失败响应体：与成功响应的结构完全一致，仅 `code != 200`。

    仅用于 OpenAPI 文档展示。实际返回由 app/core/response.py 的异常处理器
    构造（走 `error_payload()`），保证两种路径的形状永远不会漂移 ——
    若改成在路由里手写错误响应，就会出现「文档一种形状、实际另一种」的问题。
    """

    code: int
    message: str
    data: dict[str, list[FieldError]] | None = None
