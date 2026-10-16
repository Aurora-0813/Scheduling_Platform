"""单次调用快速调度链路（与多轮 Agent 并存，互不影响）。

## 为什么有这条链路

多轮 Agent（builder.py）每决定「查什么」都要一次模型往返：实测 6~8 轮、40~80 秒。
本链路把「查什么」交给后端 —— 一次性读出全部候选资源，只有**一次**模型调用
让模型做选择题。实测可压到 5~10 秒（几乎全花在那一次调用上）。

## 与多轮版的关系

- **不动** builder.py 的多轮链路，两个模式并存，由请求参数 fast 切换。
- 返回**同一个** AgentOutcome，所以 API 层、埋点、agent_trace 补写全部复用。
- trace 是 3~4 步的真实时间戳（读候选 / 模型决策 / 锁资源），不是编造的多轮推理。

## 取舍（答辩要能讲清）

单次调用**没有**多轮 Agent 的「模型自己决定查什么」的能力：候选是全量的，
模型只能在给定候选里选。资源规模上千、候选塞不进 Prompt 时要回到多轮版。

## 为什么不做「规则抽取约束」

抽取（人数/时间/类型/设备）最难的是相对时间（「下周三」这类），规则写死了很容易错、
而且错了不报错 —— 只会把活动排到错误的日期上。本项目场地只有个位数，
**全量候选塞进 Prompt 完全放得下**，于是干脆不做抽取，原始需求原样交给模型，
由它自己解析时间与取舍 —— 既快，又绕开了抽取不准的坑。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

from app.agent.chains.builder import (
    AgentOutcome,
    AgentUnavailableError,
    _to_plan,
    build_model,
    extract_plan_from_text,
)
from app.agent.prompts.fast import build_fast_prompt
from app.core.config import settings
from app.schemas.agent import ScheduleData, TraceStep
from app.services.device_service import list_available_devices
from app.services.order_service import create_order
from app.services.space_service import list_available_spaces

__all__ = ["run_schedule_fast"]


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _content_text(resp: Any) -> str:
    """把模型回复的 content 统一取成字符串（可能是 str，也可能是分段 list）。"""
    content = getattr(resp, "content", resp)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return str(content)


async def run_schedule_fast(
    *,
    text: str,
    user_id: int,
    image_context: dict[str, Any] | None = None,
    model: Any = None,
    now: datetime | None = None,
) -> AgentOutcome:
    """跑一次「全量候选 + 单次模型调用」的快速调度。

    与 run_schedule 的返回类型、降级口径**完全一致**，调用方无需分支。
    """
    started = time.perf_counter()
    steps: list[TraceStep] = []

    def _elapsed_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    def _add(
        result: str,
        *,
        thought: str | None = None,
        action: str | None = None,
        action_input: dict | None = None,
        observation: dict | None = None,
    ) -> None:
        steps.append(
            TraceStep(
                step=len(steps) + 1,
                result=result,
                timestamp=_now_str(),
                thought=thought,
                action=action,
                actionInput=action_input,
                observation=observation,
            )
        )

    def _degrade(message: str, reason: str, order_id: int | None = None) -> AgentOutcome:
        return AgentOutcome(
            data=ScheduleData(
                plan=None,
                backupPlan=None,
                trace=list(steps),
                needConfirm=True,
                orderId=order_id,
            ),
            message=message,
            success=False,
            degraded=True,
            latency_ms=_elapsed_ms(),
            locked_order_id=order_id,
            degraded_reason=reason,
            steps=len(steps),
        )

    # ---- (1) 全量候选：2 次 DB 查询（毫秒级）----
    try:
        space_res = await list_available_spaces()
        device_res = await list_available_devices()
    except Exception as exc:  # noqa: BLE001 - 与多轮版同一口径：运行期异常不穿透成 500
        return _degrade("读取资源失败，请稍后重试。", f"{type(exc).__name__}: {exc}")

    _add(
        f"读取全部候选资源：场地 {space_res['count']} 个、设备 {device_res['count']} 类",
        action="load_candidates",
        observation={"spaces": space_res["count"], "devices": device_res["count"]},
    )

    if not space_res["spaces"]:
        return _degrade(
            "系统里当前没有可用场地，无法生成方案。请先由管理员在资源管理里添加场地。",
            "no_space_available",
        )

    # ---- (2) 一次模型调用（本链路唯一的大模型往返）----
    try:
        llm = model if model is not None else build_model()
    except AgentUnavailableError:
        # 配置缺失属服务端问题，与多轮版一样显式抛出，不伪装成「AI 没想出方案」。
        raise

    prompt = build_fast_prompt(
        text=text,
        spaces=space_res["spaces"],
        devices=device_res["devices"],
        image_context=image_context or {},
        now=now,
    )

    try:
        resp = await asyncio.wait_for(llm.ainvoke(prompt), timeout=settings.AGENT_TIMEOUT)
    except TimeoutError:
        return _degrade(
            f"AI 思考超时（超过 {settings.AGENT_TIMEOUT:g} 秒）。"
            "快速模式建议把需求说得更简短后重试。",
            "timeout",
        )
    except Exception as exc:  # noqa: BLE001
        return _degrade(
            "AI 调用失败，本次未能生成方案。请稍后重试。",
            f"{type(exc).__name__}: {exc}",
        )

    raw_text = _content_text(resp)

    # ---- (3) 解析方案：复用多轮版同一套 JSON 容错解析 ----
    captured = extract_plan_from_text(raw_text)
    if captured is None:
        return _degrade(raw_text or "AI 未能给出可执行方案。", "no_plan_returned")

    plan = _to_plan(captured.get("plan"))
    if plan is None or plan.spaceId is None:
        return _degrade(raw_text or "AI 未给出可执行的场地。", "plan_without_space")
    if not plan.startTime or not plan.endTime:
        return _degrade("AI 未给出完整时段，无法锁定资源。", "plan_without_time")

    _add(
        f"AI 一次决策完成：选中 {plan.spaceName or plan.spaceId}",
        thought=plan.reason,
        action="submit_plan",
        observation=plan.model_dump(),
    )

    # ---- (4) 落库：确定性代码（事务在 create_order 内部）----
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
        return _degrade(
            "锁定资源时出现异常，方案未能落库。请稍后重试。",
            f"{type(exc).__name__}: {exc}",
        )

    if not result.get("ok"):
        _add("锁定资源失败", action="lock_resources", observation=result)
        return _degrade(
            result.get("reason") or "锁定资源失败，请换个时段或场地重试。",
            f"lock_failed:{result.get('conflictType')}",
        )

    order_id = result.get("orderId")
    valid_order_id = (
        order_id
        if isinstance(order_id, int) and not isinstance(order_id, bool) and order_id > 0
        else None
    )
    _add(
        f"资源已锁定，订单 #{order_id}",
        action="lock_resources",
        observation={"ok": True, "orderId": order_id},
    )

    return AgentOutcome(
        data=ScheduleData(
            plan=plan,
            backupPlan=_to_plan(captured.get("backupPlan")),
            trace=list(steps),
            needConfirm=True,
            orderId=valid_order_id,
        ),
        message="操作成功",
        success=True,
        degraded=False,
        latency_ms=_elapsed_ms(),
        locked_order_id=valid_order_id,
        steps=len(steps),
    )
