"""思考链提取：LangGraph `messages` → 阶段 2 冻结的 `TraceStep`（阶段 5 任务 5-3 / 5-4）。

主文档 3.3 的映射约定：

| messages 元素 | TraceStep 字段 |
| --- | --- |
| `AIMessage.content` | `thought` |
| `AIMessage.tool_calls[].name` | `action` |
| `AIMessage.tool_calls[].args` | `actionInput` |
| `ToolMessage.content` | `observation` |

## 一次「步骤」是一条 Thought-Action-Observation 三元组，不是一条消息

`AIMessage`（带 `tool_calls`）与紧随其后的 `ToolMessage` **合并成一步**：
前者的 content/name/args 填 thought/action/actionInput，后者的 content 填 observation。
这与 `docs/api.md` 模块 4 的响应示例一致——示例里 step 1 只有 thought（纯推理），
step 2 是 `query_spaces` 带全 actionInput 与 observation。

若拆成两步（发指令一步、收结果一步），前端屏 3 的时间轴会多出一倍节点，
且每步都缺一半要素，渲染出来是一串「只有动作没有结果」的卡片。

## 时间戳为什么必须在这里打（本阶段最容易做错的地方）

`messages` 里**没有墙钟时间**。如果在 Agent 跑完后统一提取、统一打点，
所有步骤的 `timestamp` 会是同一个值，前端按时间轴回放（阶段 6 / 主线一屏 3）
就退化成「所有步骤同时出现」——40 秒的思考过程变成一个瞬间。

所以本模块用 `astream(stream_mode="updates")` **边收边打点**：每收到一条新消息，
就记录当时的真实时间。代价是多一个异步函数，换来时间轴是真的。

**这个问题在假 LLM 下测不出来**：假模型不产生真实耗时，多步会落在同一秒内。
阶段 5 §6 因此要求用真实 API 冒烟一次专门验它。

## `timestamp` 的严格递增由本文件保证

冻结契约（`docs/api.md` 模块 4）写明「各步 `timestamp` 互不相同且递增，可直接用于
时间轴回放」。真实调用下各步间隔通常 >1 秒，但**同一秒内完成多步的情况是存在的**
（工具返回极快、或模型把多个 tool_call 放在一条 AIMessage 里）。此时按原值输出就
违反契约，前端回放会出现两节点重叠。

处置：同秒内的后续步骤**依次 +1 秒**顺延，保证严格递增。这是有意的、有界的
（每步最多顺延 1 秒）保序处理，不影响「溯源」用途；代价是极快运行的 trace 在
时间轴上被略微拉开。**反过来不做**（保留同秒）会让前端在演示当天出现重叠节点，
那才是真问题。
"""
from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta
from typing import Any, Iterable

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from app.schemas.agent import TraceStep

__all__ = [
    "collect_stamped_messages",
    "build_trace",
    "parse_observation",
    "now_str",
    "TIMESTAMP_FORMAT",
]

#: 契约要求的格式（`docs/api.md` 模块 4）。
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

#: Tool 名 → 中文动作名。`result` 里的中文结论靠它拼。
_ACTION_LABEL = {
    "query_spaces": "查询场地",
    "query_devices": "查询设备",
    "lock_resources": "锁定资源",
    "generate_notification": "生成通知文案",
    "submit_plan": "提交方案",
}

#: `result` 的长度上限。前端屏 3 的卡片放不下长文本。
_RESULT_MAX_LEN = 80


def now_str() -> str:
    """当前时刻的契约格式串。

    单独抽成函数是为了让用例能替换它——`AGENT-U-05` 要验的是
    「逐步打点」这个机制，不是 `datetime.now()` 本身。
    """
    return datetime.now().strftime(TIMESTAMP_FORMAT)


# --------------------------------------------------------------------------
# 一、边收边打点
# --------------------------------------------------------------------------
def _absorb(stamped: list[tuple[BaseMessage, str]], seen: set[int], messages: Any) -> None:
    """把一批新消息追加进带时间戳的列表。按 `id()` 去重。

    去重不是防御性编程：`updates` 模式下同一节点可能分多次 yield，
    而部分 LangGraph 小版本在流式收尾时会重放最后一条 state。
    不过滤的话，trace 尾部会出现重复步骤。
    """
    if not messages:
        return
    if isinstance(messages, BaseMessage):
        messages = [messages]
    for msg in messages:
        if not isinstance(msg, BaseMessage) or id(msg) in seen:
            continue
        seen.add(id(msg))
        stamped.append((msg, now_str()))


