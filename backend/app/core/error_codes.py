"""
统一错误码定义

分段规则
--------
| 区间      | 含义                       |
| --------- | -------------------------- |
| 200       | 成功                       |
| 400xx     | 请求参数错误               |
| 401xx     | 认证失败（未登录/凭据无效）|
| 403xx     | 授权失败（已登录但无权限） |
| 404xx     | 资源不存在                 |
| 409xx     | 冲突                       |
| 41xxx     | 感知类模块专用（模块 1/2） |
| 429xx     | 频率限制                   |
| 500xx     | 服务端内部错误             |
| 503xx     | 依赖服务不可用             |

约定
----
- 响应体中的 `code` 使用本表的分段业务码，成功恒为 200（项目文档 5.2）。
- HTTP 状态码由异常类携带（见 app/core/exceptions.py），与业务码解耦：
  例如 TOKEN_EXPIRED(40103) 与 TOKEN_INVALID(40102) 的 HTTP 状态都是 401，
  但业务码不同，前端可据此区分「需要续期」与「需要重新登录」。
"""

from __future__ import annotations


class ErrorCode:
    """业务错误码常量集合。"""

    # ==================== 成功 ====================
    SUCCESS = 200

    # ==================== 400xx 请求参数错误 ====================
    BAD_REQUEST = 40000
    PARAM_INVALID = 40001
    UPLOAD_TOO_LARGE = 40002
    UPLOAD_TYPE_INVALID = 40003
    TIME_RANGE_INVALID = 40004

    # ==================== 401xx 认证失败 ====================
    UNAUTHORIZED = 40100
    TOKEN_MISSING = 40101
    TOKEN_INVALID = 40102
    TOKEN_EXPIRED = 40103
    TOKEN_TYPE_INVALID = 40104
    TOKEN_REVOKED = 40105
    REFRESH_TOKEN_INVALID = 40106
    CREDENTIALS_INVALID = 40107
    USER_DISABLED = 40108
    ACCOUNT_LOCKED = 40109

    # ==================== 403xx 授权失败 ====================
    FORBIDDEN = 40300
    PERMISSION_DENIED = 40301
    ROLE_MISSING = 40302

    # ==================== 404xx 资源不存在 ====================
    NOT_FOUND = 40400
    USER_NOT_FOUND = 40401
    SPACE_NOT_FOUND = 40402
    DEVICE_NOT_FOUND = 40403
    ORDER_NOT_FOUND = 40404
    TICKET_NOT_FOUND = 40405
    INSPECT_NOT_FOUND = 40406
    MESSAGE_NOT_FOUND = 40407

    # ==================== 409xx 冲突 ====================
    CONFLICT = 40900
    RESOURCE_CONFLICT = 40901
    USERNAME_EXISTS = 40902
    ORDER_STATUS_CONFLICT = 40903

    # ==================== 41xxx 感知类模块专用（模块 1/2） ====================
    # 由模块 1（语音输入）与模块 2（摄像头空间感知）使用。
    # 这两段码在模块开发期由 core.exceptions.BusinessError 的兼容层引入，
    # 现正式登记到全局码表，避免「模块自己发明错误码」导致前端无表可查。
    IMAGE_TYPE_UNSUPPORTED = 41001
    IMAGE_TOO_LARGE = 41002
    AI_MODEL_UNAVAILABLE = 41003
    # 语音识别（百度 ASR）调用失败。
    # 单独分配而不复用 41002：41002 的语义是「图片过大」，前端据此提示用户
    # 压缩图片；若拿来表示「语音识别失败」，前端会给出完全错误的引导。
    # 也不复用 50303 EXTERNAL_API_UNAVAILABLE：该码面向所有外部依赖，
    # 无法区分是否为语音链路，模块 1 需要能独立识别并提示重录。
    ASR_FAILED = 41004

    # ==================== 429xx 频率限制 ====================
    TOO_MANY_REQUESTS = 42900

    # ==================== 500xx 服务端错误 ====================
    INTERNAL_ERROR = 50000
    AI_OUTPUT_INVALID = 50001

    # ==================== 503xx 依赖不可用 ====================
    SERVICE_UNAVAILABLE = 50300
    REDIS_UNAVAILABLE = 50301
    DATABASE_UNAVAILABLE = 50302
    EXTERNAL_API_UNAVAILABLE = 50303


