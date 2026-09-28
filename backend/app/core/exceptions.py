"""
业务异常体系

设计约定
--------
- 业务代码只抛 `BizError` 的子类，不直接抛 `HTTPException`。
  统一的异常处理器（app/core/response.py 注册）负责把它们转成
  统一响应体，保证「成功与失败响应结构一致」。
- 每个异常类携带 `code`（业务码，见 error_codes.py）与 `http_status`。
- `message` 面向用户，可以直接展示；内部细节只写日志，不进响应体
  （避免泄露堆栈或 SQL，项目文档 13 风险登记）。
"""

from __future__ import annotations

from typing import Any

from app.core.error_codes import DEFAULT_MESSAGES, ErrorCode


class BizError(Exception):
    """业务异常基类。"""

    code: int = ErrorCode.INTERNAL_ERROR
    http_status: int = 500

    def __init__(
        self,
        message: str | None = None,
        *,
        code: int | None = None,
        data: Any = None,
    ) -> None:
        # 显式传入的 code 优先，其次取子类声明的 code
        self.code = code if code is not None else type(self).code
        self.message = message or DEFAULT_MESSAGES.get(self.code, "服务异常")
        self.data = data
        super().__init__(self.message)


# ==================== 400xx ====================
class BadRequestError(BizError):
    code = ErrorCode.BAD_REQUEST
    http_status = 400


class ParamInvalidError(BizError):
    code = ErrorCode.PARAM_INVALID
    http_status = 400


class UploadTooLargeError(BizError):
    code = ErrorCode.UPLOAD_TOO_LARGE
    http_status = 400


class UploadTypeInvalidError(BizError):
    code = ErrorCode.UPLOAD_TYPE_INVALID
    http_status = 400


class TimeRangeInvalidError(BizError):
    code = ErrorCode.TIME_RANGE_INVALID
    http_status = 400


# ==================== 401xx ====================
class UnauthorizedError(BizError):
    code = ErrorCode.UNAUTHORIZED
    http_status = 401


class TokenMissingError(BizError):
    code = ErrorCode.TOKEN_MISSING
    http_status = 401


class TokenInvalidError(BizError):
    code = ErrorCode.TOKEN_INVALID
    http_status = 401


class TokenExpiredError(BizError):
    code = ErrorCode.TOKEN_EXPIRED
    http_status = 401


class TokenTypeInvalidError(BizError):
    code = ErrorCode.TOKEN_TYPE_INVALID
    http_status = 401


class TokenRevokedError(BizError):
    code = ErrorCode.TOKEN_REVOKED
    http_status = 401


class RefreshTokenInvalidError(BizError):
    code = ErrorCode.REFRESH_TOKEN_INVALID
    http_status = 401


class CredentialsInvalidError(BizError):
    code = ErrorCode.CREDENTIALS_INVALID
    http_status = 401


class UserDisabledError(BizError):
    code = ErrorCode.USER_DISABLED
    http_status = 401


class AccountLockedError(BizError):
    code = ErrorCode.ACCOUNT_LOCKED
    http_status = 401


# ==================== 403xx ====================
class ForbiddenError(BizError):
    code = ErrorCode.FORBIDDEN
    http_status = 403


class PermissionDeniedError(BizError):
    code = ErrorCode.PERMISSION_DENIED
    http_status = 403


class RoleMissingError(BizError):
    code = ErrorCode.ROLE_MISSING
    http_status = 403


# ==================== 404xx ====================
class NotFoundError(BizError):
    code = ErrorCode.NOT_FOUND
    http_status = 404


class UserNotFoundError(BizError):
    code = ErrorCode.USER_NOT_FOUND
    http_status = 404


class SpaceNotFoundError(BizError):
    code = ErrorCode.SPACE_NOT_FOUND
    http_status = 404


class DeviceNotFoundError(BizError):
    code = ErrorCode.DEVICE_NOT_FOUND
    http_status = 404


class OrderNotFoundError(BizError):
    code = ErrorCode.ORDER_NOT_FOUND
    http_status = 404


class TicketNotFoundError(BizError):
    code = ErrorCode.TICKET_NOT_FOUND
    http_status = 404


class InspectNotFoundError(BizError):
    code = ErrorCode.INSPECT_NOT_FOUND
    http_status = 404


class MessageNotFoundError(BizError):
    code = ErrorCode.MESSAGE_NOT_FOUND
    http_status = 404


# ==================== 409xx ====================
class ConflictError(BizError):
    code = ErrorCode.CONFLICT
    http_status = 409


class ResourceConflictError(BizError):
    code = ErrorCode.RESOURCE_CONFLICT
    http_status = 409


class UsernameExistsError(BizError):
    code = ErrorCode.USERNAME_EXISTS
    http_status = 409


class OrderStatusConflictError(BizError):
    code = ErrorCode.ORDER_STATUS_CONFLICT
    http_status = 409


# ==================== 429xx ====================
class TooManyRequestsError(BizError):
    code = ErrorCode.TOO_MANY_REQUESTS
    http_status = 429


# ==================== 500xx ====================
class InternalError(BizError):
    code = ErrorCode.INTERNAL_ERROR
    http_status = 500


class AiOutputInvalidError(BizError):
    """
    AI 返回内容无法解析。

    对应项目文档 10.2 要求覆盖的降级用例一：
    大模型返回非 JSON 时降级为自然语言提示。
    """

    code = ErrorCode.AI_OUTPUT_INVALID
    http_status = 502


