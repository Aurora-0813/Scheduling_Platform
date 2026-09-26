"""FastAPI 入口：统一 /api/v1 前缀、CORS、路由注册、WebSocket 挂载、建表。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import models  # noqa: F401  确保模型注册后再建表
from .api import agent, conflicts, messages, orders, resources
from .core.database import Base, async_engine
from .core.exceptions import register_exception_handlers
from .websocket import manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 建表（checkfirst=True：云数据库已存在的表不会重建，见 §6.5）
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="移动端预约与通知模块",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS（§5.4：允许前端 localhost 及小程序域名访问）
# 本模块以 X-User-Id 头鉴权、不使用 Cookie，故 allow_credentials 置 False，
# 规避「allow_origins=* 且携带凭证」的浏览器 CORS 校验冲突。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

# 统一 /api/v1/ 前缀（§5.1）
app.include_router(orders.router, prefix="/api/v1")
app.include_router(resources.router, prefix="/api/v1")
app.include_router(messages.router, prefix="/api/v1")
app.include_router(agent.router, prefix="/api/v1")
app.include_router(conflicts.router, prefix="/api/v1")


@app.websocket("/ws/notify")
async def ws_notify(websocket: WebSocket, user_id: int):
    """通知推送通道：/ws/notify?user_id=xxx（REST 之外的实时通道）。"""
    await manager.connect(user_id, websocket)
    try:
        while True:
            # 心跳/保活：客户端定时发 ping，服务端收到即确认存活
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
