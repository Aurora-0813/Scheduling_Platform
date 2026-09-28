"""
健康检查与就绪探针（模块 10）

两个接口的**语义必须区分清楚**，这是它们各自唯一的用途：

| 接口              | 语义                        | 依赖检查 | HTTP 状态         |
| ----------------- | --------------------------- | -------- | ----------------- |
| `GET /health`     | 进程还活着吗（liveness）     | **不做** | 恒 200            |
| `GET /ready`      | 依赖都通吗（readiness）      | DB、Redis| 恒 200，看 status |

为什么 `/ready` 恒返回 200 而不是「依赖挂了就 503」
---------------------------------------------------
它是给人看的**诊断接口**，M1 验收（文档 2.1「库能连上」）就靠它。
若依赖挂掉就返回 503，前端与浏览器只会看到一个错误页，看不到
「到底哪一项不通、是 ok 还是 degraded」，排查时必须去看服务器日志。
把结论放进响应体的 `status` 字段里，信息量更大。

真正的编排层探针（K8s readinessProbe / Nginx upstream 健康检查）需要的是
「非 200 即摘除」，那类场景请**另建**一个只返回状态码的路径 ——
不要为了迎合探针而牺牲这个接口的诊断能力。本项目当前不部署 K8s。

`/ready` 的响应体里绝不出现连接串与密码（文档 9.4），
失败原因只写进服务端日志。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.core.redis import check_health as redis_check_health
from app.core.response import ApiResponse, ok
from app.schemas.monitor import ReadyStatus

__all__ = ["router"]

logger = get_logger(__name__)

router = APIRouter(tags=["健康检查（模块 10）"])


async def _check_database(db: AsyncSession) -> str:
    """
    探活数据库：跑一条最轻的 `SELECT 1`。

    返回 `"ok"` / `"error"`。失败时**不把异常内容放进响应**，
    只写日志（异常里常带主机名、用户名甚至连接串片段）。
    """
    try:
        await db.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # noqa: BLE001 - 探针要吞掉一切，避免 500
        logger.warning("就绪探针：数据库不可用 %s: %s", type(exc).__name__, exc)
        try:
            # 连接失败会让会话停在未完成的事务里，回滚以便连接池能正常回收。
            # 这一步本身也可能失败（连接已断），失败无所谓，因此再包一层。
            await db.rollback()
        except Exception:  # noqa: BLE001 - 尽力而为：这里再失败已无补救动作
            pass
        return "error"


@router.get(
    "/health",
    response_model=ApiResponse[dict],
    summary="存活探针",
    description=(
        "进程是否存活。**不检查任何外部依赖**，因此不会因为数据库或 Redis "
        "不可用而失败。恒返回 HTTP 200。"
    ),
)
async def health() -> ApiResponse[dict]:
    """
    存活探针。

    刻意不检查依赖：一旦它开始检查 DB，「数据库慢」就会被误判为「进程已死」
    并触发重启，反而把可恢复的故障放大成全量不可用。
    """
    return ok(
        {
            "status": "ok",
            "service": settings.APP_NAME,
            "env": settings.APP_ENV,
        }
    )


@router.get(
    "/ready",
    response_model=ApiResponse[ReadyStatus],
    summary="就绪探针 / 依赖诊断",
    description=(
        "检查数据库与 Redis 是否可用，恒返回 HTTP 200。\n\n"
        "`db` 取值 `ok` / `error`；`redis` 取值 `ok` / `degraded` / `disabled`"
        "（`disabled` 表示 `REDIS_ENABLED=false`，属于**正常**配置，"
        "此时 refreshToken 走进程内存储）。\n\n"
        "整体 `status`：数据库正常且 Redis 为 `ok` 或 `disabled` 时为 `ok`，"
        "否则为 `degraded`。"
    ),
)
async def ready(db: AsyncSession = Depends(get_db)) -> ApiResponse[ReadyStatus]:
    """
    就绪探针。M1 验收工具：`db` 与 `redis` 都非 error 才说明环境搭好了。
    """
    db_status = await _check_database(db)
    redis_status = await redis_check_health()

    # Redis 为 disabled 不算降级：那是「按配置不使用 Redis」，
    # 刷新令牌走内存实现，功能完整（只是重启后需重新登录）。
    healthy = db_status == "ok" and redis_status in ("ok", "disabled")

    return ok(
        ReadyStatus(
            status="ok" if healthy else "degraded",
            db=db_status,
            redis=redis_status,
            app_env=settings.APP_ENV,
        )
    )
