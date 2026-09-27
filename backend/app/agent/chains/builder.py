"""Agent 组装与一次完整调度运行（阶段 5 任务 5-2 / 5-5）。

`create_agent(model, tools, system_prompt)` —— 主文档 3.3 规定 Agent 创建统一用它。
模型名、API Key、`base_url` **全部从 `.env` 读**，本文件不含任何硬编码配置。

## 本文件是三件事的交汇点

1. **组装**：`build_agent()` 把模型、5 个 Tool、渲染后的 Prompt 拼成一个 Agent
2. **运行**：`run_schedule()` 带超时跑一次，边收边打点（`trace.py`）
3. **降级**：模型没按约定调 `submit_plan` 时，从自由文本里容错解析方案；
   解析不出就走契约内降级路径（HTTP 仍 200，`plan=null`，`message` 承载模型原文）

第 3 条是主文档 7.4 明文要求的「大模型输出必须做 JSON 解析容错，异常时返回自然语言文本」，
也是主文档 10.2 要求必须测的两类降级之一。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from app.agent.chains.trace import build_trace, collect_stamped_messages, parse_observation
from app.agent.context import agent_run_context
from app.agent.prompts.scheduler import build_scheduler_prompt
from app.agent.tools import AGENT_TOOLS
from app.core.config import settings
from app.schemas.agent import Plan, ScheduleData

__all__ = [
    "AgentOutcome",
    "AgentUnavailableError",
    "build_agent",
    "build_model",
    "run_schedule",
    "extract_plan_from_text",
    "extract_submitted_plan",
    "extract_locked_order_id",
]


class AgentUnavailableError(RuntimeError):
    """Agent 无法启动——目前只有一种成因：`.env` 里的 LLM 配置不齐。

    与「降级」严格区分：降级是**模型跑了但没给出方案**（HTTP 200，契约内路径）；
    本异常是**根本没跑起来**，属服务端配置问题，API 层把它映射成非 200 的统一响应体。
    """


@dataclass
class AgentOutcome:
    """一次调度的结果，含埋点（阶段 6 任务 6-4）所需的全部字段。"""

    data: ScheduleData
    message: str
    #: 是否算「成功」。口径见 `Stage 6 §3.4`：**`plan` 非空且未触发降级**。
    #: 把降级也计入会让主线二展示的成功率虚高，答辩时经不起问。
    success: bool
    #: 是否走了降级路径（超时 / 模型未交方案 / 工具异常）。
    degraded: bool
    latency_ms: int
    #: 本次运行**真正落库**的订单 ID；没落库为 None。
    #: API 层拿它决定要不要补写 `agent_trace`（时序方案 (a)）：为 None 就跳过，
    #: 不去 UPDATE 一个不存在的订单。桩期恒为 None（`create_order` 不落库）。
    locked_order_id: int | None = None
    #: 降级原因，写日志用；成功时为 None。
    degraded_reason: str | None = None
    steps: int = field(default=0)


def build_model() -> Any:
    """按 `.env` 构造 `ChatOpenAI`。

    ⚠️ **`api_key` 必须显式传参**。`ChatOpenAI` 会隐式读取环境变量 `OPENAI_API_KEY`，
    本机若存在同名变量，请求会被静默路由到别人的额度上，且排查时极难看出。
    显式传参把这个隐式路径堵死（`.env.example` 与 `core/config.py` 都记了这条）。
    """
    if not settings.llm_configured:
        raise AgentUnavailableError(
            "大模型未配置：请在 backend/.env 中填好 LLM_MODEL_NAME / LLM_API_KEY / LLM_BASE_URL。"
        )

    from langchain_openai import ChatOpenAI  # 局部导入：没配 key 的机器上不 import 也行

    return ChatOpenAI(
        model=settings.LLM_MODEL_NAME,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        temperature=settings.LLM_TEMPERATURE,
        timeout=settings.AGENT_TIMEOUT,
        max_retries=settings.LLM_MAX_RETRIES,
    )


def build_agent(model: Any = None, *, now: datetime | None = None) -> Any:
    """组装 Agent。`model` 传 None 时按 `.env` 构造。

    **每次调用都重新组装，刻意不做模块级缓存。** 原因具体：Prompt 里注入了当前时间，
    用户说的「今天下午」「本周五」要靠它换算——缓存住 Agent 等于把首次请求那一刻的
    日期钉死，服务跑过午夜之后所有相对时间都会算错一天，而这种错**不会报错**，
    只会给出一个看起来合理的错误方案。图构造只是拼对象，不含网络调用。
    """
    return create_agent(
        model if model is not None else build_model(),
        tools=AGENT_TOOLS,
        system_prompt=build_scheduler_prompt(now),
    )


# --------------------------------------------------------------------------
# 降级路径一：模型没调 submit_plan，方案写在自由文本里
# --------------------------------------------------------------------------
#: 从正文里抠 JSON 对象：支持 ```json 围栏，也支持裸 `{...}`。
_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def extract_plan_from_text(text: str | None) -> dict[str, Any] | None:
    """尽力从模型自由文本里解析出方案对象。

    这是主文档 7.4 要求的 JSON 解析容错的落点：模型**应该**调 `submit_plan`，
    但它可能改在正文里贴 JSON——那就解析出来，别让一个可用方案因为交付形式
    不合规而丢掉。

    解析不出的返回 `None`，由调用方走「message 承载模型原文」的降级路径。
    **本函数绝不抛异常**：它的全部意义就是在异常路径上多捞一次。
    """
    if not text or not isinstance(text, str):
        return None

    candidates: list[str] = []
    fenced = _FENCE_RE.findall(text)
    candidates.extend(fenced)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start: end + 1])

    for raw in candidates:
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(parsed, dict):
            continue
        # 形态识别：要么本身就是方案，要么外层套了 {"plan": {...}}。
        inner = parsed.get("plan")
        if isinstance(inner, dict):
            return {
                "plan": inner,
                "backupPlan": parsed.get("backupPlan") if isinstance(parsed.get("backupPlan"), dict) else None,
                "reason": parsed.get("reason") or inner.get("reason"),
            }
        if any(k in parsed for k in ("spaceId", "spaceName", "deviceIds")):
            return {"plan": parsed, "backupPlan": None, "reason": parsed.get("reason")}
    return None


# --------------------------------------------------------------------------
# Tool 产出 → 调用方消费：唯一的通道是 messages 流
# --------------------------------------------------------------------------
# 为什么不能用 ContextVar 让 Tool 把方案/订单号「写」给调用方看：
# LangGraph 的 `ToolNode` 用 `asyncio.gather()` 并发跑工具，子任务里的
# `ContextVar.set()` 回不到父 context，读出来是 None——而且是**静默**的。
# 详见 `app/agent/context.py` 的模块 docstring。
#
# 下面两个函数是这条通道的出口。它们只读 `messages`，不依赖任何进程内共享状态，
# 因此并发请求之间天然隔离：每个请求的 `stamped` 是自己的。
def _tool_call_names(messages: list[BaseMessage]) -> dict[str, str]:
    """`tool_call_id` → 工具名。

    比直接读 `ToolMessage.name` 可靠：`name` 由框架填充，某些版本/某些执行路径下
    会是 None；`tool_call_id` 是 LangGraph 自己配对的，一定在。
    """
    names: dict[str, str] = {}
    for msg in messages:
        if not isinstance(msg, AIMessage):
            continue
        for call in getattr(msg, "tool_calls", None) or []:
            if not isinstance(call, dict):
                continue
            call_id, call_name = call.get("id"), call.get("name")
            if call_id and call_name:
                names[call_id] = call_name
    return names


def _tool_name(msg: ToolMessage, names: dict[str, str]) -> str | None:
    call_id = getattr(msg, "tool_call_id", None)
    if call_id and call_id in names:
        return names[call_id]
    return getattr(msg, "name", None)


def _normalize_submission(raw: dict[str, Any]) -> dict[str, Any] | None:
    """把「提交形状」统一成 `extract_plan_from_text` 的同一种返回结构。

    两条来源的字段名不一样，必须在这里抹平，否则下游 `_to_plan(captured["backupPlan"])`
    会静默拿到 None：

    | 来源 | 备选方案字段名 |
    | --- | --- |
    | `submit_plan` 的**入参**（模型按 schema 填） | `backup_plan`（snake_case，Python 侧） |
    | `submit_plan` 的**返回值**（Tool 回显） | `backupPlan`（camelCase，响应契约侧） |
    | 自由文本 JSON（模型自己编） | 两种都可能 |
    """
    plan = raw.get("plan")
    if not isinstance(plan, dict):
        return None

    backup = raw.get("backupPlan")
    if not isinstance(backup, dict):
        backup = raw.get("backup_plan")

    return {
        "plan": plan,
        "backupPlan": backup if isinstance(backup, dict) else None,
        "reason": raw.get("reason") or plan.get("reason"),
    }


def extract_submitted_plan(messages: list[BaseMessage]) -> dict[str, Any] | None:
    """从消息流里取模型交出的方案；没交过返回 None。

    取的顺序有讲究，**先入参后回显**：

    1. 最后一次 `submit_plan` 的 `tool_calls[].args` —— 这是模型的原意，
       即使 Tool 执行失败（理论上不会）也拿得到。
    2. 兜底：`submit_plan` 的 `ToolMessage` 回显。少数执行路径下模型可能把参数
       塞进 `content` 而不是结构化 `tool_calls`（例如模型不支持 function calling 时的
       文本降级），这条兜底让那种情况下方案也不丢。

    返回结构与 `extract_plan_from_text` 一致：`{"plan": ..., "backupPlan": ..., "reason": ...}`。
    """
    for msg in reversed(messages):
        if not isinstance(msg, AIMessage):
            continue
        for call in reversed(getattr(msg, "tool_calls", None) or []):
            if not isinstance(call, dict) or call.get("name") != "submit_plan":
                continue
            args = call.get("args")
            if isinstance(args, dict):
                normalized = _normalize_submission(args)
                if normalized is not None:
                    return normalized

    names = _tool_call_names(messages)
    for msg in reversed(messages):
        if not isinstance(msg, ToolMessage) or _tool_name(msg, names) != "submit_plan":
            continue
        payload = parse_observation(msg.content)
        if isinstance(payload, dict) and payload.get("accepted"):
            normalized = _normalize_submission(payload)
            if normalized is not None:
                return normalized

    return None


def extract_locked_order_id(messages: list[BaseMessage]) -> int | None:
    """从消息流里取**最后一次成功锁定**的订单 ID；没落库返回 None。

    往前扫是为了「先失败几次、最后成功」的路径：只要最近一次成功的 `lock_resources`
    带了订单号，就以它为准。失败的调用不携带 `orderId`，会被略过。

    `orderId` 为 None / 非正整数 / 是 bool 一律当成「没落库」——桩期（阶段 3 的
    `create_order` 不写库）走的就是这条。API 层据此跳过 `update_agent_trace`。
    """
    names = _tool_call_names(messages)
    for msg in reversed(messages):
        if not isinstance(msg, ToolMessage) or _tool_name(msg, names) != "lock_resources":
            continue
        payload = parse_observation(msg.content)
        if not isinstance(payload, dict) or not payload.get("ok"):
            continue
        order_id = payload.get("orderId")
        if isinstance(order_id, bool) or not isinstance(order_id, int) or order_id <= 0:
            continue
        return order_id
    return None


def _to_plan(payload: Any) -> Plan | None:
    """dict → 响应契约的 `Plan`。字段不认识就忽略，缺的按契约留空。"""
    if not isinstance(payload, dict):
        return None
    allowed = set(Plan.model_fields)
    return Plan(**{k: v for k, v in payload.items() if k in allowed})


def _last_ai_text(messages: list[BaseMessage]) -> str | None:
    """取最后一条 AIMessage 的正文——降级时它要原样回给用户（主文档 10.2）。"""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                parts = [
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                joined = "".join(parts).strip()
                if joined:
                    return joined
    return None


def _plan_missing_message(messages: list[BaseMessage]) -> str:
    """模型既没调 `submit_plan`、正文里也没有可解析的方案时，回给用户的话。"""
    text = _last_ai_text(messages)
    if text:
        # 契约内降级：message 承载模型原文（docs/api.md 模块 4「大模型输出格式错乱」一栏）
        return text
    return (
        "AI 未能给出可执行的方案，也没有说明原因。"
        "建议把需求说得更具体，例如：人数、日期与时段、场地类型、需要哪些设备、预算上限。"
    )


# --------------------------------------------------------------------------
# 运行
# --------------------------------------------------------------------------
async def run_schedule(
    *,
    text: str,
    user_id: int,
    image_context: dict[str, Any] | None = None,
    model: Any = None,
    now: datetime | None = None,
) -> AgentOutcome:
    """跑一次完整调度，返回 `AgentOutcome`。

    调用方是 `app/api/v1/agent.py`，它负责把 `AgentOutcome` 包进统一响应体。

    三条降级路径都在这里收口，全部返回 `degraded=True` 且 HTTP 仍为 200：

    | 触发 | `plan` | `message` |
    | --- | --- | --- |
    | 模型调用超时 | None（保留中断前的 trace） | 友好提示 + 已思考到第几步 |
    | 模型没交方案、正文也解析不出 | None | 模型原文 |
    | 工具抛异常 / 其他运行期异常 | None | 友好提示 |

    成功路径的判定口径（阶段 6 §3.4）：**`plan` 非空且未触发降级**。
    """
    started = time.perf_counter()
    agent = build_agent(model, now=now)

    inputs = {
        "messages": [{
            "role": "user",
            "content": _compose_user_message(text, image_context or {}),
        }]
    }
    config = {"recursion_limit": settings.AGENT_RECURSION_LIMIT}

    # 超时时要能拿到「已经思考到的那几步」，所以 stamped 由本函数持有并作为 sink 传入。
    stamped: list[tuple[BaseMessage, str]] = []

    def _elapsed_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    def _degrade(message: str, reason: str) -> AgentOutcome:
        trace = build_trace(stamped)
        messages = [m for m, _ in stamped]
        return AgentOutcome(
            data=ScheduleData(plan=None, backupPlan=None, trace=trace, needConfirm=True),
            message=message,
            success=False,
            degraded=True,
            latency_ms=_elapsed_ms(),
            # 降级也照样报订单号：方案可能没交出来，但库已经锁了。
            # 不报的话这单就成了孤儿——落库了却没人补 agent_trace，也没人告诉用户「已锁但没方案」。
            locked_order_id=extract_locked_order_id(messages),
            degraded_reason=reason,
            steps=len(trace),
        )

    try:
        # 身份与需求原文只在这次 with 块内可见。Tool 读得到，模型读不到、也改不了。
        with agent_run_context(user_id=user_id, raw_request=text):
            await asyncio.wait_for(
                collect_stamped_messages(agent, inputs, config=config, sink=stamped),
                timeout=settings.AGENT_TIMEOUT,
            )
    except asyncio.TimeoutError:
        return _degrade(
            (
                f"AI 思考超时（超过 {settings.AGENT_TIMEOUT:g} 秒），"
                f"已思考到第 {len(build_trace(stamped))} 步。"
                "建议把需求拆得更简单一些，或稍后重试。"
            ),
            "timeout",
        )
    except Exception as exc:  # noqa: BLE001 - 任何运行期异常都不许穿透成 500
        # AGENT-E-04：工具抛异常时降级。这里刻意宽catch：LangGraph 会把 Tool 内的
        # 异常包成不同层级的类型，逐个枚举必然漏；漏掉的那种就是演示当天的 500。
        return _degrade(
            "AI 调度过程出现异常，本次未能生成方案。请稍后重试，或改用更明确的需求描述。",
            f"{type(exc).__name__}: {exc}",
        )

    messages = [m for m, _ in stamped]

    # 正规出口：模型调了 submit_plan，方案在它的 tool_call 入参里。
    captured = extract_submitted_plan(messages)
    if captured is None:
        # 降级路径一：模型改了正文，没调工具 —— 从自由文本里捞。
        captured = extract_plan_from_text(_last_ai_text(messages))

    if captured is None:
        return _degrade(_plan_missing_message(messages), "no_plan_returned")

    plan = _to_plan(captured.get("plan"))
    if plan is None or plan.spaceId is None:
        # 拿到了结构、但里面没有可执行的场地 —— 与「没方案」同级处理。
        # 不把半成品当方案返回：前端拿到一个 spaceId 为 null 的 plan 会直接崩在渲染上。
        return _degrade(_plan_missing_message(messages), "plan_without_space")

    trace = build_trace(stamped)
    return AgentOutcome(
        data=ScheduleData(
            plan=plan,
            backupPlan=_to_plan(captured.get("backupPlan")),
            trace=trace,
            needConfirm=True,
        ),
        message="操作成功",
        success=True,
        degraded=False,
        latency_ms=_elapsed_ms(),
        locked_order_id=extract_locked_order_id(messages),
        steps=len(trace),
    )


def _compose_user_message(text: str, image_context: dict[str, Any]) -> str:
    """把用户文本与模块 2 传来的图像上下文拼成一条人类消息。

    图像上下文（主文档 5.3 模块 2 的 `imageContext`）可能是空间识别结果或草图解读，
    作为**补充证据**拼在需求之后，而不是覆盖它。
    """
    if not image_context:
        return text
    try:
        context_text = json.dumps(image_context, ensure_ascii=False)
    except (TypeError, ValueError):
        context_text = str(image_context)
    return (
        f"{text}\n\n"
        f"[来自摄像头/草图的图像解析上下文，作为补充证据参考，可能与文字描述冲突，"
        f"以文字描述为准并指出冲突]\n{context_text}"
    )
