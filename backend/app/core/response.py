"""
统一响应体与全局异常收口

响应结构（项目文档 5.2）
------------------------
成功：`{"code": 200, "message": "操作成功", "data": {...}}`
失败：`{"code": 40001, "message": "参数校验未通过", "data": {"errors": [...]}}`

成功与失败**结构完全一致**，前端只需判断 `code === 200`。
`code` 是业务码（见 app/core/error_codes.py），HTTP 状态码另算：
例如账号禁用返回 HTTP 403 + code 40108。

by_alias 的坑
-------------
Pydantic 的 `model_dump()` 默认输出 snake_case，只有显式 `by_alias=True`
才是 camelCase。异常处理器里手写的 dict 若漏了这一步，会出现
「成功响应 accessToken、报错响应 access_token」—— 平时测不出来，
只在前端走错误分支时炸。本文件所有出参统一经过 `jsonable_encoder(by_alias=True)`。
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.camel import CamelModel, to_camel_alias
from app.core.error_codes import DEFAULT_MESSAGES, ErrorCode
from app.core.exceptions import BizError
from app.core.logging import get_logger

__all__ = [
    "ApiResponse",
    "ok",
    "success",
    "fail",
    "error_payload",
    "register_exception_handlers",
]

logger = get_logger(__name__)

T = TypeVar("T")


class ApiResponse(CamelModel, Generic[T]):
    """统一响应体。用作 FastAPI 的 `response_model` 以获得准确的接口文档。"""

    code: int = ErrorCode.SUCCESS
    message: str = "操作成功"
    data: T | None = None


def ok(data: Any = None, message: str = "操作成功") -> ApiResponse[Any]:
    """构造成功响应。"""
    return ApiResponse(code=ErrorCode.SUCCESS, message=message, data=data)


def error_payload(code: int, message: str | None = None, data: Any = None) -> dict[str, Any]:
    """构造失败响应体的 dict 形态（供异常处理器返回 JSONResponse 使用）。"""
    return {
        "code": code,
        "message": message or DEFAULT_MESSAGES.get(code, "服务异常"),
        "data": data,
    }


# ===========================================================================
# 模块 1 / 模块 2 兼容层：success() / fail()
# ===========================================================================
# 背景
# ----
# 模块 1（语音输入）与模块 2（摄像头空间感知）在基础支撑交付前，曾自建过一版
# 临时的 app/core/response.py，提供了 success() / fail() 两个构造函数，并在
# 交付说明中写明「直接覆盖本文件即可，只要保持 success() / fail() 的函数签名
# 与响应体结构不变，模块无需改动」。
#
# 本模块是正式实现，主 API 为 ok() / error_payload()（返回 ApiResponse 模型，
# 便于 FastAPI 生成准确的接口文档）。为不改动两个模块的既有代码，这里补充
# 同名兼容函数，语义完全等价：
#
#     ok()            ←→  success()
#     error_payload() ←→  fail()
#
# 与主 API 的唯一差别：兼容函数直接返回 **dict**，即临时实现原本的返回形态，
# 确保模块内 `return success(...)` / `return fail(...)` 的既有写法行为不变
# （FastAPI 会依据路由上的 response_model=ApiResponse[...] 做校验与序列化）。
# 新写的代码请优先使用 ok() / error_payload()。


def success(data: Any = None, message: str = "操作成功") -> dict[str, Any]:
    """
    构造成功响应体（兼容层，等价于 `ok()`，返回 dict 形态）。

    参数：
        data    : 业务数据，可以是 Pydantic 模型 / dict / list / None
        message : 提示信息，默认「操作成功」

    返回：
        `{"code": 200, "message": "...", "data": ...}`
    """
    return {"code": ErrorCode.SUCCESS, "message": message, "data": data}


def fail(code: int, message: str | None = None, data: Any = None) -> dict[str, Any]:
    """
    构造失败响应体（兼容层，等价于 `error_payload()`，返回 dict 形态）。

    参数：
        code    : 业务错误码，见 app/core/error_codes.py
        message : 面向用户的友好提示；省略时取码表默认文案
        data    : 失败时通常为 None；特定场景可携带部分数据（如候选列表）

    返回：
        `{"code": 41003, "message": "...", "data": null}`
    """
    return error_payload(code, message, data)


def _json_response(
    payload: dict[str, Any], http_status: int, headers: dict[str, str] | None = None
) -> JSONResponse:
    """dict → JSONResponse。

    `jsonable_encoder` 显式传 `by_alias=True`：payload 里若嵌了 Pydantic 模型
    （例如异常携带的 data），这一步保证它按 camelCase 输出。
    """
    return JSONResponse(
        status_code=http_status,
        content=jsonable_encoder(payload, by_alias=True),
        headers=headers,
    )


# ==========================================================================
# 参数校验错误的中文提示
# ==========================================================================
_VALIDATION_MESSAGES: dict[str, str] = {
    "missing": "该字段为必填项",
    "string_type": "必须是字符串",
    "string_too_short": "长度不足",
    "string_too_long": "长度超出限制",
    "string_pattern_mismatch": "格式不正确",
    "int_type": "必须是整数",
    "int_parsing": "必须是整数",
    "float_parsing": "必须是数字",
    "decimal_parsing": "必须是数字",
    "bool_type": "必须是布尔值",
    "bool_parsing": "必须是布尔值",
    "datetime_parsing": "时间格式不正确，应为 YYYY-MM-DD HH:mm:ss",
    "datetime_from_date_parsing": "时间格式不正确，应为 YYYY-MM-DD HH:mm:ss",
    "date_parsing": "日期格式不正确，应为 YYYY-MM-DD",
    "time_delta_parsing": "时长格式不正确",
    "enum": "取值不在允许范围内",
    "greater_than": "数值过小",
    "greater_than_equal": "数值过小",
    "less_than": "数值过大",
    "less_than_equal": "数值过大",
    "list_type": "必须是数组",
    "dict_type": "必须是对象",
    "json_invalid": "请求体不是合法的 JSON",
    "value_error": "取值不合法",
    "extra_forbidden": "存在不支持的字段",
}

# 请求位置前缀，出现在 Pydantic 的 loc 里但对前端无意义，需剔除
_LOC_PREFIXES = frozenset({"body", "query", "path", "header", "cookie"})


def _format_validation_error(err: dict[str, Any]) -> dict[str, str]:
    """把单条 Pydantic 错误转成 `{field, message}`。"""
    loc = tuple(err.get("loc") or ())
    parts = [str(item) for item in loc if str(item) not in _LOC_PREFIXES]

    # 路径每一段都转 camelCase（数字下标保持原样），
    # 这样无论前端传 userName 还是 user_name，报错里的字段名是一致的
    camel_parts = [part if part.isdigit() else to_camel_alias(part) for part in parts]
    field = ".".join(camel_parts) or "body"

    err_type = err.get("type", "")
    ctx = err.get("ctx") or {}
    message = _VALIDATION_MESSAGES.get(err_type) or err.get("msg") or "参数不合法"

    # 把约束条件补进提示，例如「长度不足（要求 6）」
    if err_type in ("string_too_short", "string_too_long") and ctx.get("limit") is not None:
        message = f"{message}（要求 {ctx['limit']}）"
    elif err_type == "greater_than" and ctx.get("gt") is not None:
        message = f"{message}（须大于 {ctx['gt']}）"
    elif err_type == "greater_than_equal" and ctx.get("ge") is not None:
        message = f"{message}（须不小于 {ctx['ge']}）"
    elif err_type == "less_than" and ctx.get("lt") is not None:
        message = f"{message}（须小于 {ctx['lt']}）"
    elif err_type == "less_than_equal" and ctx.get("le") is not None:
        message = f"{message}（须不大于 {ctx['le']}）"
    elif err_type == "enum" and ctx.get("expected") is not None:
        message = f"{message}：{ctx['expected']}"

    return {"field": field, "message": message}


# ==========================================================================
# 兼容层：模块 7 的旧异常名
# ==========================================================================
class ApiError(Exception):
    """模块 7 旧名：业务异常（`notify_templates.py` 与两个测试在 import）。

    ⚠️ 刻意**不**继承 `app.core.exceptions.BizError`：`exceptions.py` 在模块顶部
    `from app.core.error_codes import ...` / 与 response.py 有既有依赖方向，
    反向 import 会成环，且在 `main.py` 的导入顺序下会直接 ImportError。
    因此独立成类，由 `register_exception_handlers` 单独挂处理器 ——
    保证它抛出来同样是统一响应体，而不是 FastAPI 默认的 `{"detail": ...}`。
    """

    def __init__(
        self,
        message: str,
        *,
        code: int = 400,
        http_status: int | None = None,
        data: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        # HTTP 状态码默认由业务码推出（本项目约定 HTTP = code // 100）；
        # 推不出合法状态码时退回 400。显式传 http_status 则以其为准。
        derived = code // 100
        self.http_status = (
            http_status if http_status is not None else (derived if 400 <= derived <= 599 else 400)
        )
        self.data = data


# ==========================================================================
# 异常处理器注册
# ==========================================================================
def register_exception_handlers(app: FastAPI) -> None:
    """把所有异常收敛成统一响应体。应在 `app = FastAPI(...)` 之后立刻调用。"""

    @app.exception_handler(BizError)
    async def _handle_biz_error(request: Request, exc: BizError) -> JSONResponse:
        """业务异常：按异常自带的业务码与 HTTP 状态返回。"""
        # 5xx 说明是服务端问题，要留日志；4xx 是调用方问题，用 info 即可
        log = logger.error if exc.http_status >= 500 else logger.info
        log(
            "业务异常: %s %s -> code=%s http=%s message=%s",
            request.method,
            request.url.path,
            exc.code,
            exc.http_status,
            exc.message,
            extra={"extra_fields": {"code": exc.code, "httpStatus": exc.http_status}},
        )
        return _json_response(error_payload(exc.code, exc.message, exc.data), exc.http_status)

    @app.exception_handler(ApiError)
    async def _handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        """模块 7 兼容层的 `ApiError`：与 `BizError` 同一套信封，不穿透成 `{"detail": ...}`。"""
        log = logger.error if exc.http_status >= 500 else logger.info
        log(
            "业务异常(ApiError): %s %s -> code=%s http=%s message=%s",
            request.method,
            request.url.path,
            exc.code,
            exc.http_status,
            exc.message,
            extra={"extra_fields": {"code": exc.code, "httpStatus": exc.http_status}},
        )
        return _json_response(error_payload(exc.code, exc.message, exc.data), exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """请求参数校验失败 → HTTP 400 / code 40001。"""
        errors = [_format_validation_error(err) for err in exc.errors()]
        if errors:
            first = errors[0]
            message = f"参数校验未通过：{first['field']} {first['message']}"
        else:
            message = DEFAULT_MESSAGES[ErrorCode.PARAM_INVALID]

        logger.info(
            "参数校验失败: %s %s -> %s",
            request.method,
            request.url.path,
            errors,
            extra={"extra_fields": {"validationErrors": errors}},
        )
        return _json_response(
            error_payload(ErrorCode.PARAM_INVALID, message, {"errors": errors}),
            400,
        )

    @app.exception_handler(ResponseValidationError)
    async def _handle_response_validation_error(
        request: Request, exc: ResponseValidationError
    ) -> JSONResponse:
        """
        出参不符合声明的 response_model —— 这是**服务端 bug**，不是调用方问题。

        返回 500 并在日志里打全 stack，避免把内部结构暴露给前端。
        """
        logger.exception("出参校验失败（服务端缺陷）: %s %s", request.method, request.url.path)
        return _json_response(error_payload(ErrorCode.INTERNAL_ERROR), 500)

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Starlette/FastAPI 原生的 HTTPException（如未知路由 404、方法不允许 405）。"""
        code = _STATUS_TO_CODE.get(exc.status_code, ErrorCode.BAD_REQUEST)
        detail = exc.detail if isinstance(exc.detail, str) and exc.detail else None
        message = _STATUS_MESSAGES.get(exc.status_code) or detail or DEFAULT_MESSAGES.get(code)
        # 401 需要透传 WWW-Authenticate 之类的响应头
        headers = dict(exc.headers) if exc.headers else None
        return _json_response(error_payload(code, message), exc.status_code, headers)

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """未预期异常 → HTTP 500 / code 50000。

        堆栈只进日志（JSON 日志的 exception 字段），绝不进响应体，
        避免泄露表名、SQL 或文件路径（项目文档 13 风险登记）。
        """
        logger.exception("未处理异常: %s %s", request.method, request.url.path)
        return _json_response(error_payload(ErrorCode.INTERNAL_ERROR), 500)


# HTTP 状态码 → 业务码的兜底映射
_STATUS_TO_CODE: dict[int, int] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.BAD_REQUEST,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.PARAM_INVALID,
    429: ErrorCode.TOO_MANY_REQUESTS,
    500: ErrorCode.INTERNAL_ERROR,
    502: ErrorCode.AI_OUTPUT_INVALID,
    503: ErrorCode.SERVICE_UNAVAILABLE,
}

# 少数状态码的默认文案覆盖 FastAPI 内置的英文 detail
_STATUS_MESSAGES: dict[int, str] = {
    404: "接口或资源不存在",
    405: "请求方法不被允许",
}
