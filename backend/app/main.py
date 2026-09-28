"""
FastAPI 应用入口（模块 10：系统集成与联调）

启动方式
--------
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

或直接用 `bash scripts/dev.sh`（内含上述命令与常用参数）。

本文件是**全组唯一的集成点**
---------------------------
模块 1~8 的接口不需要改本文件：每个人把自己的 router 加进
`app/api/v1/__init__.py` 的 `api_router` 即可，本文件只 include 那一个汇总 router。
这样能避免 5 个人反复改同一个 main.py 造成冲突。

中间件的顺序（**顺序即语义，改之前务必读完这段**）
--------------------------------------------------
Starlette 的 `add_middleware` 是**前插**：最后添加的在栈的最外层，
请求先经过它。本项目的顺序（自外向内）：

    CORS  →  RequestContext  →  AgentMetrics  →  ExceptionMiddleware  →  路由

- **CORS 在最外层**：否则 4xx 响应（由内层的 ExceptionMiddleware 生成）
  不会经过 CORS 中间件、响应里就没有 `Access-Control-Allow-Origin`，
  浏览器把「401 未登录」报成「跨域错误」，前端排查会被完全带偏。
- **RequestContext 在 Metrics 外层**：埋点写 Redis 失败时的告警日志
  也要带上 requestId；反过来的话那条日志就没有 ID 可关联。
- 两者都在 ExceptionMiddleware 外层：这样 `BizError` 转换出的响应
  同样会经过它们，被记进访问日志、拿到 `X-Request-Id` 头。

已知边界：**未处理异常（500）的响应没有 CORS 头，也没有 X-Request-Id 头**。
`app/core/response.py` 注册的 `Exception` 处理器是交给 Starlette 的
`ServerErrorMiddleware` 调用的，而它位于全部业务中间件**之外**：它生成的
响应不会再回穿 CORS 与 RequestContext —— 这是框架结构决定的，不是本项目的
配置疏漏，已由 `tests/api/test_cors.py` 固化为断言。

覆盖范围要说清楚：**凡是走到 `exception_handler` 之外的未预料异常**（即
`BizError`、`RequestValidationError` 与显式抛出的 `HTTPException` 之外的一切），
响应都会缺这两个头；`/api/v1/_probe/cors-boom` 那条用例实测的就是这条路径。
影响可接受：此时响应体仍是规范的信封（500/50000），堆栈在日志里，
而「缺一个 CORS 头」是次要问题。要消掉它只能在自己的中间件里再造一份
500 响应体，那会让「统一响应体」出现两个来源 —— 代价更大。
排查此类故障时，按 `method + path` 关联本中间件那条 **ERROR 级访问日志**
（它带 requestId）与紧跟其后的堆栈日志即可。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.status import WS_1008_POLICY_VIOLATION

from app import models  # noqa: F401  确保模型注册后再建表（_ensure_schema 用）
from app.api.deps import reset_token_store
from app.api.v1 import API_V1_PREFIX, api_router
from app.core.config import MIN_JWT_SECRET_LENGTH, settings
from app.core.database import Base, async_engine
from app.core.events import bus
from app.core.exceptions import BizError
from app.core.logging import get_logger, setup_logging
from app.core.metrics import reset_metric_store
from app.core.redis import check_health as redis_check_health
from app.core.response import register_exception_handlers
from app.core.scheduler import PeriodicScanner
from app.core.security import TokenType, decode_token
from app.middlewares import AgentMetricsMiddleware, RequestContextMiddleware
from app.services.conflict_service import scan_and_notify_job
from app.services.notify_events import subscribe_notify_events
from app.websocket import manager

__all__ = ["app", "create_app", "lifespan"]

logger = get_logger(__name__)

# CORS 预检结果缓存时长（秒）。前端一个页面会连发多个不同方法/头的请求，
# 不缓存的话每个都会先发一次 OPTIONS，白白多一倍请求量。
_CORS_MAX_AGE = 600


# ==========================================================================
# lifespan：启动与关闭
# ==========================================================================
async def _probe_database() -> str:
    """
    启动期数据库探活。返回 `"ok"` / `"error"`。

    **失败不阻止启动**，只打日志。理由：库连不上时更需要进程活着 ——
    否则 `/api/v1/ready` 也打不开，就只能去翻服务器日志才能知道是库的问题。
    而且 uvicorn 的 `--reload` 会在库还没起好时反复重启进程，硬失败会导致
    开发期陷入启动/退出循环。真正的「依赖不可用」判定交给 `/ready` 接口。
    """
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # noqa: BLE001 - 启动探活不能抛
        # 只打异常类型与消息，不打堆栈：连接失败的栈有 40 行且每次启动都一样，
        # 真正有用的信息是「哪个地址连不上」，而它已经在 masked_database_url 里。
        logger.warning(
            "启动探活：数据库不可用（服务仍会启动，详见 GET /api/v1/ready） target=%s %s: %s",
            settings.masked_database_url,
            type(exc).__name__,
            exc,
        )
        return "error"


def _warn_about_security_settings() -> None:
    """
    启动时把安全配置的问题再喊一遍。

    `app/core/config.py` 的 `model_validator` 在 **import 时**就检查过一次，
    但那时 `setup_logging()` 还没执行，告警可能落在默认的 handler 上（格式不同、
    可能被忽略）。这里在日志系统就绪后再打一次，保证它一定以 JSON 日志出现
    在启动输出里 —— 一个 6 字符的 JWT 密钥不该静悄悄地跑起来。
    """
    if len(settings.JWT_SECRET_KEY or "") < MIN_JWT_SECRET_LENGTH:
        logger.warning(
            "安全告警：JWT_SECRET_KEY 强度不足（当前 %s 字符，要求至少 %s）。"
            "该密钥可被暴力破解，进而伪造任意用户的登录令牌。"
            '生成新密钥：python -c "import secrets; print(secrets.token_urlsafe(48))"',
            len(settings.JWT_SECRET_KEY or ""),
            MIN_JWT_SECRET_LENGTH,
        )
    if not settings.is_dev:
        logger.info("当前环境为 %s（非 dev），已启用密钥强度硬校验", settings.APP_ENV)


async def _ensure_schema() -> None:
    """确保 ORM 声明的表都存在（`checkfirst=True`：已存在的不动）。

    为什么启动时要建表，而不是全交给 Alembic
    ----------------------------------------
    1. **`§13.1` 的演示应急预案**：「云数据库断连 -> 切换本地 SQLite 镜像库」。
       镜像库是演示现场临时建的空库，没有跑过任何迁移 —— 不建表就只能演示一个
       「每个接口都 500」的系统，应急预案等于没有。
    2. **`§6.5` 的云库路径不受影响**：云库上的表由基础支撑与集成组统一建立，
       `checkfirst=True` 使这一步在云库上退化为一次 `has_table` 查询，
       不会改任何既有表结构。**它不能替代迁移**：新增/变更列仍须走
       `alembic/versions/`，由集成组统一执行（`§6.5`）。

    失败只告警不阻止启动，与 `_probe_database` 同一取舍：库不可用时更需要
    进程活着，好让 `/api/v1/ready` 能回答「到底哪一环不通」。
    """
    try:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001 - 启动期不能因建表失败而崩
        logger.warning(
            "启动建表失败（服务仍会启动，业务接口可能因缺表报错） target=%s %s: %s",
            settings.masked_database_url,
            type(exc).__name__,
            exc,
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期：日志 → 配置自检 → 依赖探活 →（yield）→ 资源释放。"""
    setup_logging(logging.DEBUG if settings.DEBUG else logging.INFO)

    logger.info(
        "应用启动 name=%s env=%s debug=%s db=%s redis=%s",
        settings.APP_NAME,
        settings.APP_ENV,
        settings.DEBUG,
        settings.masked_database_url,
        f"{settings.REDIS_HOST}:{settings.REDIS_PORT}" if settings.REDIS_ENABLED else "disabled",
        extra={
            "extra_fields": {
                "app": settings.APP_NAME,
                "env": settings.APP_ENV,
                "database": settings.masked_database_url,
                "redisEnabled": settings.REDIS_ENABLED,
            }
        },
    )

    _warn_about_security_settings()

    # 丢弃可能已存在的单例，确保它们按**当前**配置重建。
    # 测试里会改配置再建 app，不重置就会继续用上一个 app 的实例。
    reset_token_store()
    reset_metric_store()

    db_status = await _probe_database()
    redis_status = await redis_check_health()
    logger.info(
        "启动探活完成 db=%s redis=%s（redis=disabled 表示 REDIS_ENABLED=false，属正常）",
        db_status,
        redis_status,
    )

    await _ensure_schema()

    # ---- 模块 7：事件订阅 + 周期冲突扫描 ----
    # 订阅是幂等的；扫描器可按 CONFLICT_SCAN_ENABLED 关闭（演示/测试期常见）。
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
        yield
    finally:
        # 关闭阶段**不能抛异常**：抛了会让 uvicorn 打印一堆与真实问题无关的
        # 关闭错误，掩盖真正的退出原因。每个资源各自兜住自己的异常。
        # ⚠️ 顺序有讲究：先停扫描器（它可能正拿着连接写库），再收敛事件总线，
        #    最后才释放连接池（在 _shutdown 里）。反过来会让仍在跑的扫描任务
        #    抛 MissingGreenlet，污染关闭日志。
        if scanner is not None:
            try:
                await scanner.stop()
            except Exception as exc:  # noqa: BLE001 - 关闭路径不能抛
                logger.warning("停止周期扫描器出错: %s: %s", type(exc).__name__, exc)
        app.state.conflict_scanner = None
        try:
            await bus.aclose()
        except Exception as exc:  # noqa: BLE001 - 关闭路径不能抛
            logger.warning("关闭事件总线出错: %s: %s", type(exc).__name__, exc)
        await _shutdown()


