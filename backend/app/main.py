"""
FastAPI 应用入口
====================================================================
⚠️ 临时实现，待基础支撑与集成组接管

    集成组交付正式的 app/main.py（挂载全部模块路由 + 完整中间件）后，
    请把本文件中的「模块 2 相关挂载块」合并进去，然后覆盖本文件。
    模块 2 需要的挂载内容已在下面用醒目注释标出。

启动方式：
    cd backend
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

    启动后打开 http://127.0.0.1:8000/docs 即可看到接口文档并直接调测。
"""
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import async_engine, dispose_engine
from app.core.events import bus
from app.core.exceptions import register_exception_handlers
from app.core.response import success
from app.core.scheduler import PeriodicScanner
from app.services.conflict_service import scan_and_notify_job
from app.services.notify_events import subscribe_notify_events

# ===========================================================================
# 路由注册
# ===========================================================================
# 每接入一个新模块，在这里 import 它的 router 并 include_router
from app.api.v1.image import router as image_router            # 模块 2 摄像头空间感知
from app.api.v1.voice import router as voice_router            # 模块 1 语音输入

# 模块 7：api_router 自身没有 prefix（内含 /conflicts、/notify），
# 所以挂载时必须补 /api/v1，否则会落到根路径上。
from app.api.v1.router import api_router

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    应用生命周期钩子：启动时准备资源，关闭时释放资源。

    参数：
        app : FastAPI  应用实例

    说明：
        用 lifespan 取代已废弃的 @app.on_event("startup"/"shutdown")，
        它是 FastAPI 当前推荐的写法，且 with 语句能保证清理逻辑一定被执行。
    """
    # ---- 启动阶段 ----
    # 确保上传目录存在。settings.image_upload_path 内部已做 mkdir，
    # 这里主要是为了在启动日志里留下痕迹，方便排查路径问题。
    logger.info("上传目录：%s", settings.image_upload_path)
    logger.info("视觉模型：%s", settings.VISION_MODEL_NAME or "（未配置）")
    if settings.AUTH_BYPASS:
        # 用 warning 级别，确保这条提示在日志里足够显眼
        logger.warning("⚠️ 鉴权已关闭（AUTH_BYPASS=true），仅限联调使用，部署前必须改回 false")

    # ---- 模块 7：事件订阅 + 周期扫描器 ----
    subscribe_notify_events(bus)

    scanner: PeriodicScanner | None = None
    if settings.CONFLICT_SCAN_ENABLED:
        scanner = PeriodicScanner(
            scan_and_notify_job,
            interval_seconds=settings.CONFLICT_SCAN_INTERVAL_SECONDS,
            initial_delay_seconds=settings.CONFLICT_SCAN_INITIAL_DELAY_SECONDS,
            name="conflict-scan",
        )
        scanner.start()
    else:
        logger.info("周期扫描已关闭（CONFLICT_SCAN_ENABLED=False），仅保留手动接口")
    # 挂到 app.state 上，便于运维与测试观察后台任务状态
    app.state.conflict_scanner = scanner

    try:
        yield   # ← 应用运行期间在这里挂起
    finally:
        # ---- 关闭阶段 ----
        # ⚠️ 顺序有讲究：先停扫描器（它可能正拿着连接写库），再收敛事件总线，
        #    最后释放连接池。反过来先 dispose_engine，会让仍在跑的扫描任务
        #    抛 MissingGreenlet，污染关闭日志。
        if scanner is not None:
            await scanner.stop()
        await bus.aclose()
        app.state.conflict_scanner = None
        # 显式释放数据库连接池，避免进程退出时留下未关闭的连接。
        # 用 dispose_engine() 而非 async_engine.dispose()：前者还会在同步引擎
        # 「确实被创建过」时一并释放，这与 database.py 的 PEP 562 惰性设计配套。
        await dispose_engine()
        logger.info("数据库连接池已释放，应用关闭")


app = FastAPI(
    title=settings.APP_NAME,
    description="AI 全感知·智能空间与设备综合调度平台 —— 后端服务",
    version="0.1.0-m2+m7",          # 合并后标一次版本，便于排查线上跑的是哪版
    lifespan=lifespan,
)

# ===========================================================================
# 中间件与全局处理
# ===========================================================================

# 统一异常处理（§4.3）：业务异常、参数校验失败、未捕获异常都收敛成统一响应体
register_exception_handlers(app)

# CORS（§5.4）：允许前端 localhost 及小程序域名访问
# 注意：小程序原生请求不受浏览器同源策略约束，此项主要服务于 Web 管理端开发
# 取主干版 settings.CORS_ORIGINS + allow_credentials=True；
# 模块 7 版的 allow_origins=["*"] + allow_credentials=False 更宽松，不采用
# （allow_credentials=True 与通配来源组合会被浏览器直接拒绝）。
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===========================================================================
# 静态目录：让 /uploads/xxx.jpg 可访问（模块 2 图片回放）
# ===========================================================================
# 生产环境若改为 Nginx 直接托管 uploads 目录，可删掉这一段以节省后端资源。
# 目录已在 settings.image_upload_path 中自动创建，不会因目录缺失导致启动失败。
app.mount(
    settings.IMAGE_STORAGE_BASE_URL,
    StaticFiles(directory=str(settings.image_upload_path)),
    name="uploads",
)

# ===========================================================================
# 路由挂载 —— prefix 归属是本步唯一易错点
# ===========================================================================
# 模块 2 / 模块 1 的 router 自带 prefix，注册时不要再加；
# 模块 7 的 api_router 自身无 prefix，必须补 /api/v1。
# 两边各自加对，就不会出现 /api/v1/api/v1/ 这种嵌套前缀。
app.include_router(image_router)                    # 模块 2 摄像头空间感知 → /api/v1/image/*
app.include_router(voice_router)                    # 模块 1 语音输入       → /api/v1/voice/*
app.include_router(api_router, prefix="/api/v1")    # 模块 7 冲突预警与通知 → /api/v1/conflicts/*、/api/v1/notify/*


# ===========================================================================
# 基础接口
# ===========================================================================


@app.get("/api/v1/health", tags=["系统"], summary="健康检查")
async def health_check():
    """
    健康检查接口。

    用途：
        - 确认服务是否正常启动
        - 部署后供 Nginx / 监控探活
        - 前端联调前先打一次，确认地址与端口正确

    返回：
        统一响应体，data 含服务名、环境状态、调试开关、AI 开关

    ⚠️ 全局唯一健康检查。模块 7 的 api/v1/router.py 里那份同名路由已删除，
       避免「后注册者静默覆盖先注册者」。
    """
    return success(
        data={
            "app": settings.APP_NAME,
            "env": settings.APP_ENV,
            "debug": settings.DEBUG,
            "aiEnabled": settings.AI_ENABLED,   # 模块 7 加的字段，保留
        },
        message="服务运行正常",
    )
