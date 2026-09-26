"""当前用户解析（认证由队友「用户认证与权限」模块负责，此处提供演示 mock）。

真实接入后：解析 `Authorization: Bearer <jwt>`（§5.1），校验后返回 user_id。
演示阶段：优先读 X-User-Id，其次 Bearer 任意 token，兜底 mock 用户 id=1。
身份一律从 JWT 解析，禁止从请求体/FormData 传入（§5.1 / §9.1）。
"""
from fastapi import Header

MOCK_USER_ID = 1


async def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_user_id: int | None = Header(default=None, alias="X-User-Id"),
) -> int:
    if x_user_id is not None:
        return x_user_id
    # 真实 JWT 校验接入点：authorization 形如 "Bearer <token>"
    return MOCK_USER_ID