async def _shutdown() -> None:
    """释放数据库连接池与 Redis 连接。"""
    try:
        await async_engine.dispose()
    except Exception as exc:  # noqa: BLE001 - 关闭路径不能抛
        logger.warning("关闭数据库连接池出错: %s: %s", type(exc).__name__, exc)

    try:
        from app.core.redis import close as close_redis

        await close_redis()
    except Exception as exc:  # noqa: BLE001 - 关闭路径不能抛
        logger.warning("关闭 Redis 连接出错: %s: %s", type(exc).__name__, exc)

    reset_token_store()
    reset_metric_store()
    logger.info("应用已关闭")


# ==========================================================================
# 中间件
# ==========================================================================
def _register_middlewares(app: FastAPI) -> None:
    """
    注册中间件。**顺序即语义**，添加顺序与执行顺序相反（详见模块 docstring）。

    先内后外地添加：AgentMetrics（最内）→ RequestContext → CORS（最外）。
    """
    app.add_middleware(AgentMetricsMiddleware)
    app.add_middleware(RequestContextMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        # 本项目鉴权走 `Authorization: Bearer` 头，**不使用 Cookie**，
        # 因此不需要凭据模式。若将来改用 Cookie 会话，必须把这里改成 True，
        # 否则浏览器不会携带 Cookie，症状是「登录成功但下一个接口 401」。
        # 当前允许来源是显式白名单（非 "*"），届时可直接开启。
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        # "*" 表示预检时原样回显浏览器请求的头（Starlette 的行为）。
        # 来源本身已受白名单限制，因此这里不必逐一列举 Authorization / Content-Type。
        allow_headers=["*"],
        # 暴露给前端 JS 的响应头。默认只有少数几个「安全头」可读，
        # 不显式暴露的话前端拿不到 X-Request-Id，报错时就没法把它贴给后端。
        expose_headers=["X-Request-Id"],
        max_age=_CORS_MAX_AGE,
    )


