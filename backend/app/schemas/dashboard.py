"""
模块 8 - AI 数据洞察面板 请求 / 响应模型

对应文档：
- 《规范》5.3 模块 8（接口契约）
- 《规范》7.3「必须使用 Pydantic 做请求/响应校验」
- 《规范》6.2 字段命名：库表 snake_case，**API 传输 camelCase**

命名策略：Python 侧保持 snake_case（PEP8），通过 alias_generator 自动生成
camelCase 别名；FastAPI 默认 response_model_by_alias=True，因此线上传输的是
camelCase，与《规范》6.2 和 docs/api-dashboard.md 一致。
"""
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# ---------- 统计窗口天数（请求参数契约）----------
# 单一定义处：dashboard_service 也从这里导入，避免前后端/前后层各写一个 7 而漂移。
DEFAULT_DAYS = 7
MIN_DAYS = 1
MAX_DAYS = 90


class _CamelModel(BaseModel):
    """所有对外模型的基类：传输层 camelCase，Python 侧 snake_case"""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ============ GET /stats ============
class PeakHourItem(_CamelModel):
    """预约高峰时段的一项"""
    hour: int = Field(ge=0, le=23, description="小时，0-23")
    count: int = Field(ge=0, description="该小时内的预约次数")


class FaultFrequencyItem(_CamelModel):
    """设备故障频次的一项"""
    device_name: str = Field(description="设备名称")
    count: int = Field(ge=0, description="该设备的维修工单数")


class DashboardStatsData(_CamelModel):
    """
    /stats 的 data 结构（《规范》5.3 模块 8）

    注意：本模型作为 FastAPI 的 response_model 使用，**会过滤掉未声明的字段** ——
    服务层 dict 里多出来的 key 会被静默丢弃。所以「返回什么」必须在这里有声明。

    `degraded` 于 2026-09-28 补上（原 B1 待办）：库不可达时路由层降级返回
    零值四字段 + `degraded=true`，让前端能区分「真的是 0%」与「取数失败」。
    不补这个字段的话，前端会拿到四个 0/空数组却无从判断，与 `ge=0` 的校验也自相矛盾。

    ⚠️ **声明在最后**：前四个字段的位置一个没动（`test_api_contract.py` C1/C2 锁着
    字段顺序，前端按顺序渲染，挪位置等于破坏契约）。新增只能往后追加。
    """
    space_usage_rate: float = Field(ge=0, le=100, description="场地使用率，百分比 0-100")
    device_idle_rate: float = Field(ge=0, le=100, description="设备闲置率，百分比 0-100")
    peak_hours: list[PeakHourItem] = Field(description="按小时统计的预约次数，count 降序")
    fault_frequency: list[FaultFrequencyItem] = Field(description="按设备统计的维修工单数，Top 10")
    degraded: bool = Field(
        default=False,
        description=(
            "是否走了降级路径。true = 数据库不可达，上面四项均为**占位零值**"
            "（不是真实统计结果），前端应显示「数据暂时不可用」而非当成 0"
        ),
    )


# ============ GET /report ============
class Suggestion(_CamelModel):
    """
    单条 AI 建议。《规范》4.4 模块 8 强制三要素齐全，缺一不可。
    """
    finding: str = Field(min_length=1, description="发现的事实，含具体数字")
    evidence: str = Field(min_length=1, description="数据依据，引用统计结果中的真实数字")
    suggestion: str = Field(min_length=1, description="可执行的建议动作")


class DashboardReportData(_CamelModel):
    """`/report` 的 data 结构"""
    suggestions: list[Suggestion] = Field(
        description="AI 建议，每条含三要素；**永不为空数组**（LLM 不可用时走纯统计降级）"
    )
    export_url: str | None = Field(
        default=None,
        description=(
            "CSV 报告下载链接（相对路径，如 /static/exports/dashboard_20260927_194500.csv）；"
            "数据库不可达或写盘失败时为 null"
        ),
    )
    degraded: bool = Field(
        default=False, description="是否走了降级路径（true = LLM 不可用，建议由纯统计生成）"
    )


# ============ 请求参数 ============
class DaysQuery(_CamelModel):
    """
    统计窗口天数查询参数。

    抽成模型是为了让「默认值 / 范围」有单一出处；实际路由里用
    `Query(DEFAULT_DAYS, ge=MIN_DAYS, le=MAX_DAYS)` 声明，
    以便 OpenAPI 生成准确的参数约束（前端可在 /docs 直接看到 1–90）。
    """
    days: int = Field(
        default=DEFAULT_DAYS, ge=MIN_DAYS, le=MAX_DAYS,
        description=f"统计窗口天数，默认 {DEFAULT_DAYS}，范围 {MIN_DAYS}-{MAX_DAYS}",
    )
