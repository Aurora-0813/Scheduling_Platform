"""
监控与探针 schema（模块 10）

单位约定（**必须与前端模块 8 对齐，已写入 docs/api.md**）
------------------------------------------------------
文档 5.3 给出的示例是 `{"totalCalls": 128, "successRate": 96.1, "avgLatency": 3.2}`。
`successRate` 是 96.1 而不是 0.961，`avgLatency` 是 3.2（秒）。

因此本文件的约定是：

| 字段          | 单位 / 取值域            |
| ------------- | ------------------------ |
| `successRate` | **百分比**，0~100，1 位小数 |
| `avgLatency`  | **秒**，1 位小数          |
| `degradedRate`| 百分比，0~100，1 位小数   |

注意 `MetricsSnapshot.success_rate` 返回的是 0~1 的比值，
换算成百分比是 `app/services/monitor_service.py` 的职责 —— 不要在这里
二次换算，也不要让 router 自己算。
"""

from __future__ import annotations

from app.core.camel import CamelModel

__all__ = ["ReadyStatus", "AgentMonitorOut"]


class ReadyStatus(CamelModel):
    """`GET /ready` 的 data。"""

    status: str
    """`ok` / `degraded`：整体结论。"""

    db: str
    """`ok` / `error`。"""

    redis: str
    """`ok` / `degraded` / `disabled`。`disabled` 表示配置为不使用 Redis，属正常。"""

    app_env: str
    """当前环境（`dev` / `prod`），便于确认探针打到的是哪个环境。"""


class AgentMonitorOut(CamelModel):
    """
    `GET /monitor/agent` 的 data。

    前三个字段是文档 5.3 约定的契约，**任何情况下都会返回**。
    其余字段仅在 `?detail=true` 时返回（不接受时保持 None，
    由路由的 `response_model_exclude_none=True` 从 JSON 里剔除）。

    为什么不拆成两个响应模型：FastAPI 只认一个 `response_model`，
    若按 `detail` 声明成两个模型、运行时返回另一个的实例，
    Pydantic 会**静默丢弃**不在声明模型里的字段 —— 表现为「传了 detail=true
    却没有额外字段」，且不报错。用「可选字段 + exclude_none」既能表达
    两种形态，又不会踩这个静默截断。
    """

    total_calls: int
    """`/api/v1/agent/*` 的 HTTP 请求数（按请求计，非按 token 计）。"""

    success_rate: float
    """成功百分比（0~100，1 位小数）。仅按 HTTP 状态码判定：< 400 记为成功。"""

    avg_latency: float
    """平均耗时，单位**秒**（1 位小数）。"""

    # ---- 以下仅在 detail=true 时返回 ----
    success_calls: int | None = None
    """成功调用数。"""

    error_calls: int | None = None
    """失败调用数（HTTP 状态码 >= 400）。"""

    degraded_calls: int | None = None
    """
    大模型降级次数。

    降级通常仍返回 HTTP 200，因此**单列**、不并入 `successRate` ——
    否则模块 4 大量降级时主指标会掉到 80% 以下，看起来像系统故障，
    实际是设计好的降级路径在生效。
    """

    degraded_rate: float | None = None
    """降级百分比（0~100，1 位小数）。"""

    source: str | None = None
    """数据来源：`redis`（跨重启累计）或 `memory`（本进程启动至今，说明 Redis 不可用）。"""
