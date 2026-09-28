"""
v1 聚合路由

各业务模块把自己的路由挂到这里，最终统一以 /api/v1 前缀暴露。
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.conflict import router as conflict_router
from app.api.v1.notify import router as notify_router
from app.core.config import settings
from app.core.response import ApiResponse, ok

api_router = APIRouter()
api_router.include_router(conflict_router)
api_router.include_router(notify_router)


@api_router.get(
    "/health",
    response_model=ApiResponse[dict],
    summary="健康检查",
    tags=["系统"],
)
async def health() -> ApiResponse[dict]:
    """供部署自检与前端联通性检查使用"""
    return ok(
        {
            "status": "ok",
            "app": settings.APP_NAME,
            "env": settings.APP_ENV,
            "aiEnabled": settings.AI_ENABLED,
        }
    )
