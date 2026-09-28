"""Agent 调用埋点与思考链落库（阶段 6 任务 6-4 / 6-5）。

对应端点是 `GET /api/v1/monitor/agent`（主文档 5.3 模块 10、`docs/api.md` 模块 10）：

```json
{ "totalCalls": 128, "successRate": 96.1, "avgLatency": 3200 }
```

## 「成功」的口径（阶段 6 §3.4 要求写清楚）

**`plan` 非空且未触发降级**才算成功。

不取「HTTP 200 就算成功」：本项目三条降级路径（超时、无方案、模型输出格式错乱）
**全部返回 200**——那是契约内的正常返回，不是异常。若把它们计入成功，
主线二展示的成功率会接近 100%，而这个数字恰恰是给评委看「AI 在真实运行」的证据，
虚高等于自己拆自己的台。

## 存储：进程内计数，不是数据库

`TODO(申云飞)`: 阶段 6 入口条件要求「埋点存储方式已与集成组确认（Redis 或库表）」，
该确认未到位。当前实现是**进程内计数**，满足阶段 6 的通过标准「埋点返回真实数据
（非 0 非空壳）」，但有两个已知边界：

| 边界 | 影响 | 正式方案 |
| --- | --- | --- |
| 进程重启即清零 | 演示中途重启服务，历史计数丢失 | Redis `INCR` / 库表 |
| 多 worker 各自计数 | `uvicorn --workers 4` 时四个进程各报一份 | Redis / 库表 |

选它而不是先塞一张自建表，是因为**建表要走集成组**（主文档 6.5），
自建表等于绕开流程；而进程内计数零依赖、零 DDL，替换点收在这一个文件里——
四个函数（`record_call` / `snapshot` / `reset`）就是全部对外接口。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent.chains.builder import AgentOutcome
from app.services import update_agent_trace

__all__ = ["record_call", "snapshot", "reset", "persist_agent_trace"]


@dataclass
class _Counters:
    """累计计数。单进程内由事件循环串行访问，无需加锁。"""

    total_calls: int = 0
    success_calls: int = 0
    degraded_calls: int = 0
    total_latency_ms: int = 0
    #: 按降级原因分类，供排障；不进响应体（契约只有三个字段，多给字段前端也不认）。
    degraded_reasons: dict[str, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.degraded_reasons is None:
            self.degraded_reasons = {}


_counters = _Counters()


def record_call(outcome: AgentOutcome) -> None:
    """记一次 Agent 调用。API 层在拿到 `AgentOutcome` 后立刻调用。

    ⚠️ **本地调试用，正式埋点走 `app/middlewares/agent_metrics.py`。**
    本函数与 `snapshot()` / `reset()` 是模块 4 阶段 6 自建的**进程内计数**；
    rebase 到 `origin/main`（`9f30d3a`）后监控链路取的是集成组正式版
    （`middlewares/agent_metrics.py` 自动收集 → `core/metrics.py` 的 `MetricStore`
    存 Redis，`services/monitor_service.py` 换算，`GET /api/v1/monitor/agent` 读它）。
    **正式版那套才是线上口径**，本进程内计数**已无任何读端**——保留它是因为
    直调 Agent 时想快速看一眼「跑了几次、成功几次」很顺手，删掉会让本地排障少个抓手。

    ⚠️ **不要拿它当监控数据源**：两个口径数字不同（正式版按 HTTP 状态码判成功、
    降级单列不计入 `successRate`、`avgLatency` 单位是秒；这里按 `outcome.success`
    判定、单位是毫秒），且本计数**进程重启即清零、多 worker 各报一份**。
    清理与否见 `docs/spec/done/README.md` 硬卡点表（低优先、非阻塞）。

    **必须在阶段 6 就埋上**（阶段 6 §3.4）：事后补埋要重跑一遍联调。
    """
    _counters.total_calls += 1
    _counters.total_latency_ms += max(outcome.latency_ms, 0)
    if outcome.success:
        _counters.success_calls += 1
    else:
        _counters.degraded_calls += 1
        reason = outcome.degraded_reason or "unknown"
        _counters.degraded_reasons[reason] = _counters.degraded_reasons.get(reason, 0) + 1


def snapshot() -> dict[str, Any]:
    """给 `GET /api/v1/monitor/agent` 的 data。

    `successRate` 是百分数（保留一位小数），`avgLatency` 单位**毫秒**——
    单位取自 `docs/api.md` 模块 10 的明文「平均耗时（毫秒）」。
    ⚠️ 主文档 5.3 的示例值写的是 `3.2`，那个量级更像秒；两处不一致已记入
    `docs/spec/done/stage-06-completion.md` 的未决事项，**以 `docs/api.md` 为准**
    （它是本模块出具、给前端看的契约）。

    无调用时返回零值而不是 `null`：前端 `toFixed(1)` 拿 `null` 会直接崩。
    """
    total = _counters.total_calls
    success_rate = round(_counters.success_calls / total * 100, 1) if total else 0.0
    avg_latency = round(_counters.total_latency_ms / total) if total else 0
    return {
        "totalCalls": total,
        "successRate": success_rate,
        "avgLatency": avg_latency,
    }


def reset() -> None:
    """清零。**仅供测试夹具使用**——用例之间必须互不影响，
    否则「先跑成功用例再跑埋点用例」与反过来的结果不一样。"""
    global _counters
    _counters = _Counters()


async def persist_agent_trace(
    *,
    order_id: int,
    user_id: int,
    request_text: str,
    outcome: AgentOutcome,
) -> bool:
    """把完整思考链补写入 `reserve_order.agent_trace`。

    时序见 2026-09-27 与蔡玉礼对齐的结果（采纳方案 (a)）：`create_order` 落库那一刻
    本次 Agent 运行**还没结束**，trace 注定残缺，所以那次落 `None`；
    完整 trace 只有跑完之后才存在，由**路由**在这里补一次 UPDATE。

    返回是否写入成功。**失败不抛异常、也不影响响应**：trace 是「溯源」用的附加值，
    写不进去不该让用户拿不到已经生成的方案。失败原因由调用方记日志。

    `agent_trace` 落的是**裸的 TraceStep 对象数组**（主文档 3.3 的
    Thought-Action-Observation 映射结果），不是包了一层的信封对象——
    形状由 2026-09-27 冻结的服务层契约 §7.6 定死，见下方两处说明。
    """
    if order_id is None:
        return False

    # `request_text` 不再进载荷（理由见下），保留参数是因为路由的调用契约就是四项，
    # 而需求原文已经落在 `agent_request` 列上——留在这里只是别让它看起来「被丢了」。
    _ = request_text

    # ⚠️ 这里**不要**包信封（`{"steps": [...], "request": ...}`）。冻结口径写的是
    # `agent_trace: list  # TraceStep 对象数组，整体覆盖该列`，而 `update_agent_trace`
    # 用 `isinstance(agent_trace, list)` 校验：信封 dict 会被判成 `invalid_param`。
    # 后果之所以严重，是因为失败被静默吸收——本函数只把 `ok` 转成 bool、调用点仅记日志
    # 不影响响应，于是「补写没生效」在接口上完全看不出来，库里 agent_trace 恒为 NULL，
    # 而 TC-26 / TC-30 验收的恰恰是「溯源完整」。
    # 信封里原本想带的 `request` 已由 `create_order` 落在 `agent_request` 列上，
    # 不必在这里重复承载；`plan` / `degraded` 也在响应体里另有出口。
    steps = [step.model_dump() for step in outcome.data.trace]

    # 空数组要跳过而不是照发：§7.6 明文拒绝 `[]`（空链路在库里与 NULL「尚未生成」
    # 区分不开，前端会把「没跑出东西」渲染成一条空链路），并写明「没有内容可补写时
    # 不要调用本函数」。降级且一步未走时就会走到这里——那时确实不该补写。
    if not steps:
        return False

    result = await update_agent_trace(
        order_id=order_id,
        user_id=user_id,
        agent_trace=steps,
    )
    return bool(result.get("ok"))
