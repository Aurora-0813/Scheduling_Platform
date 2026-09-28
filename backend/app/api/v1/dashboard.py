"""
模块 8 - AI 数据洞察面板 接口

- GET /api/v1/dashboard/stats   四项统计（《规范》5.3 模块 8）
- GET /api/v1/dashboard/report  AI 数据洞察报告（《规范》5.3 模块 8）

响应体统一走 app/core/response.py 的 success()（《规范》5.2 / 7.3），
响应结构由 app/schemas/dashboard.py 校验（《规范》7.3）。

说明：
    上面两行是**对外路径**（《规范》5.3 模块 8），本文件的 router 只写相对
    前缀 "/dashboard"，"/api/v1" 由 app/api/v1/__init__.py 统一挂到
    API_V1_PREFIX 下 —— 与模块 1/2 的处理一致（见各文件顶部说明）。
"""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import ApiResponse, success
from app.schemas.dashboard import (
    MAX_DAYS,
    MIN_DAYS,
    DashboardReportData,
    DashboardStatsData,
)
from app.services import dashboard_ai_service as ai_svc
from app.services import dashboard_service as svc

# 合并说明：本行原为 prefix="/api/v1/dashboard"，原因同 app/api/v1/image.py，
# 对齐项目约定后改为相对前缀 "/dashboard"。
router = APIRouter(prefix="/dashboard", tags=["dashboard"])

logger = logging.getLogger(__name__)

# TODO(鉴权): 两个接口**需要 JWT**（2026-09-28 与集成组确认，《规范》9.1「API 接口必须校验权限」）。
#   现在还没接，因为后端**尚无任何认证代码** —— 仓库里搜不到 get_current_user / oauth2 / HTTPBearer，
#   认证模块属 M2 范围（申云飞）。依赖对象不存在时无法先写 import，否则应用直接起不来。
# 就位后要动的三处（一次改完，约 10 分钟）：
#   1. 本文件：两个路由加 `_user=Depends(get_current_user)`，并 import 他给的路径
#   2. backend/tests/test_api_contract.py：新增未带 token 的 401 用例；
#      C1–C14 用 `app.dependency_overrides[get_current_user]` 覆盖掉（与现在覆盖 get_db 同一手法）
#   3. docs/api-dashboard.md：错误码表补 401（已先记在那）

# days 参数声明（默认值/范围取自 schemas，保证与契约单一定义）
_DAYS_QUERY = Query(
    default=svc.DEFAULT_DAYS,
    ge=MIN_DAYS,
    le=MAX_DAYS,
    description=f"统计窗口天数，默认 {svc.DEFAULT_DAYS}，范围 {MIN_DAYS}-{MAX_DAYS}",
)


@router.get("/stats", response_model=ApiResponse[DashboardStatsData])
async def stats(
    days: int = _DAYS_QUERY,
    db: AsyncSession = Depends(get_db),
):
    """
    场地使用率、设备闲置率、预约高峰时段、设备故障频次。

    days 已暴露到 HTTP 层：
    - 默认 7 天，范围 1–90，越界由 FastAPI 返回 422
    - 口径：场地使用率与高峰时段用 [1,2,4]（待确认/已确认/已完成），
      设备闲置率用 [1,2]（已完成视为设备已归还），详见 dashboard_service.py 顶部说明

    **本接口不抛 500**（2026-09-28 起，与 `/report` 对齐）：数据库不可达时降级为
    `code=200` + 零值四字段 + `degraded=true`，前端据此显示「数据暂时不可用」。
    依据《规范》13.1 演示应急预案 —— 演示时库一断，整个看板不该白屏。

    ⚠️ **try 必须在本层，不能下沉进 `get_all_stats`**：
    `/report` 的降级路径**依赖 `get_all_stats` 抛出**来区分两种情形 ——
    ①「压根没取到数」→ 只陈述失败事实、不给任何统计数字；
    ②「取到了数、只是 LLM 不可用」→ 用真实数字生成纯统计建议。
    若 `get_all_stats` 自己吞掉异常返回零值，`/report` 会拿着四个 0 去生成
    「场地使用率 0%」这类**看似具体、实则编造**的建议 —— 正是
    `dashboard_ai_service.generate_report` 顶部注释明确要避免的事。
    所以「降级」这个决定只能由**知道自己要什么**的调用方做：`/stats` 要零值占位，
    `/report` 要区分真假，两者策略不同，不能由被调用方一刀切。
    """
    try:
        data = await svc.get_all_stats(db, days)
    except Exception:
        # 不写 `as e`：logger.exception 自带完整堆栈，单独留个变量反而被 linter 判为未使用
        logger.exception("stats: 读取统计数据失败，降级为空结果")
        return success({**svc.empty_stats(), "degraded": True})

    return success(data)


@router.get("/report", response_model=ApiResponse[DashboardReportData])
async def report(
    days: int = _DAYS_QUERY,
    db: AsyncSession = Depends(get_db),
):
    """
    AI 数据洞察报告。

    本接口**不抛 500**：LLM 不可用、超时、JSON 解析失败、数据库不可达
    都各自降级，响应体中的 data.degraded 标识本次是否降级。
    """
    data = await ai_svc.generate_report(db, days)
    return success(data)
