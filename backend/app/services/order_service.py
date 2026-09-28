"""预约订单服务层：创建预约（§5.5 事务六步）。

## 这个文件为什么存在

`§4.3`（模块间调用规范）、`§7.4`（AI 代码规范）、`§9.3`（AI 安全）三条指向同一件事：
Agent 只能通过 Tool 调用 **`services/` 层的异步函数**访问业务数据，Tool 内禁止使用
`AsyncSession`、禁止注册为 HTTP 端点。所以「创建预约」必须有一个**不依赖 HTTP、
不依赖调用方会话**的实现。本模块就是那个实现；`app/api/orders.py` 的路由只是它的薄壳。

在此之前，这段逻辑是 `app/api/orders.py` 里的路由层私有函数 `_create_order(db, ...)`：
入参是 HTTP DTO、失败抛 `HTTPException`、没有 `FOR UPDATE` 也没有显式事务边界。
三处都不满足上面的规范，且并发下第 3 步查重与第 5 步 INSERT 之间存在空窗。

## 冻结契约（核心调度 Agent 的 `lock_resources` Tool 直接调用，签名不得更改）

    async def create_order(*, user_id, space_id, start_time, end_time,
                           device_ids=None, agent_request=None,
                           agent_trace=None, order_status=1) -> dict

五条一起冻结，改任何一条都是破坏性变更：

1. **函数名与模块路径**：`app.services.order_service.create_order`
2. **参数名与顺序**：全部 keyword-only（位置传参一律拒绝，避免日后加参数时静默错位）
3. **签名里没有 `db`**：Tool 拿不到 `AsyncSession`（`§7.4`），会话由本函数自管；
   事务边界也由本函数自管——这正是 `§5.5` 六步原子性的落点。调用方**无法**
   在六步之间插入一次 commit，也就无法把锁提前放掉。
4. **返回结构**：`{ok, orderId, reason, conflictType, conflictDetail}`
5. **业务性失败不抛异常**（`§5.5` 的「ROLLBACK 并返回友好提示」）：见下

### 返回值

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ok` | bool | 是否创建成功 |
| `orderId` | int \\| None | 成功时为新订单 ID，失败为 None |
| `reason` | str | 面向用户的中文原因，可直接进 trace / 前端提示 |
| `conflictType` | str \\| None | 失败归类：`invalid_param` / `not_found` / `time_conflict` / `device_conflict` |
| `conflictDetail` | dict \\| None | 结构化冲突详情，供前端（屏 3）展示；无详情时为 None |

`conflictDetail` 的形状随 `conflictType` 而定：

    invalid_param   -> None（原因写在 reason 里）
    not_found       -> {"target": "space"|"user"|"device", ...对应的 ID}
    time_conflict   -> {"conflicts": [{"orderId", "startTime", "endTime"}, ...]}
    device_conflict -> {"conflicts": [{"orderId", "deviceIds", "startTime", "endTime"}, ...]}
                       或 {"conflicts": [{"deviceId", "reason": "status"|"exhausted"}]}
                       （设备本身不可用，与既有订单无关）

> `device_conflict` 的**判据**在 2026-09-28 由「查到重叠就拒」改成**计数比较**
> （`重叠单数 >= available_count` 才拒，见 `_device_conflicts`）。**形状与字段集
> 未变** —— `docs/api.md` 里 `create_order` 的契约冻结了上面这张表，改形状要走
> §5.3；变的只是列出来的单**都落在已约满的那几台设备上**。

`not_found` 与 `device_conflict` 的分界是「东西不存在」还是「东西被占/不能用」——
前者对 HTTP 是 404，后者是 409，归错类会把状态码整体带偏。

### 与 `lock_resources` 的对应

Tool 签名 `lock_resources(space_id, device_ids, start_time, end_time)`（`§5.3` 模块 4）
比本函数少一个 `user_id`：身份一律从 JWT 解析（`§5.1`），由 Agent 运行上下文补入。
其余参数一对一，`order_status` 由 Tool 传 `needConfirm` 推出的取值（默认 1 待确认）。

## 补缺：`update_agent_trace`

上面五项签名**一项都没动**。Agent 的思考链路是**跑完之后**才有的：落单那一刻还拿不到，
所以链路只能分两步写——`create_order` 先落 `agent_trace=None`，Agent 跑完由路由调
`update_agent_trace` 补一次 UPDATE。

为什么创建时不落「残缺 trace」：残缺 trace 在库里与完整 trace 无法区分，前端会当成完整
链路渲染，而 TC-26 / TC-30 验收的恰恰是「溯源完整」。`None` 的语义干净——**尚未生成**，
不是**生成了一半**。事后一次覆盖是安全的，因为不存在中间态。

这是**补缺，不是改契约**：冻的是已列的五项，补的是缺的那个函数。

## 异常边界

只有**业务性失败**走结构化返回。基础设施异常（连不上库、连接断开等）仍会抛出，
由 `core/exceptions.py` 的统一异常处理器兜成 500 —— 那是故障，不是「方案不可行」，
把它伪装成 `ok: False` 会让 Agent 把基础设施故障讲成业务建议。
"""
from collections import Counter

