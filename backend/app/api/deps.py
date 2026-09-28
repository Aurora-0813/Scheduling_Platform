"""
FastAPI 依赖注入模块
====================================================================
⚠️ 临时实现，待基础支撑与集成组接管

    集成组交付正式的 api/deps.py（含完整的 RBAC 权限校验）后，覆盖本文件即可。
    唯一要求：保留 get_current_user 的依赖签名，模块 2 的路由直接 `Depends(get_current_user)`。

规范依据：
    开发流程.md §5.1：身份来源 —— userId 等身份标识一律从 JWT 解析，
                      禁止从请求体或 FormData 传入，防止身份伪造
    开发流程.md §9.1：JWT 双 Token 机制、RBAC 权限模型

本文件当前提供的能力：
    get_current_user() —— 从 Authorization: Bearer {token} 解析出当前用户
    get_llm()          —— 文本 LLM（通知 / 抽取链）；视觉 LLM 见 app/core/llm.py
    注意：这里**只做 Token 解析**，不做「查库确认用户状态」「角色权限校验」，
         那些属于集成组的完整实现（模块 9）。
"""
from dataclasses import dataclass

import jwt
from fastapi import Header
from langchain_core.language_models import BaseChatModel

from app.agent.chains.llm import build_llm
from app.core.config import settings
from app.core.exceptions import AuthError


@dataclass
class CurrentUser:
    """
    当前登录用户的轻量视图。

    刻意不直接用 ORM 的 SysUser 对象：
        1. 避免每个请求都多查一次数据库（JWT 里已经带了身份信息）
        2. 避免 services/ 层拿到 ORM 对象后绕过业务校验直接改字段
        3. 让本模块的单元测试可以轻易伪造一个 CurrentUser，不必连库
    """
    user_id: int | None = None      # 用户 ID，可能为 None（开发放行模式）
    username: str | None = None     # 登录名
    role: str | None = None         # 角色标识：user / admin / super_admin


async def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    """
    FastAPI 依赖：解析 JWT，返回当前用户。

    参数：
        authorization : str | None
            请求头 Authorization 的值，形如 "Bearer eyJhbGciOi...".
            FastAPI 会按参数名自动从请求头取值（下划线转连字符）。

    返回：
        CurrentUser

    抛出：
        AuthError(401) —— 请求头缺失、格式不对、Token 过期或签名无效

    用法（路由里）：
        @router.post("/analyze")
        async def analyze(current_user: CurrentUser = Depends(get_current_user)):
            ...

    关于 AUTH_BYPASS：
        .env 里 AUTH_BYPASS=true 时直接放行，返回一个假的开发者身份。
        这是为了让本模块在集成组的登录接口就绪前能先跑通自测
        （scripts/seed.py 的 test 命令就依赖它）。
        **演示与部署前必须把 AUTH_BYPASS 改成 false。**
    """
    # ---- 开发放行模式（仅限联调阶段）----
    if settings.AUTH_BYPASS:
        return CurrentUser(user_id=1, username="dev_bypass", role="admin")

    # ---- 1. 校验请求头格式 ----
    if not authorization:
        raise AuthError("缺少认证信息，请先登录")

    parts = authorization.split()
    # 必须恰好是两段，且第一段是 Bearer（大小写不敏感）
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthError("认证信息格式不正确，应为 'Bearer {token}'")

    token = parts[1]

    # ---- 2. 解码并验签 ----
    # jwt.decode 会自动校验签名与 exp 过期时间
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,                      # 与签发端必须一致，从 .env 读
            algorithms=[settings.JWT_ALGORITHM],          # 显式指定算法，防止算法混淆攻击
        )
    except jwt.ExpiredSignatureError:
        raise AuthError("登录已过期，请重新登录")
    except jwt.PyJWTError:
        # 签名不对、格式损坏、算法不匹配等，统一归为凭证无效。
        # 刻意不区分具体原因，避免给攻击者提供探测信息。
        raise AuthError("身份凭证无效，请重新登录")

    # ---- 3. 从 payload 提取身份 ----
    # 兼容两种常见写法：sub（JWT 标准）与 userId（业务直白命名）
    raw_user_id = payload.get("userId", payload.get("sub"))
    try:
        user_id = int(raw_user_id) if raw_user_id is not None else None
    except (TypeError, ValueError):
        user_id = None

    # ⚠️ 这一句是主干明确的拒绝分支，绝不能省：省掉它等于放行
    #    「签名合法但没有用户标识」的凭证 —— 比「无 token 放行」更隐蔽。
    if user_id is None:
        raise AuthError("身份凭证缺少用户标识，请重新登录")

    # ---- 4. 角色字段：入站兼容 role / roleName / role_name，出站统一为 role ----
    #    兼容不是保险而是硬需求：tests/api/conftest.py:31 签发的就是 "roleName"，
    #    若只读 payload.get("role") 会得到 None，tests/api/test_notify_api.py
    #    的 role_key 断言（ROLE_OWNER / ROLE_RESOURCE_ADMIN）会失败。
    role = payload.get("role") or payload.get("roleName") or payload.get("role_name")

    return CurrentUser(
        user_id=user_id,
        username=payload.get("username"),      # 主干原文；刻意不加 `or ""`，那是行为变化
        role=str(role) if role else None,
    )


async def get_llm() -> BaseChatModel:
    """模块 7 注入用：文本 LLM（通知 / 抽取链）。视觉 LLM 见 app/core/llm.py。"""
    return build_llm()


# ⚠️ feat 的 __all__ 里有 "get_db"，但实测全仓【0 处】从本模块 import get_db，
#    且主干版 deps.py 既不 import 也不定义 get_db —— 故此处不带 get_db，
#    避免引入一个无人使用的 re-export（模块 docstring 亦只列两个能力）。
__all__ = ["CurrentUser", "get_current_user", "get_llm"]