# ==================== 503xx ====================
class ServiceUnavailableError(BizError):
    code = ErrorCode.SERVICE_UNAVAILABLE
    http_status = 503


class RedisUnavailableError(BizError):
    """
    Redis 不可用。

    项目文档 13 要求外部依赖失败时友好降级。认证链路的取舍见
    docs/开发流程说明文档.md「Redis 不可用时的降级策略」：
    登录仍可成功（仅记 warning），但刷新与登出必须失败。
    """

    code = ErrorCode.REDIS_UNAVAILABLE
    http_status = 503


class DatabaseUnavailableError(BizError):
    code = ErrorCode.DATABASE_UNAVAILABLE
    http_status = 503


class ExternalApiUnavailableError(BizError):
    """
    外部 API 调用失败。

    对应项目文档 10.2 要求覆盖的降级用例二：
    外部 API 超时或失败时降级为友好提示。
    """

    code = ErrorCode.EXTERNAL_API_UNAVAILABLE
    http_status = 503


# ===========================================================================
# 模块 1 / 模块 2 兼容层：BusinessError
# ===========================================================================
# 背景
# ----
# 模块 1（语音输入）与模块 2（摄像头空间感知）在基础支撑交付前，曾各自
# 自建过一版临时的 app/core/exceptions.py，其中定义了：
#
#     class BusinessError(Exception):
#         def __init__(self, code: int, message: str): ...
#
# 并在交付说明中写明「唯一要求：保留 BusinessError 类名与 (code, message)
# 构造签名」。本文件是基础支撑的正式实现，基类名为 BizError，因此这里补一个
# 兼容类，让两个模块的既有代码**无需任何改动**即可接入统一异常体系。
#
# 已确认的行为差异
# ----------------
# 临时实现把业务异常的 HTTP 状态码固定为 200，业务码只放在 body.code。
# 正式实现按 HTTP 语义返回真实状态码（见 error_codes.py 顶部约定）。
# 此项由集成侧拍板采用后者，故本兼容类的 http_status 按下方映射表取值。
# 模块代码本身不承担责任 —— 它们只负责抛异常，状态码由全局处理器决定。

# 错误码 → HTTP 状态码。未登记的码一律按 400（客户端错误）处理。
#
# 这张表是给**没有对应 BizError 子类**的码用的（模块 1/2 的 41xxx 段就是这样），
# 主流写法应该是直接抛子类。两条路径给出的状态码必须一致 —— 一旦不一致，
# 同一个错误会因为调用方写法不同而返回不同状态码，前端无法统一处理。
# 这种不一致由 tests/api/test_response_envelope.py 的对账用例拦下。
_BUSINESS_ERROR_HTTP_STATUS: dict[int, int] = {
    # ---- 41xxx：模块 1/2 的临时码段 ----
    # 这一段是 5 位码里唯一不满足「HTTP = code // 100」的：41001 // 100 = 410，
    # 而 410 是 Gone，语义完全不对；41003 // 100 = 410 同理。所以这一段必须
    # 显式登记，不能靠默认的除法规则。
    ErrorCode.IMAGE_TYPE_UNSUPPORTED: 400,
    ErrorCode.IMAGE_TOO_LARGE: 400,
    ErrorCode.AI_MODEL_UNAVAILABLE: 503,
    # ASR 失败是下游依赖（百度语音）不可用，不是调用方的请求有问题，
    # 因此映射到 503 而非 400 —— 前端据此可提示「稍后重试」而不是「改参数」。
    ErrorCode.ASR_FAILED: 503,
    # ---- 40901：有子类（ResourceConflictError，HTTP 409），本无需登记 ----
    # 登记它是因为「冲突」有两条抛法，而此前只有一条给出正确的状态码：
    #     raise ResourceConflictError(...)            → HTTP 409（按类）
    #     raise BusinessError(40901, ...)             → 落默认值，HTTP 400
    # 同一个「目标时段资源已被占用」，前端拿到的状态码取决于调用方怎么写，
    # 这属于两条路径不一致，必须对齐。40901 // 100 = 409，与子类一致。
    ErrorCode.RESOURCE_CONFLICT: 409,
}


class BusinessError(BizError):
    """
    模块 1 / 模块 2 使用的业务异常基类（兼容层）。

    参数：
        code    : 业务错误码。位置参数与关键字参数两种写法都支持，
                  以兼容模块既有的 `BusinessError(code=..., message=...)`
                  与 `BusinessError(41003, "...")` 两种调用方式。
        message : 面向用户的友好提示。省略时取码表中的默认文案。
        data    : 失败时可选携带的数据（如候选列表）。

    用法：
        raise BusinessError(code=41003, message="图像识别服务暂时不可用")

    子类化：
        模块内可继续派生语义化子类，无需重写 __init__：
            class ImageValidationError(BusinessError): ...
            raise ImageValidationError(code=41001, message="图片格式不支持")
    """

    def __init__(
        self,
        code: int = ErrorCode.INTERNAL_ERROR,
        message: str | None = None,
        data: Any = None,
    ) -> None:
        super().__init__(message, code=code, data=data)
        self.http_status = _BUSINESS_ERROR_HTTP_STATUS.get(code, 400)