# ==========================================================================
# 应用工厂
# ==========================================================================
def create_app() -> FastAPI:
    """
    构造应用。

    做成工厂函数而不是模块级的一堆语句，是为了测试能反复调用得到**干净**的
    实例（不同的配置、不同的依赖覆盖），而不用去动模块级全局状态。
    """
    app = FastAPI(
        title=f"{settings.APP_NAME} 后端接口",
        version="1.0.0",
        description=(
            "AI 全感知·智能空间与设备综合调度平台 —— 后端接口文档。\n\n"
            "**统一响应体**：所有接口（含错误）都是 "
            "`{code, message, data}` 结构，`code` 为 5 位业务码，"
            "成功恒为 `200`，与 HTTP 状态码解耦。\n\n"
            "**字段命名**：请求与响应字段一律 camelCase。\n\n"
            "**时间格式**：一律 `YYYY-MM-DD HH:mm:ss`（本地时间，无时区后缀）。\n\n"
            "**鉴权**：登录接口返回 `accessToken`，后续请求带 "
            "`Authorization: Bearer <accessToken>`；"
            "`accessToken` 有效期 30 分钟，用 `POST /api/v1/auth/refresh` 续期。"
        ),
        lifespan=lifespan,
        # 接口文档始终开放。本项目是内网部署的课设系统，接口文档对前端/小程序
        # 联调是刚需；若将来对外发布，请按 docs/deploy.md 的说明在非 dev 环境关闭。
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # 异常处理器要在中间件之前注册：ServerErrorMiddleware 在构造中间件栈时
    # 读取 app.exception_handlers，晚注册会拿不到兜底的 Exception 处理器。
    register_exception_handlers(app)
    _register_middlewares(app)

    app.include_router(api_router, prefix=API_V1_PREFIX)

    # ------------------------------------------------------------------
    # 静态目录：让 /uploads/xxx.jpg 可访问（模块 2 图片回放）
    # ------------------------------------------------------------------
    # 目录由 settings.image_upload_path 自动创建，不会因目录缺失导致启动失败。
    # 生产环境若改为 Nginx 直接托管 uploads 目录，可删掉这一段以节省后端资源。
    # 注意：mount 的路径不能与 API 路由前缀重叠，"/uploads" 与 "/api/v1" 互不干扰。
    app.mount(
        settings.IMAGE_STORAGE_BASE_URL,
        StaticFiles(directory=str(settings.image_upload_path)),
        name="uploads",
    )

    # ------------------------------------------------------------------
    # 模块 3：WebSocket 通知通道
    # ------------------------------------------------------------------
    # 预约确认 / 取消后由 services/message_service.py 经 ConnectionManager 推送。
    # 路径刻意**不带** `/api/v1` 前缀：它是 REST 之外的实时通道，与 REST 树分开，
    # 前端连 `ws://<host>/ws/notify?token=<accessToken>`。
    #
    # 为什么令牌在查询串而不是 `Authorization` 头
    # ------------------------------------------
    # 浏览器的 `WebSocket` 构造函数**不允许**自定义请求头，实时通道只能把凭据
    # 放进 URL。这里早先传的是 `?user_id=`，等于把「我是谁」交给客户端自报：
    # 连上 `/ws/notify?user_id=2` 就能实时收到别人预约的确认/取消通知。
    # 现在传的是**令牌**，服务端自己解出 user_id（§5.1 / docs/api.md §1.6：
    # 身份一律从令牌解析，禁止从 Query 传入身份本身）。
    #
    # 已知残留（与本轮 REST 侧改造同一性质，记号待办）
    # ----------------------------------------------
    # 这里只校验令牌签名与类型，**不查库**确认用户仍存在 / 未被禁用 ——
    # 那段逻辑在 `app.api.deps.get_current_user` 里，是为 `Depends` 写的，
    # 无法直接复用。影响有限：被删用户的令牌最多再活一个有效期（30 分钟），
    # 且 `send_to_user` 只会推库中为它生成的通知，删号后不会再生成。
    @app.websocket("/ws/notify")
    async def ws_notify(websocket: WebSocket, token: str) -> None:
        """通知推送通道：`/ws/notify?token=<accessToken>`（模块 3）。"""
        try:
            payload = decode_token(token, expected_type=TokenType.ACCESS)
        except BizError:
            # 握手阶段就拒绝：不 accept，直接按「策略违规」关闭。
            # 不区分过期/签名错/类型错 —— 与 REST 侧同样不透原因（§9.2）。
            await websocket.close(code=WS_1008_POLICY_VIOLATION)
            return

        await manager.connect(payload.user_id, websocket)
        try:
            while True:
                # 心跳/保活：客户端定时发文本，服务端收到即确认存活。
                # 收不到就靠 WebSocketDisconnect 退出 —— 这条循环没有业务含义，
                # 只是维持连接不被中间层按空闲回收。
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(payload.user_id, websocket)

    if settings.DEBUG:
        # 延迟导入：Mock 路由只在开发环境存在，生产环境连模块都不加载。
        # 放在函数内部而非模块顶部，是为了让 `create_app()` 能在没有 mock 模块
        # 的情况下也构造成功（模块 10 之外的成员不需要它的实现细节）。
        from app.api.v1 import mock

        app.include_router(mock.router, prefix=API_V1_PREFIX)
        logger.info("已注册 Mock 路由（DEBUG=true）: %s/mock/*", API_V1_PREFIX)

    return app


app = create_app()
