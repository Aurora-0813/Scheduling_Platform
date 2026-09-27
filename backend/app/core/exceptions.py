"""
统一异常处理模块
====================================================================
⚠️ 临时实现，待基础支撑与集成组接管

    集成组交付正式的 core/exceptions.py 后，覆盖本文件即可。
    唯一要求：保留 BusinessError 类名与 (code, message) 构造签名，
    因为各业务模块（含模块 2）都继承它。

规范依据：
    开发流程.md §4.3：统一异常处理 —— API 调用失败、大模型返回格式错误、
                      图片解析失败均设置友好降级提示
    开发流程.md §7.3：统一异常处理在 core/ 目录

设计要点：
    1. BusinessError 是业务异常的基类，携带业务错误码。
       各模块只需定义子类或直接抛 BusinessError(code=..., message=...)，
       全局处理器会自动转成统一响应体，模块代码里不用写任何 try/except 返回。
    2. 未捕获的异常统一兜底成 code=500，绝不把 Python 堆栈暴露给前端
       （§9.2 数据安全：防止通过报错信息泄露内部结构）。
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from app.core.response import fail

# 模块级 logger，异常堆栈只写进服务端日志，不进 HTTP 响应
logger = logging.getLogger("app.exceptions")


class BusinessError(Exception):
    """
    业务异常基类。

    参数：
        code    : int  业务错误码（如 41001 图片格式不支持）
        message : str  面向用户的友好提示，会直接出现在响应体的 message 字段

    用法：
        raise BusinessError(code=41003, message="图像识别服务暂时不可用")

    设计说明：
        继承 Exception 而不是 HTTPException，是为了让业务代码与 Web 框架解耦 ——
        services/ 层不应该知道 HTTP 的存在。转换工作交给下面的全局处理器。
    """

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class AuthError(BusinessError):
    """
    认证/授权失败（对应错误码 401）。

    单独成类的原因：
        401 在语义上需要前端做「跳转登录页」的特殊处理，
        独立类型便于将来在全局处理器里做差异化处理（如附加 WWW-Authenticate 头）。
    """

    def __init__(self, message: str = "未认证或登录已过期"):
        super().__init__(code=401, message=message)


def register_exception_handlers(app: FastAPI) -> None:
    """
    把全局异常处理器注册到 FastAPI 应用上。

    参数：
        app : FastAPI  应用实例，在 main.py 里调用一次即可

    注册了三类处理器：
        1. BusinessError        —— 业务异常 → 统一响应体，HTTP 恒 200
        2. RequestValidationError —— 请求参数校验失败 → code=400，HTTP 恒 200
        3. Exception            —— 兜底 → code=500，且**只回友好文案，不回堆栈**
    """

    @app.exception_handler(BusinessError)
    async def _handle_business_error(request: Request, exc: BusinessError) -> JSONResponse:
        """
        业务异常处理器。

        注意 HTTP 状态码恒为 200 —— 见 core/response.py 顶部的约定说明。
        真正的错误码在 body.code 里。
        """
        return JSONResponse(
            status_code=200,
            content=fail(code=exc.code, message=exc.message),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """
        请求参数校验失败处理器（缺字段、类型不对等）。

        默认 FastAPI 会返回 422 并把校验细节全吐出来，
        这里统一收敛成 code=400 + 一句人话，避免暴露内部模型定义。
        """
        # 校验细节只进服务端日志，方便排查；不进响应体
        logger.warning("请求参数校验失败 %s %s：%s", request.method, request.url.path, exc.errors())
        return JSONResponse(
            status_code=200,
            content=fail(code=400, message="请求参数有误，请检查后重试"),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """
        兜底处理器：任何没被上面捕获的异常。

        关键点：
            - 完整堆栈写进服务端日志（logger.exception 会自动带 traceback）
            - 响应体里**只有**一句友好提示，绝不包含异常类型或堆栈
              （§9.2：防止通过报错信息泄露数据库结构、文件路径等内部信息）
        """
        logger.exception("未捕获异常 %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=200,
            content=fail(code=500, message="系统开小差了，请稍后重试"),
        )