from sqlalchemy import select

from ..core.database import AsyncSessionLocal
from ..core.utils import format_time, parse_time
from ..models import (
    ACTIVE_ORDER_STATUSES,
    DeviceResource,
    ReserveOrder,
    SpaceResource,
    SysUser,
)
from ..state_machine import OrderStatus

__all__ = [
    "create_order",
    "update_agent_trace",
    "CONFLICT_TIME",
    "CONFLICT_DEVICE_MISSING",
    "CONFLICT_DEVICE_UNAVAILABLE",
    "CONFLICT_DEVICE_SHORTAGE",
    "CONFLICT_INVALID_TIME",
]

#: `§6.3` 表 6：agent_request VARCHAR(1024)。超长截断而不是报错——需求文本是模型
#: 生成的，因长度丢一次预约比截断更糟。
_AGENT_REQUEST_MAX = 1024

#: 创建时允许的订单状态：只有状态机的两个入口态（`§6.3` 表 6）。
#: 3/4 是流转出来的结果态，创建即完成/取消都是错误输入。
_ALLOWED_CREATE_STATUS = (OrderStatus.PENDING.value, OrderStatus.CONFIRMED.value)

# ==========================================================================
# 返回体 `conflictType` 的取值（模块 4 的 Tool 层与用例直接依赖，**不得删除**）
# ==========================================================================
# 2026-09-27 与模块 4 对齐（依据 docs/spec/contract-alignment.md 第 3 条，出自 docs/api.md §7.2）：
#   1. 命名是 **snake_case**，不是 SCREAMING_SNAKE；
#   2. 设备类的两种情形**不再拆成两个取值**，统一为 `device_conflict`，
#      靠 `conflictDetail.conflicts[].reason` 区分「设备停用」(`status`) 与
#      「数量不足」(`exhausted`)。
#
# 名字保留在 service 层是为了让「取值只有一处定义」这条约定成立：
# `app/agent/tools/lock_resources.py` 的可重试集合与 `tests/test_agent_tools.py`、
# `tests/test_agent_concurrency.py` 都从这里取，不要在实现里另写字面量。
CONFLICT_TIME = "time_conflict"                  # 场地时段冲突
CONFLICT_DEVICE_MISSING = "not_found"            # 设备 ID 不存在（→ HTTP 404）
CONFLICT_DEVICE_UNAVAILABLE = "device_conflict"  # 设备非完好状态（reason=status）
CONFLICT_DEVICE_SHORTAGE = "device_conflict"     # 设备库存不足（reason=exhausted）
CONFLICT_INVALID_TIME = "invalid_param"          # 起止时间本身非法