async def collect_stamped_messages(
    agent: Any,
    inputs: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    sink: list[tuple[BaseMessage, str]] | None = None,
) -> list[tuple[BaseMessage, str]]:
    """跑一次 Agent，返回**按到达顺序、各自带真实时间戳**的消息列表。

    优先用 `astream(stream_mode="updates")` 边收边打点（阶段 5 任务 5-4）。
    若当前 LangGraph 版本不产出 `updates` 形状的 chunk（实测没有，但版本会变），
    退回 `ainvoke()` 并在 `build_trace` 里靠保序逻辑把时间戳拉开——
    **宁可退化成「时间轴被拉开」，也不要静默地全部同秒**。

    `sink` 由调用方传入时**原地追加**，函数返回的也是同一个列表。
    存在的唯一理由：超时（阶段 6 任务 6-3 / 主文档 13.1）时 `wait_for` 会取消本协程，
    返回值根本拿不到，但调用方**仍要拿到已经思考到的那几步**——
    「前端可展示思考到哪一步中断了」靠的就是这个引用。
    """
    stamped: list[tuple[BaseMessage, str]] = [] if sink is None else sink
    seen: set[int] = {id(m) for m, _ in stamped}
    base_len = len(stamped)

    try:
        async for chunk in agent.astream(inputs, stream_mode="updates", config=config):
            if not isinstance(chunk, dict):
                continue
            for update in chunk.values():
                if isinstance(update, dict):
                    _absorb(stamped, seen, update.get("messages"))
    except (TypeError, ValueError):
        # 不支持的 stream_mode，或图不接受该参数——退回一次性调用。
        # 只回退「本次尝试新增的」：sink 里已有的步骤不动，
        # 否则退回 `ainvoke` 会把前面已打点的步骤重复一遍。
        del stamped[base_len:]
        seen = {id(m) for m, _ in stamped}

    if len(stamped) == base_len:
        result = await agent.ainvoke(inputs, config=config)
        _absorb(stamped, seen, (result or {}).get("messages"))

    return stamped


# --------------------------------------------------------------------------
# 二、映射成 TraceStep
# --------------------------------------------------------------------------
def parse_observation(content: Any) -> dict[str, Any] | None:
    """`ToolMessage.content` → dict。

    Tool 返回的是 dict，但 `ToolMessage.content` 是**字符串**（框架序列化的结果），
    不同版本可能用 `json.dumps`（双引号）或 `str()`（单引号、Python 字面量）。
    两种都试，都不成才包成 `{"text": ...}`——**不允许因为解析不了就丢字段**，
    前端屏 3 要靠 observation 渲染工具结果。

    **对外公开**（不带下划线）是因为 `chains/builder.py` 也用它取 `orderId`：
    「Tool 产出 → 调用方消费」只有 `messages` 这一条通道，两处的解析必须一致，
    否则会出现「trace 里看得到订单号、补写 agent_trace 却拿不到」这种割裂。
    """
    if content is None:
        return None
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        return {"content": content}
    if not isinstance(content, str):
        return {"text": str(content)}

    text = content.strip()
    if not text:
        return None
    for loader in (json.loads, ast.literal_eval):
        try:
            parsed = loader(text)
        except (ValueError, SyntaxError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}
    return {"text": text}


def _clip(text: str) -> str:
    text = " ".join(str(text).split())
    if len(text) > _RESULT_MAX_LEN:
        text = text[: _RESULT_MAX_LEN - 1] + "…"
    return text


