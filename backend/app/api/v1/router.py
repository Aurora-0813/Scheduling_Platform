"""模块 7 的聚合路由。

⚠️ 本文件不含 /health。健康检查由 app/main.py 统一提供（/api/v1/health）。
   此处原有一份同名路由，合并时已删除，避免「后注册者静默覆盖先注册者」。
"""
from fastapi import APIRouter

from app.api.v1.conflict import router as conflict_router
from app.api.v1.notify import router as notify_router

api_router = APIRouter()
api_router.include_router(conflict_router)   # → /conflicts/*
api_router.include_router(notify_router)     # → /notify/*

# ---- 已删除：@api_router.get("/health", response_model=ApiResponse[dict], ...) ----
#   该路由原先还 import 了 ApiResponse 与 settings（两者只被它使用），
#   删除路由后这两个 import 一并去掉，避免留下未使用的 import。
