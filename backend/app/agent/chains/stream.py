"""调度过程的**事件流**（2026-10-13 新增）。

## 解决什么

原先 `POST /agent/schedule` 是「攒完再返回」：Agent 内部其实早就在流式收消息
（见 `trace.py` 的 `astream(stream_mode="updates")`），但那一路流在 `run_schedule`
里就被收干了，HTTP 层再一次性给前端 —— 前端只能转圈等 40 秒，拿到完整 trace 后
用 setInterval 假装逐步播出。

本模块把那条**已经存在的流**接出来：边跑边 yield 事件。取法由调用方决定：
Web 与小程序/APK **统一走「任务 + 轮询」**（`uni.request` 拿不到 chunk，
两个端用同一套代码省一半维护成本；前端再配一个本地逐字队列，观感一样丝滑）。

## 事件协议

| event | data | 用途 |
|---|---|---|
| `start` | `{requestId, fast}` | 清空旧内容 |
| `thinking` | `{delta}` | **逐字**追加（打字机） |
| `tool_args` | `{name, delta}` | 工具参数边生成边到 |
| `step` | `{...TraceStep}` | 一步成型/更新，**按 step 号覆盖**（幂等） |
| `plan` | `{plan, backupPlan}` | 方案成形 |
| `error` | `{message}` | 降级原因（HTTP 仍是 200，与既有口径一致） |

`plan` / `error` 的 data 里带一个私有键 `_outcome`（`AgentOutcome`），
调用方取走后**必须删掉**再转发/落缓存（它不是 JSON 可序列化的）。
`done` 由调用方发 —— 它要先做埋点与 `agent_trace` 补写。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessageChunk, BaseMessage

from app.agent.chains.builder import (
    AgentOutcome,
    _compose_user_message,
    _plan_missing_message,
    _to_plan,
    build_agent,
    build_model,
    extract_locked_order_id,
    extract_plan_from_text,
    extract_submitted_plan,
)
from app.agent.chains.trace import _absorb, build_trace
from app.agent.context import agent_run_context
from app.agent.prompts.fast import build_fast_prompt
from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.agent import ScheduleData, TraceStep
from app.services.device_service import list_available_devices
from app.services.order_service import create_order
from app.services.space_service import list_available_spaces

logger = get_logger(__name__)

__all__ = ["stream_events"]


def _chunk_text(msg: Any) -> str:
    """AIMessageChunk → 纯文本增量。content 可能是 str，也可能是 parts 列表。"""
    content = getattr(msg, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(p.get("text") or "")
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    return ""


def _now_str() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _step_payload(step: TraceStep) -> dict:
    return step.model_dump()


def _tail(outcome: AgentOutcome) -> list[dict]:
    """AgentOutcome → 尾部事件。`_outcome` 由调用方取走后删除。"""
    if outcome.data.plan is not None:
        return [
            {
                "event": "plan",
                "data": {
                    "plan": outcome.data.plan.model_dump(),
                    "backupPlan": outcome.data.backupPlan.model_dump()
                    if outcome.data.backupPlan
                    else None,
                    "_outcome": outcome,
                },
            }
        ]
    if not outcome.success:
        return [{"event": "error", "data": {"message": outcome.message, "_outcome": outcome}}]
    return []


async def stream_events(
    *,
    text: str,
    user_id: int,
    image_context: dict[str, Any] | None = None,
    fast: bool = False,
) -> AsyncIterator[dict]:
    """跑一次调度，边跑边 yield 事件。

    与 `run_schedule` / `run_schedule_fast` **同一套降级口径与结果解析**，
    只是把「等它跑完」换成「边跑边报」—— 收尾判定直接复用 builder 里的函数，
    不另写一份（两套口径迟早会漂）。
    """
    request_id = uuid.uuid4().hex[:12]
    started = time.perf_counter()
    yield {"event": "start", "data": {"requestId": request_id, "fast": bool(fast)}}

    try:
        if fast:
            gen = _stream_fast(
                text=text, user_id=user_id, image_context=image_context, started=started
            )
        else:
            gen = _stream_agent(
                text=text, user_id=user_id, image_context=image_context, started=started
            )
        async for ev in gen:
            yield ev
    except Exception as exc:  # noqa: BLE001 - 任何运行期异常都不许穿透成 500
        logger.exception("流式调度异常 request_id=%s", request_id)
        yield {
            "event": "error",
            "data": {
                "message": "AI 调度过程出现异常，本次未能生成方案。请稍后重试，或改用更明确的需求描述。",
                "reason": f"{type(exc).__name__}: {exc}",
            },
        }


# --------------------------------------------------------------------------
# 多轮 Agent 路径
# --------------------------------------------------------------------------
async def _stream_agent(
    *, text: str, user_id: int, image_context: dict[str, Any] | None, started: float
) -> AsyncIterator[dict]:
    agent = build_agent()
    inputs = {
        "messages": [{"role": "user", "content": _compose_user_message(text, image_context or {})}]
    }
    config = {"recursion_limit": settings.AGENT_RECURSION_LIMIT}

    stamped: list[tuple[BaseMessage, str]] = []
    seen: set[int] = {id(m) for m, _ in stamped}
    # step 号 → 上次发出去的 JSON。只有**变了**才重发，避免同一批消息重复推
    emitted: dict[int, str] = {}

    def drain_steps() -> list[dict]:
        out = []
        for s in build_trace(stamped):
            payload = _step_payload(s)
            key = repr(payload)
            if emitted.get(s.step) == key:
                continue
            emitted[s.step] = key
            out.append({"event": "step", "data": payload})
        return out

    deadline = time.perf_counter() + settings.AGENT_TIMEOUT

    with agent_run_context(user_id=user_id, raw_request=text):
        try:
            async for item in agent.astream(
                inputs, stream_mode=["messages", "updates"], config=config
            ):
                if time.perf_counter() > deadline:
                    raise TimeoutError
                if isinstance(item, tuple) and len(item) == 2:
                    mode, payload = item
                else:
                    mode, payload = "updates", item

                if mode == "messages":
                    msg = payload[0] if isinstance(payload, tuple) else payload
                    if isinstance(msg, AIMessageChunk):
                        delta = _chunk_text(msg)
                        if delta:
                            yield {"event": "thinking", "data": {"delta": delta}}
                        for tc in getattr(msg, "tool_call_chunks", None) or []:
                            if isinstance(tc, dict) and tc.get("args"):
                                yield {
                                    "event": "tool_args",
                                    "data": {"name": tc.get("name") or "", "delta": tc["args"]},
                                }
                    continue

                if isinstance(payload, dict):
                    for update in payload.values():
                        if isinstance(update, dict):
                            _absorb(stamped, seen, update.get("messages"))
                    for ev in drain_steps():
                        yield ev
        except TimeoutError:
            for ev in _tail(_degrade_timeout(stamped, started)):
                yield ev
            return
        except (TypeError, ValueError) as exc:
            # 当前 LangGraph 版本不认多模式 —— 退回一次性调用。
            # **不能因为流不了就不干活**，否则升级/降级一次就整条链路挂掉。
            logger.warning("多模式 astream 不可用，退回 ainvoke：%s", exc)
            result = await agent.ainvoke(inputs, config=config)
            _absorb(stamped, seen, (result or {}).get("messages"))
            for ev in drain_steps():
                yield ev

    messages = [m for m, _ in stamped]

    captured = extract_submitted_plan(messages)
    if captured is None:
        captured = extract_plan_from_text(_last_ai_text(messages))
    if captured is None:
        for ev in _tail(_degrade_no_plan(messages, started)):
            yield ev
        return

    plan = _to_plan(captured.get("plan"))
    if plan is None or plan.spaceId is None:
        for ev in _tail(_degrade_no_plan(messages, started)):
            yield ev
        return

    trace = build_trace(stamped)
    locked = extract_locked_order_id(messages)
    for ev in _tail(
        AgentOutcome(
            data=ScheduleData(
                plan=plan,
                backupPlan=_to_plan(captured.get("backupPlan")),
                trace=trace,
                needConfirm=True,
                orderId=locked,
            ),
            message="操作成功",
            success=True,
            degraded=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
            locked_order_id=locked,
            steps=len(trace),
        )
    ):
        yield ev


def _last_ai_text(messages: list[BaseMessage]) -> str | None:
    from app.agent.chains.builder import _last_ai_text as impl

    return impl(messages)


# --------------------------------------------------------------------------
# fast 路径（单次调用）
# --------------------------------------------------------------------------
async def _stream_fast(
    *, text: str, user_id: int, image_context: dict[str, Any] | None, started: float
) -> AsyncIterator[dict]:
    """单次调用：没有多轮思考链，但模型正文同样**逐字**流出。

    收尾（解析 + 落库）与 `run_schedule_fast` 同源：复用同一套
    `extract_plan_from_text` / `_to_plan` / `create_order`。
    """
    steps: list[TraceStep] = []

    def add(result: str, *, thought=None, action=None, observation=None) -> dict:
        steps.append(
            TraceStep(
                step=len(steps) + 1,
                result=result,
                timestamp=_now_str(),
                thought=thought,
                action=action,
                actionInput=None,
                observation=observation,
            )
        )
        return {"event": "step", "data": steps[-1].model_dump()}

    def degrade(message: str, reason: str, order_id: int | None = None) -> AgentOutcome:
        return AgentOutcome(
            data=ScheduleData(
                plan=None, backupPlan=None, trace=list(steps), needConfirm=True, orderId=order_id
            ),
            message=message,
            success=False,
            degraded=True,
            latency_ms=int((time.perf_counter() - started) * 1000),
            locked_order_id=order_id,
            degraded_reason=reason,
            steps=len(steps),
        )

    try:
        space_res = await list_available_spaces()
        device_res = await list_available_devices()
    except Exception as exc:  # noqa: BLE001
        for ev in _tail(degrade("读取资源失败，请稍后重试。", f"{type(exc).__name__}: {exc}")):
            yield ev
        return

    yield add(
        f"读取全部候选资源：场地 {space_res['count']} 个、设备 {device_res['count']} 类",
        action="load_candidates",
        observation={"spaces": space_res["count"], "devices": device_res["count"]},
    )
    if not space_res["spaces"]:
        for ev in _tail(
            degrade(
                "系统里当前没有可用场地，无法生成方案。请先由管理员在资源管理里添加场地。",
                "no_space_available",
            )
        ):
            yield ev
        return

    llm = build_model()  # 配置缺失时抛 AgentUnavailableError，与多轮版一致显式暴露
    prompt = build_fast_prompt(
        text=text,
        spaces=space_res["spaces"],
        devices=device_res["devices"],
        image_context=image_context or {},
        now=None,
    )

    buf: list[str] = []
    stream = llm.astream(prompt)
    while True:
        try:
            chunk = await asyncio.wait_for(stream.__anext__(), timeout=settings.AGENT_TIMEOUT)
        except StopAsyncIteration:
            break
        except TimeoutError:
            for ev in _tail(
                degrade(
                    f"AI 思考超时（超过 {settings.AGENT_TIMEOUT:g} 秒）。"
                    "快速模式建议把需求说得更简短后重试。",
                    "timeout",
                )
            ):
                yield ev
            return
        except Exception as exc:  # noqa: BLE001
            for ev in _tail(
                degrade("AI 调用失败，本次未能生成方案。请稍后重试。", f"{type(exc).__name__}: {exc}")
            ):
                yield ev
            return
        delta = _chunk_text(chunk)
        if delta:
            buf.append(delta)
            yield {"event": "thinking", "data": {"delta": delta}}

    raw_text = "".join(buf)
    captured = extract_plan_from_text(raw_text)
    if captured is None:
        for ev in _tail(degrade(raw_text or "AI 未能给出可执行方案。", "no_plan_returned")):
            yield ev
        return
    plan = _to_plan(captured.get("plan"))
    if plan is None or plan.spaceId is None:
        for ev in _tail(degrade(raw_text or "AI 未给出可执行的场地。", "plan_without_space")):
            yield ev
        return
    if not plan.startTime or not plan.endTime:
        for ev in _tail(degrade("AI 未给出完整时段，无法锁定资源。", "plan_without_time")):
            yield ev
        return

    yield add(
        f"AI 一次决策完成：选中 {plan.spaceName or plan.spaceId}",
        thought=plan.reason,
        action="submit_plan",
        observation=plan.model_dump(),
    )

    try:
        result = await create_order(
            user_id=user_id,
            space_id=plan.spaceId,
            start_time=plan.startTime,
            end_time=plan.endTime,
            device_ids=list(plan.deviceIds or []),
            agent_request=text,
            agent_trace=None,
            order_status=1,
        )
    except Exception as exc:  # noqa: BLE001
        for ev in _tail(
            degrade("锁定资源时出现异常，方案未能落库。请稍后重试。", f"{type(exc).__name__}: {exc}")
        ):
            yield ev
        return

    if not result.get("ok"):
        yield add("锁定资源失败", action="lock_resources", observation=result)
        for ev in _tail(
            degrade(
                result.get("reason") or "锁定资源失败，请换个时段或场地重试。",
                f"lock_failed:{result.get('conflictType')}",
            )
        ):
            yield ev
        return

    order_id = result.get("orderId")
    valid_id = order_id if isinstance(order_id, int) and not isinstance(order_id, bool) and order_id > 0 else None
    yield add(
        f"资源已锁定，订单 #{order_id}", action="lock_resources", observation={"ok": True, "orderId": order_id}
    )
    for ev in _tail(
        AgentOutcome(
            data=ScheduleData(
                plan=plan,
                backupPlan=_to_plan(captured.get("backupPlan")),
                trace=list(steps),
                needConfirm=True,
                orderId=valid_id,
            ),
            message="操作成功",
            success=True,
            degraded=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
            locked_order_id=valid_id,
            steps=len(steps),
        )
    ):
        yield ev


# --------------------------------------------------------------------------
# 降级
# --------------------------------------------------------------------------
def _degrade_timeout(stamped, started: float) -> AgentOutcome:
    trace = build_trace(stamped)
    locked = extract_locked_order_id([m for m, _ in stamped])
    return AgentOutcome(
        data=ScheduleData(plan=None, backupPlan=None, trace=trace, needConfirm=True, orderId=locked),
        message=(
            f"AI 思考超时（超过 {settings.AGENT_TIMEOUT:g} 秒），已思考到第 {len(trace)} 步。"
            "建议把需求拆得更简单一些，或稍后重试。"
        ),
        success=False,
        degraded=True,
        latency_ms=int((time.perf_counter() - started) * 1000),
        locked_order_id=locked,
        degraded_reason="timeout",
        steps=len(trace),
    )


def _degrade_no_plan(messages: list[BaseMessage], started: float) -> AgentOutcome:
    locked = extract_locked_order_id(messages)
    return AgentOutcome(
        data=ScheduleData(plan=None, backupPlan=None, trace=[], needConfirm=True, orderId=locked),
        message=_plan_missing_message(messages),
        success=False,
        degraded=True,
        latency_ms=int((time.perf_counter() - started) * 1000),
        locked_order_id=locked,
        degraded_reason="no_plan_returned",
        steps=0,
    )
