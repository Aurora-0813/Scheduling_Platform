"""
JWT 身份解析

最小实现：仅负责校验并解出载荷，供 api/deps.py 组装当前用户。

注意：用户认证模块（登录、双 Token 签发与续期）由「用户认证与权限」负责人实现。
本文件存在只为让冲突预警与通知模块的接口在联调前能独立启动，
待正式认证模块落地后，把 api/deps.py 的 get_current_user 切过去并删除本文件。
"""
from __future__ import annotations

from typing import Any

import jwt

from app.core.config import settings
from app.core.response import ApiError


def decode_access_token(token: str) -> dict[str, Any]:
    """
    校验并解出 access token 载荷。

    失败一律抛 401 业务异常 —— 开发流程.md 9.1：身份只能从 JWT 解析。
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError as exc:
        raise ApiError("登录状态已失效，请重新登录", code=401) from exc
    except jwt.PyJWTError as exc:
        raise ApiError("登录凭证无效", code=401) from exc

    if not payload.get("sub"):
        raise ApiError("登录凭证缺少身份信息", code=401)
    return payload


def extract_bearer_token(authorization: str | None) -> str:
    """从 Authorization 头取出 Bearer Token"""
    if not authorization:
        raise ApiError("请先登录", code=401)

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ApiError("登录凭证格式不正确", code=401)
    return token.strip()