def _summarize(action: str | None, observation: dict[str, Any] | None, thought: str | None) -> str:
    """把一步归纳成中文结论（阶段 5 §3.3：`result` 写本步骤的中文结论）。"""
    if action is None:
        return _clip(thought) or "模型推理"

    label = _ACTION_LABEL.get(action, action)

    if observation is None:
        return f"{label}：已发起，尚未返回结果"

    if action in ("query_spaces", "query_devices"):
        ok = observation.get("ok", True)
        count = observation.get("count")
        if not ok:
            return _clip(f"{label}：{observation.get('reason', '未命中')}")
        unit = "个候选场地" if action == "query_spaces" else "台可借设备"
        if not count:
            return f"{label}：无匹配结果"
        return f"{label}：命中 {count} {unit}"

    if action == "lock_resources":
        if observation.get("ok"):
            order_id = observation.get("orderId")
            return f"{label}：成功" + (f"（订单 {order_id}）" if order_id else "（未落库）")
        return _clip(f"{label}：失败（{observation.get('conflictType') or '未知原因'}）")

    if action == "submit_plan":
        return f"{label}：已提交"

    if action == "generate_notification":
        if not observation.get("ok", True):
            return _clip(f"{label}：失败（{observation.get('reason', '未提供原因')}）")
        title = observation.get("title")
        return _clip(f"{label}：{title}") if title else label

    return label


def _merge_steps(stamped: Iterable[tuple[BaseMessage, str]]) -> list[dict[str, Any]]:
    """把「消息流」合并成「步骤流」。

    合并规则见模块 docstring：AIMessage 开一步，紧随的 ToolMessage 补上 observation。
    一条 AIMessage 里若带多个 `tool_calls`，**每个 tool_call 各起一步**
    （它们共享该消息的到达时刻，时间戳由下一步的保序逻辑拉开）。
    """
    steps: list[dict[str, Any]] = []

    for msg, ts in stamped:
        if isinstance(msg, ToolMessage):
            tool_name = getattr(msg, "name", None)
            # 从后往前找最近一个「有 action、还没有 observation」的步骤。
            # 从后往前是因为并行工具调用时，多条 ToolMessage 会依次补回同一批步骤。
            for step in reversed(steps):
                if step["action"] and step["observation"] is None and (
                    tool_name is None or step["action"] == tool_name
                ):
                    step["observation"] = parse_observation(msg.content)
                    break
            continue

        if not isinstance(msg, AIMessage):
            # HumanMessage / SystemMessage 不进 trace——它们是输入，不是思考过程。
            continue

        thought = msg.content if isinstance(msg.content, str) else None
        thought = thought.strip() or None if thought else None
        tool_calls = getattr(msg, "tool_calls", None) or []

        if not tool_calls:
            steps.append({
                "timestamp": ts, "thought": thought,
                "action": None, "actionInput": None, "observation": None,
            })
            continue

        for call in tool_calls:
            args = call.get("args") if isinstance(call, dict) else getattr(call, "args", None)
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            steps.append({
                "timestamp": ts, "thought": thought,
                "action": name,
                "actionInput": args if isinstance(args, dict) else None,
                "observation": None,
            })

    return steps


def _enforce_strictly_increasing(timestamps: list[str]) -> list[str]:
    """保证各步 `timestamp` 严格递增（冻结契约的明文承诺）。

    解析不了的时刻**原样保留**，不做顺延——顺延的前提是能比较；
    宁可让异常值暴露出来，也不要拿一个猜的时间往下推。
    顺延只在本步与上一步同秒或更早时发生，每次 +1 秒。
    """
    result: list[str] = []
    previous: datetime | None = None

    for raw in timestamps:
        try:
            current = datetime.strptime(raw, TIMESTAMP_FORMAT)
        except (ValueError, TypeError):
            result.append(raw)
            continue

        if previous is not None and current <= previous:
            current = previous + timedelta(seconds=1)
        result.append(current.strftime(TIMESTAMP_FORMAT))
        previous = current

    return result


def build_trace(stamped: Iterable[tuple[BaseMessage, str]]) -> list[TraceStep]:
    """带时间戳的消息流 → 冻结契约的 `TraceStep` 列表。

    `step` 从 1 递增；`result` 由 action 与 observation 归纳；
    `timestamp` 经严格递增保序（见模块 docstring）。
    """
    steps = _merge_steps(stamped)
    timestamps = _enforce_strictly_increasing([s["timestamp"] for s in steps])

    return [
        TraceStep(
            step=index,
            result=_summarize(s["action"], s["observation"], s["thought"]),
            timestamp=timestamps[index - 1],
            thought=s["thought"],
            action=s["action"],
            actionInput=s["actionInput"],
            observation=s["observation"],
        )
        for index, s in enumerate(steps, start=1)
    ]