# 错误码 → 默认提示文案。异常类未显式传 message 时取此表。
DEFAULT_MESSAGES: dict[int, str] = {
    ErrorCode.SUCCESS: "操作成功",
    ErrorCode.BAD_REQUEST: "请求参数有误",
    ErrorCode.PARAM_INVALID: "参数校验未通过",
    ErrorCode.UPLOAD_TOO_LARGE: "上传文件超过大小限制",
    ErrorCode.UPLOAD_TYPE_INVALID: "上传文件类型不支持",
    ErrorCode.TIME_RANGE_INVALID: "时间范围不合法",
    ErrorCode.UNAUTHORIZED: "未登录或登录状态已失效",
    ErrorCode.TOKEN_MISSING: "缺少认证令牌",
    ErrorCode.TOKEN_INVALID: "认证令牌无效",
    ErrorCode.TOKEN_EXPIRED: "认证令牌已过期",
    ErrorCode.TOKEN_TYPE_INVALID: "认证令牌类型不正确",
    ErrorCode.TOKEN_REVOKED: "认证令牌已失效，请重新登录",
    ErrorCode.REFRESH_TOKEN_INVALID: "刷新令牌无效或已被使用",
    ErrorCode.CREDENTIALS_INVALID: "用户名或密码错误",
    ErrorCode.USER_DISABLED: "账号已被禁用，请联系管理员",
    ErrorCode.ACCOUNT_LOCKED: "账号因异常登录被临时锁定，请稍后重试",
    ErrorCode.FORBIDDEN: "没有访问权限",
    ErrorCode.PERMISSION_DENIED: "当前角色缺少所需权限",
    ErrorCode.ROLE_MISSING: "账号未分配角色，请联系管理员",
    ErrorCode.NOT_FOUND: "请求的资源不存在",
    ErrorCode.USER_NOT_FOUND: "用户不存在",
    ErrorCode.SPACE_NOT_FOUND: "空间资源不存在",
    ErrorCode.DEVICE_NOT_FOUND: "设备资源不存在",
    ErrorCode.ORDER_NOT_FOUND: "预约订单不存在",
    ErrorCode.TICKET_NOT_FOUND: "维修工单不存在",
    ErrorCode.INSPECT_NOT_FOUND: "巡检记录不存在",
    ErrorCode.MESSAGE_NOT_FOUND: "消息不存在",
    ErrorCode.CONFLICT: "操作与当前数据状态冲突",
    ErrorCode.RESOURCE_CONFLICT: "目标时段资源已被占用",
    ErrorCode.USERNAME_EXISTS: "用户名已存在",
    ErrorCode.ORDER_STATUS_CONFLICT: "订单当前状态不允许该操作",
    ErrorCode.IMAGE_TYPE_UNSUPPORTED: "图片格式不支持，请上传 JPG / PNG / WEBP 格式的图片",
    ErrorCode.IMAGE_TOO_LARGE: "图片超过大小限制，请压缩后重试",
    ErrorCode.AI_MODEL_UNAVAILABLE: "AI 识别服务暂时不可用，请稍后重试或改用文字描述需求",
    ErrorCode.ASR_FAILED: "语音识别失败，请重新录制或改用文字输入",
    ErrorCode.TOO_MANY_REQUESTS: "操作过于频繁，请稍后重试",
    ErrorCode.INTERNAL_ERROR: "服务内部错误，请稍后重试",
    ErrorCode.AI_OUTPUT_INVALID: "AI 返回内容无法解析",
    ErrorCode.SERVICE_UNAVAILABLE: "依赖服务暂不可用，请稍后重试",
    ErrorCode.REDIS_UNAVAILABLE: "缓存服务暂不可用，请稍后重试",
    ErrorCode.DATABASE_UNAVAILABLE: "数据库暂不可用，请稍后重试",
    ErrorCode.EXTERNAL_API_UNAVAILABLE: "外部接口调用失败，请稍后重试",
}
