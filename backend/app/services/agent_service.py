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

    `agent_trace` 落的是 `{"steps": [...], "request": ..., "generatedAt": ...}`：
    主文档 3.3 要求按 Thought-Action-Observation 映射，`steps` 就是那个映射结果；
    外层两个字段是为了答辩溯源时能看清「这段思考是回答哪个需求的」。
    """
    from datetime import datetime

    if order_id is None:
        return False

    payload = {
        "steps": [step.model_dump() for step in outcome.data.trace],
        "request": request_text,
        "plan": outcome.data.plan.model_dump() if outcome.data.plan else None,
        "degraded": outcome.degraded,
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    result = await update_agent_trace(
        order_id=order_id,
        user_id=user_id,
        agent_trace=payload,
    )
    return bool(result.get("ok"))
