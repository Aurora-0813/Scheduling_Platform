"""Tool 3/5：`lock_resources` —— 锁定场地与设备，落预约订单。

对应主文档 5.3 模块 4 冻结签名：
    async def lock_resources(space_id: int, device_ids: list[int], start_time: str, end_time: str) -> dict

## 本 Tool 只做三件事

1. 从**调用上下文**取 `user_id`（不是从参数取，见 `app/agent/context.py` 的说明）
2. 调模块 3 的 `create_order`（名字与 Tool 不同名，**不要混**）
3. 把 `create_order` 的结构化失败翻译成模型能据以决策的返回值

事务本身（`BEGIN → SELECT ... FOR UPDATE → 时段重叠 → 设备可用 → INSERT → COMMIT`，
主文档 5.5）**不在本文件里**，它在 `create_order` 的实现里。Tool 不能直接碰
`AsyncSession`（主文档 3.4 / 7.4 / 9.3），所以这里没有任何事务代码是**正确**的，
不是遗漏。`AGENT-C-01`（并发）验的正是被调用的那一侧。

## 为什么失败必须结构化返回

阶段 4 §3.3：第 3/4 步校验失败要「返回友好提示，让 Agent 转去生成备选方案」。
主文档 4.4 的场景 B（场地拆分）就是靠这条链路成立的——模型收到 `conflictType=time_conflict`
才可能想到「换个场地或拆成两场」，收到一个 TypeError 则只能宣布失败。
"""
from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.context import get_agent_user_id, get_raw_request
from app.agent.tools._common import fail, parse_time
from app.services import create_order

__all__ = ["lock_resources", "LockResourcesArgs"]

#: 模型收到后可自行换方案重试的冲突类型。
#: 值来自 `app/services/order_service.py` 的冻结常量（2026-09-27 与蔡玉礼对齐为 snake_case），
#: 此处**按字面复制**而不是 import 常量再比对——避免两个模块对同一份枚举产生
#: 「改了一边忘了另一边」的隐性耦合。若枚举再变，这里与 order_service 必须同时改，
#: `tests/test_agent_tools.py::test_lock_resources_conflict_type_enum_matches_service`
#: 会在两边不一致时失败，起护栏作用。
_RETRYABLE = frozenset({"time_conflict", "device_conflict", "not_found"})

#: 交给 `create_order` 的时间格式。
#:
#: **为什么要在本层回写规范化**（遗留 #7）：本模块的 `parse_time` 收 4 种格式
#: （含只有日期的 `%Y-%m-%d`），而 service 的 `_parse_time` 只收 3 种，且解不出时
#: **直接抛 `ValueError`**（`order_service.py` 的 `_parse_time` 末尾）。两边一松一紧，
#: 于是「Tool 说合法、service 说非法」：模型传 `"2026-10-15"`，本层校验通过，
#: 原样传给 service 就炸成 traceback 并被 LangGraph 包进 ToolMessage——
#: 模型拿到的不是结构化失败，没法据以改参数。
#: 在本层按 service 的格式回写，分歧就只剩「本层能认、service 也一定能认」这一种。
_SERVICE_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

#: 冲突类型 → 给模型的中文行动建议。**给的是下一步动作，不是错误描述**——
#: 模型据这句话决定改期、换场地还是换设备。
_ACTION_HINT = {
    "time_conflict": "该场地该时段已被占用：请改时段，或改选其他场地，或按用户授权拆成多个小场地。",
    "not_found": "所选的设备 ID 不存在：请先调 query_devices 拿到真实 ID 再重试。",
    "device_conflict": "所选设备不可用或数量不足：请改用替代设备类型（如投影仪→显示屏）后重试。",
    "invalid_param": "参数本身非法（如时段倒置、ID 非数字）：请修正参数后重试，不要原样重发。",
}


class LockResourcesArgs(BaseModel):
    """`lock_resources` 的入参 schema。

    ⚠️ **没有 `user_id`**，这是刻意的：身份从 JWT 解析后经调用上下文注入
    （主文档 5.1 / 9.1）。模型无权决定「替谁预约」。
    """

    space_id: int = Field(..., gt=0, description="场地 ID，必须来自 query_spaces 的返回值")
    device_ids: list[int] = Field(
        default_factory=list,
        description=(
            "要一并锁定的设备 ID 列表，必须来自 query_devices 的返回值。"
            "**必须是数组**，例如 [1, 2]；不要传字符串 \"1\"。不需要设备时传 [] 或省略。"
        ),
    )
    start_time: str = Field(..., description="开始时间，格式 YYYY-MM-DD HH:mm:ss")
    end_time: str = Field(..., description="结束时间，格式 YYYY-MM-DD HH:mm:ss")