def _as_int(value) -> int | None:
    """把模型可能传成字符串的数值安全转成 int；转不了返回 None。

    Agent 的 Tool 入参是模型生成的 JSON，`"space_id": "101"` 完全可能。
    `§9.3` 要求对模型输出做业务边界校验，这里就是那道边界。
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class _Reject(Exception):
    """业务性拒绝（`§5.5` 第 3、4 步校验失败）。

    用异常只是为了触发 `begin()` 上下文的 ROLLBACK —— 它**不会**逃出本模块，
    在 `create_order` 内被翻译成结构化返回值。
    """

    def __init__(self, conflict_type: str, reason: str, detail: dict | None = None):
        super().__init__(reason)
        self.conflict_type = conflict_type
        self.reason = reason
        self.detail = detail


def _lock_space_stmt(space_id: int):
    """`§5.5` 第 2 步的语句：对目标场地行加锁。

    单独抽成函数只为让「锁有没有被写丢」可被机械验证 —— 单测跑在 SQLite 上，
    其方言会把 `FOR UPDATE` **编译掉**（`tests/module3/test_order_service.py`
    里有一条断言把这个差异钉死）。少了那条断言，哪天有人删掉 `with_for_update()`
    整套路还是会全绿，而云库上的并发语义已经没了。
    """
    return (
        select(SpaceResource).where(SpaceResource.id == space_id).with_for_update()
    )


def _fail(conflict_type: str, reason: str, detail: dict | None = None) -> dict:
    """失败结果（字段集与成功结果一致，调用方无需分支取值）。"""
    return {
        "ok": False,
        "orderId": None,
        "reason": reason,
        "conflictType": conflict_type,
        "conflictDetail": detail,
    }


async def _time_conflicts(db, space_id: int, start, end) -> list[dict]:
    """第 3 步：该场地在目标时段的重叠订单（占用口径见 `ACTIVE_ORDER_STATUSES`）。"""
    result = await db.execute(
        select(
            ReserveOrder.id, ReserveOrder.start_time, ReserveOrder.end_time
        )
        .where(
            ReserveOrder.space_id == space_id,
            ReserveOrder.order_status.in_(ACTIVE_ORDER_STATUSES),
            # 重叠判定：半开区间，首尾相接（10:00 结束 / 10:00 开始）不算冲突
            ReserveOrder.end_time > start,
            ReserveOrder.start_time < end,
        )
        .order_by(ReserveOrder.start_time)
    )
    return [
        {
            "orderId": r.id,
            "startTime": format_time(r.start_time),
            "endTime": format_time(r.end_time),
        }
        for r in result.all()
    ]


def _hit_device_ids(raw, wanted: set[int]) -> list[int]:
    """取该订单里与 `wanted` 相交的设备 ID（容错：JSON 列里混入非整数则跳过）。"""
    hit = set()
    for item in raw or []:
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if value in wanted:
            hit.add(value)
    return sorted(hit)


async def _device_conflicts(
    db, device_ids: list[int], caps: dict[int, int], start, end
) -> list[dict]:
    """第 4 步的时间维度部分：这些设备在同时段是否已被**约满**。

    `§6.3` 没有「设备占用」表，设备的时段占用只存在 `reserve_order.device_ids`
    （JSON 列）里，所以只能先捞重叠时段的订单、再在 Python 里按设备计数；`§6.6`
    的 10 个 `idx_*` 里也没有设备维度的索引，这一步没有可用索引。数据量上来后
    需要集成组给出正式口径（占用表 / 生成列 / 多值索引），当前实现是**尽力而为**
    的正确性，不做性能承诺。

    **判据是计数比较，不是「查到重叠就拒」**：`device_resource.available_count`
    是**可用上限**（不是「还剩几台」），同一台设备在同时段允许多单共存，只要总数
    没到上限。剩余量**用时推导**：

        某设备在某时段的剩余量 = available_count − 该时段重叠单数

    所以本函数不写任何列，`§5.5` 六步既没有扣减、也没有第 7 步回补 —— 订单一旦
    离开 `ACTIVE_ORDER_STATUSES`（取消 / 完成），下一单算出来的剩余量自然就回来，
    **回补不需要代码**。

    参数：
        caps: `{device_id: available_count}`，由 `_check_devices` 从设备行读出。
            取不到时按 0 处理（= 约满），方向上是**保守拒绝**而不是静默放行。

    返回：`docs/api.md` 里 `create_order` 冻结的形状（一单一条）。只列**碰到已约满
    设备**的那些单 —— 不过滤的话，「A 满了」会把只用到空闲 B 的单也一并报出来。
    """
    wanted = set(device_ids)
    result = await db.execute(
        select(
            ReserveOrder.id,
            ReserveOrder.start_time,
            ReserveOrder.end_time,
            ReserveOrder.device_ids,
        ).where(
            ReserveOrder.order_status.in_(ACTIVE_ORDER_STATUSES),
            ReserveOrder.end_time > start,
            ReserveOrder.start_time < end,
        )
    )
    rows = result.all()

    used: Counter[int] = Counter()
    for row in rows:
        for did in _hit_device_ids(row.device_ids, wanted):
            used[did] += 1      # 一单里同一台设备只算一次（`_hit_device_ids` 去重）

    full = {did for did in wanted if used[did] >= caps.get(did, 0)}
    if not full:
        return []

    conflicts = []
    for row in rows:
        busy = sorted(set(_hit_device_ids(row.device_ids, wanted)) & full)
        if busy:
            conflicts.append(
                {
                    "orderId": row.id,
                    "deviceIds": busy,
                    "startTime": format_time(row.start_time),
                    "endTime": format_time(row.end_time),
                }
            )
    return conflicts


async def _check_devices(db, device_ids: list[int], start, end) -> None:
    """第 4 步：校验设备可用性。失败抛 `_Reject`。

    四查：存在（`not_found`）→ 状态完好 → 还有可用上限 → 时段未被约满
    （后三者是 `device_conflict`，时间维度的检查见 `_device_conflicts`）。

    注意 `available_count` **只读不写** —— 这不是「暂时不扣」而是**口径本身**：
    它是**可用上限**（`total_count` 是物理台账数，留出备用机），「还剩几台」是
    `available_count − 该时段重叠单数`，属于**用时推导**。写时扣减会让一个不带
    时间维度的整数列去记「(设备, 时段)」的二维事实，必然串台：周一借走一台会
    把周二的名额一起吃掉，且 `available_count` 单调递减、没有任何自然事件能把
    它救回来。因此 `§5.5` 六步不加第 7 步「回补库存」，取消/完成靠
    `ACTIVE_ORDER_STATUSES` 自动生效。口径判据与 AGENT-C-01/02 的对照表见
    `docs/available_count口径判据.md`。
    """
    if not device_ids:
        return

    result = await db.execute(
        select(DeviceResource).where(DeviceResource.id.in_(device_ids))
    )
    devices = {d.id: d for d in result.scalars().all()}

    for did in device_ids:
        device = devices.get(did)
        if device is None:
            # 归类为 not_found 而不是 device_conflict：这是「参数指向的东西不存在」，
            # 不是「资源被占用」。HTTP 契约（§5.3 模块3）里设备不存在是 404，
            # 归错类会把这个 404 变成 409。
            raise _Reject(
                CONFLICT_DEVICE_MISSING,
                f"设备 {did} 不存在",
                {"target": "device", "deviceIds": [did]},
            )
        if device.device_status != 1:  # 1完好 2损坏 3缺失配件（§6.3 表5）
            raise _Reject(
                CONFLICT_DEVICE_UNAVAILABLE,
                f"设备 {device.device_name} 状态异常，暂不可用",
                {"conflicts": [{"deviceId": did, "reason": "status"}]},
            )
        if (device.available_count or 0) <= 0:
            raise _Reject(
                CONFLICT_DEVICE_SHORTAGE,
                f"设备 {device.device_name} 已无可用库存",
                {"conflicts": [{"deviceId": did, "reason": "exhausted"}]},
            )

    caps = {did: (devices[did].available_count or 0) for did in device_ids}
    busy = await _device_conflicts(db, device_ids, caps, start, end)
    if busy:
        # 「已约满」而不是「已被占用」：容量 > 1 时，重叠单数没到上限本来就不算冲突，
        # 走到这里的都是**这台设备的名额用光了**，沿用旧文案会让人以为「只要没人用就行」。
        raise _Reject(CONFLICT_DEVICE_SHORTAGE, "该时段设备已约满", {"conflicts": busy})


async def create_order(
    *,
    user_id: int,
    space_id: int,
    start_time: str,
    end_time: str,
    device_ids: list[int] | None = None,
    agent_request: str | None = None,
    agent_trace: list | None = None,
    order_status: int = OrderStatus.PENDING.value,
) -> dict:
    """在**一个事务**内完成 `§5.5` 的资源锁定与落单。

    参数：
        user_id: 预约人；由调用方从 JWT 解出后传入（`§5.1` 禁止从请求体取）
        space_id: 场地 ID
        start_time / end_time: `YYYY-MM-DD HH:mm:ss`（`§5.1` 时间格式统一）
        device_ids: 设备 ID 列表，无设备传 None 或 []
        agent_request: 用户原始需求，落 `reserve_order.agent_request`，超 1024 截断
        agent_trace: Agent 思考过程（TraceStep 对象数组），落 `reserve_order.agent_trace`
        order_status: 1待确认（默认）/ 2已确认；其余取值一律拒绝

    返回：见模块 docstring 的返回值表。业务性失败返回 `ok=False`，不抛异常。
    """
    # ---- 入参校验：不占 §5.5 六步，但同样不抛 —— Agent 的入参来自模型输出（§9.3）----
    user_id = _as_int(user_id)
    if user_id is None or user_id <= 0:
        # Agent 侧最容易漏的一环：JWT 解出的 user_id 忘了往下传。
        # 这里明确拒绝，而不是落 NULL 或抛异常。
        return _fail("invalid_param", "缺少 user_id：身份必须从 JWT 解析后传入（§5.1）")
    space_id = _as_int(space_id)
    if space_id is None:
        return _fail("invalid_param", "space_id 必须是整数")
    order_status = _as_int(order_status)
    if order_status not in _ALLOWED_CREATE_STATUS:
        return _fail(
            "invalid_param",
            f"order_status 只能为 1（待确认）或 2（已确认），收到 {order_status}",
        )

    if device_ids is None:
        device_ids = []
    if not isinstance(device_ids, (list, tuple)):
        return _fail("invalid_param", "device_ids 必须是整数数组")
    parsed_ids = [_as_int(d) for d in device_ids]
    if any(d is None for d in parsed_ids):
        return _fail("invalid_param", "device_ids 必须是整数数组")
    device_ids = parsed_ids
    if len(set(device_ids)) != len(device_ids):
        return _fail("invalid_param", "设备列表存在重复项")

    if agent_request is not None and not isinstance(agent_request, str):
        return _fail("invalid_param", "agent_request 必须是字符串")
    if agent_trace is not None and not isinstance(agent_trace, list):
        return _fail(
            "invalid_param",
            "agent_trace 必须是 TraceStep 对象数组（§5.3 模块4）",
        )

    try:
        start = parse_time(start_time)
        end = parse_time(end_time)
    except ValueError as exc:
        return _fail("invalid_param", str(exc))
    if start >= end:
        return _fail("invalid_param", "开始时间必须早于结束时间")

    async with AsyncSessionLocal() as db:
        # ===================== §5.5 事务六步（开发流程.md:435-441）=====================
        try:
            async with db.begin():                                      # 1. BEGIN
                # 2. SELECT ... FOR UPDATE 对目标场地行加锁
                #    （SQLite 方言会把 FOR UPDATE 编译掉，见 tests 走 aiosqlite；
                #      云库 mysql+asyncmy 下真实生效）
                locked = await db.execute(_lock_space_stmt(space_id))
                if locked.scalar_one_or_none() is None:
                    raise _Reject(
                        "not_found",
                        "场地不存在",
                        {"target": "space", "spaceId": space_id},
                    )

                # 预约人必须存在：云库上 reserve_order.user_id 是真外键
                # （docs/database.md），不先查会以 1452 炸成 500
                if await db.get(SysUser, user_id) is None:
                    raise _Reject(
                        "not_found",
                        "用户不存在",
                        {"target": "user", "userId": user_id},
                    )

                conflicts = await _time_conflicts(db, space_id, start, end)   # 3.
                if conflicts:
                    raise _Reject(
                        CONFLICT_TIME, "该时段已被占用", {"conflicts": conflicts}
                    )

                await _check_devices(db, device_ids, start, end)              # 4.

                # 5. 插入 reserve_order，写入 device_ids
                order = ReserveOrder(
                    user_id=user_id,
                    space_id=space_id,
                    device_ids=device_ids,
                    start_time=start,
                    end_time=end,
                    order_status=order_status,
                    agent_request=(
                        (agent_request or "").strip()[:_AGENT_REQUEST_MAX] or None
                    ),
                    agent_trace=agent_trace,
                )
                db.add(order)
                await db.flush()   # 取库侧自增 id；事务仍开着，未提交
                order_id = order.id
            # 6. COMMIT —— `begin()` 上下文正常退出即提交
        except _Reject as reject:
            # §5.5：第 3/4 步校验失败 → ROLLBACK（已由 begin() 上下文完成）
            # 并返回友好提示
            return _fail(reject.conflict_type, reject.reason, reject.detail)

    return {
        "ok": True,
        "orderId": order_id,
        "reason": "预约创建成功",
        "conflictType": None,
        "conflictDetail": None,
    }


async def update_agent_trace(
    *,
    order_id: int,
    user_id: int,
    agent_trace: list,
) -> dict:
    """补写 Agent 思考链路（`create_order` 之后由路由回调，见模块 docstring）。

    与 `create_order` 同规矩：keyword-only、签名**不含 `db`**（会话与事务边界都自管）、
    业务性失败返回 `ok=False` 而不抛异常。

    参数：
        order_id: 要补写的订单 ID
        user_id: 归属校验用，由调用方从 JWT 解出后传入（`§5.1`）。**必须进签名**——
            只凭 `order_id` 就能改任意订单的 `agent_trace`，等于把它变成可写公共字段。
        agent_trace: Agent 思考过程（TraceStep 对象数组），**整体覆盖**库中该列

    返回：字段集与 `create_order` **完全一致**，调用方一处取值逻辑两处通用。
    可重复调用（同一份 trace 补写两次仍返回 `ok=True`）。
    """
    order_id = _as_int(order_id)
    if order_id is None or order_id <= 0:
        return _fail("invalid_param", "order_id 必须是正整数")

    user_id = _as_int(user_id)
    if user_id is None or user_id <= 0:
        return _fail("invalid_param", "缺少 user_id：身份必须从 JWT 解析后传入（§5.1）")

    if not isinstance(agent_trace, list):
        return _fail(
            "invalid_param",
            "agent_trace 必须是 TraceStep 对象数组（§5.3 模块4）",
        )
    # 空数组拒绝：它在库里与 `NULL`（尚未生成）区分不开，写进去只会让前端把
    # 「没跑出东西」渲染成一条空链路。没有内容可补写时**不要调用本函数**。
    # 注意 `create_order` 允许空 list —— 那里 `None` 才是常态（补写链路的起点），
    # 显式传 `[]` 是合法输入；两处宽严不同是刻意的。
    if not agent_trace:
        return _fail(
            "invalid_param",
            "agent_trace 不能为空数组：空链路与「尚未生成」无法区分，没有内容时勿调用",
        )

    async with AsyncSessionLocal() as db:
        try:
            async with db.begin():
                # 刻意用「先 SELECT ... FOR UPDATE 再赋值」，而不是一条 UPDATE：
                # MySQL 的 affected_rows 默认只数**真正发生变化**的行，同一份 trace
                # 补写两次时第二条 UPDATE 返回 0，会被误判成 not_found。分成两步才能
                # 把「不存在 / 非本人」与「值没变」分开。（SQLite 方言把 FOR UPDATE
                # 编译掉，测试跑 aiosqlite 时锁不生效；云库 mysql+asyncmy 下真实生效。）
                result = await db.execute(
                    select(ReserveOrder)
                    .where(
                        ReserveOrder.id == order_id,
                        ReserveOrder.user_id == user_id,
                    )
                    .with_for_update()
                )
                order = result.scalar_one_or_none()
                if order is None:
                    # 不存在与非本人**同一处理、不区分原因**：区分了就等于承认「这单
                    # 存在，只是不是你的」，可据此枚举全库订单。与 api 层的
                    # `_get_owned_order`、`messages.py::read_message` 同一口径。
                    raise _Reject("not_found", "预约不存在")
                order.agent_trace = agent_trace
            # 上下文正常退出即 COMMIT
        except _Reject as reject:
            return _fail(reject.conflict_type, reject.reason, reject.detail)

    return {
        "ok": True,
        "orderId": order_id,
        "reason": "思考链路已补写",
        "conflictType": None,
        "conflictDetail": None,
    }