@tool("lock_resources", args_schema=LockResourcesArgs)
async def lock_resources(
    space_id: int,
    device_ids: list[int],
    start_time: str,
    end_time: str,
) -> dict:
    """锁定场地与设备并创建预约订单。**这是唯一会真正写库的工具。**

    什么时候用：**方案确定后就调用**，每次运行最多调一次。
    **不要向用户追问「是否要锁定」**——锁定不等于最终生效：订单落库后是**待确认**状态，
    用户确认后才转为**已确认**。所以「用户还没点头」不是不锁的理由；
    不锁的话这个时段没有任何占位，随时可能被别人订走。
    调用前必须先用 query_spaces / query_devices 拿到真实的 ID——不要凭印象填数字。
    本工具会自动带上当前登录用户身份，你不需要也不要尝试指定用户。

    Args:
        space_id: 场地 ID，取自 query_spaces 返回的 `id`。
        device_ids: 设备 ID 数组，取自 query_devices 返回的 `id`；无设备传 []。
        start_time: 开始时间，格式 `YYYY-MM-DD HH:mm:ss`。
        end_time: 结束时间，格式 `YYYY-MM-DD HH:mm:ss`。

    Returns:
        成功：{"ok": true, "orderId": 12, "reason": "..."}
        失败：{"ok": false, "conflictType": "time_conflict", "reason": "...",
               "retryable": true, "actionHint": "该场地该时段已被占用：请改时段..."}

        **`ok=false` 不是异常，是业务冲突**。请读 `actionHint` 决定下一步：
        `retryable=true` 时可以用别的场地/时段/设备重试；`retryable=false` 时应向用户说明原因。
    """
    # ---- 1. 身份：只从调用上下文取。取不到就明确失败，**绝不编造用户** ----
    user_id = get_agent_user_id()
    if user_id is None:
        return fail(
            "调用上下文缺少用户身份，无法创建预约。这是服务端的身份注入问题，"
            "请勿重试本工具；请改为直接向用户说明。",
            conflictType="invalid_param", retryable=False, actionHint=None,
        )

    # ---- 2. 参数校验（服务层还会再校验一次，这里先挡一道，省一次往返）----
    # ⚠️ `device_ids` 的类型**必须在本层挡住**，不能只靠 `args_schema`。
    # 原因具体：`list(device_ids or [])` 对字符串是**逐字符迭代**的——
    # `device_ids="1"` 会静默变成 `["1"]`，再被 `create_order` 的整数容错转成 `[1]`，
    # 于是一次传错类型的调用变成了一次**成功且正确**的预约（错得无声无息）。
    # `order_service` 专门为这个形状写了拒绝分支，本层若先 `list()` 一遍就等于把它拆掉。
    if device_ids is not None and not isinstance(device_ids, (list, tuple)):
        return fail(
            f"device_ids 必须是数组，收到 {type(device_ids).__name__}（{device_ids!r}）。"
            "传字符串会被逐字符迭代成错误的 ID 列表，例如 \"12\" → [1, 2]。",
            conflictType="invalid_param", retryable=False,
            actionHint=_ACTION_HINT["invalid_param"],
        )

    start_dt = parse_time(start_time)
    end_dt = parse_time(end_time)
    if start_dt is None or end_dt is None:
        return fail(
            f"时间格式无法解析：start_time={start_time!r}、end_time={end_time!r}，"
            "期望 YYYY-MM-DD HH:mm:ss。",
            conflictType="invalid_param", retryable=False,
            actionHint=_ACTION_HINT["invalid_param"],
        )
    if end_dt <= start_dt:
        return fail(
            f"结束时间({end_time})不晚于开始时间({start_time})，时段倒置。",
            conflictType="invalid_param", retryable=False,
            actionHint=_ACTION_HINT["invalid_param"],
        )

    # ---- 3. 时间回写规范化：消掉「Tool 说合法、service 说非法」----
    # 上面两个校验用的是**模型给的原文**（失败提示要照原样回显，模型才知道自己发了什么），
    # 到了这一行必须换成 service 唯一保证接受的格式。见 `_SERVICE_TIME_FORMAT`。
    start_time = start_dt.strftime(_SERVICE_TIME_FORMAT)
    end_time = end_dt.strftime(_SERVICE_TIME_FORMAT)

    # ---- 4. 调模块 3 的 service。Tool 不碰库、不管事务边界 ----
    # `agent_trace` 传 None：本 Tool 被调用时本次 Agent 运行还没结束，trace 注定残缺。
    # 按 2026-09-27 与蔡玉礼对齐的时序 (a)，落 None，由路由在 Agent 跑完后调
    # `update_agent_trace` 补一次 UPDATE。`None` 的语义是「尚未生成」，不是「生成了一半」。
    result = await create_order(
        user_id=user_id,
        space_id=space_id,
        start_time=start_time,
        end_time=end_time,
        device_ids=list(device_ids or []),
        agent_request=get_raw_request(),
        agent_trace=None,
        order_status=1,  # 1待确认：needConfirm=true，用户确认后才转 2
    )

    if result.get("ok"):
        order_id = result.get("orderId")
        # `orderId` 随返回值走，不写 ContextVar：API 层要拿它在 Agent 跑完后补写
        # agent_trace（时序方案 (a)），而 Tool 里的 ContextVar 写入跨不过
        # `asyncio.gather` 的 context 拷贝（见 `app/agent/context.py`）。
        # 提取点在 `app/agent/chains/builder.py`——它扫 ToolMessage 拿这个字段。
        #
        # 桩期 `orderId` 恒为 None（`create_order` 不落库），API 层据此跳过补写，
        # 不会去 UPDATE 一个不存在的订单。
        return {
            "ok": True,
            "orderId": order_id,
            "reason": result.get("reason"),
            "stub": result.get("stub", False),
        }

    conflict_type = result.get("conflictType")
    return fail(
        result.get("reason") or "锁定失败，原因未提供。",
        conflictType=conflict_type,
        conflictDetail=result.get("conflictDetail"),
        retryable=conflict_type in _RETRYABLE,
        actionHint=_ACTION_HINT.get(conflict_type),
    )
