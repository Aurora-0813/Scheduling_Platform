"""场地查询 service（模块 5）—— 检索**该时段真正订得上的**场地。

来源约定：流程文档阶段 3 §3.1「资源查询（模块 5）」｜负责人：杨睿坤。

本文件曾是阶段 3 的桩：只筛 `status / space_type / capacity`，`start_time` /
`end_time` **只收不用**，于是已订出去的场地照样被判为「可选」，Agent 会把它排进
方案，直到 `lock_resources` 才被拒 —— 用户看到的是「推荐了一个订不上的场地」。
（阶段 3 完成文档第 6 节第 1 条，实测 `10-15 13:00~17:00` 已占的 space 4 仍返回。）

现已补上两条业务规则，即该条遗留问题的两个缺口：

  1. **时段重叠排除** —— 排除在该时段已有占位订单的场地。口径与模块 3 的
     `create_order` 一致，取同一个 `OCCUPYING_STATUS`（两处定义由护栏用例钉住，
     见 `app/models/reservation.py` 该常量的说明）：
     `order_status IN OCCUPYING_STATUS` 且 `existing.start < end` 且
     `existing.end > start`（半开区间，首尾相接不算重叠）。
  2. **开放时段过滤** —— 排除 `open_start_time` / `open_end_time` 盖不住该时段的
     场地（`NULL` 视为不限）。

签名保持主文档 §5.3 模块 4 的冻结形状，未改一字：
    async def query_spaces(capacity: int, space_type: int, start_time: str, end_time: str) -> dict

**不过滤可用性之外的东西**：本函数只回答「哪些场地这个时段能订」，不回答
「订得上要多少钱」之类的取舍 —— 那些留给 Agent 权衡（场景 A 的预算降级就靠它）。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.exceptions import ParamInvalidError
from app.models.reservation import OCCUPYING_STATUS, ReserveOrder
from app.models.resource import SpaceResource
from app.state_machine import OrderStatus

__all__ = [
    "query_spaces",
    "list_available_spaces",
    "list_space_bookings",
    "space_occupancy",
    "TIME_FORMATS",
]

#: 允许的时间格式。**必须与 `app/agent/tools/_common.py` 的 `TIME_FORMATS` 一致**。
#:
#: 原因：Tool 层用那一份做校验，但**存的是原始字符串**——`query_spaces` Tool
#: 校验通过后把 `start_time` / `end_time` 原样透传给本函数（不做归一化）。
#: 两边格式表若不一致，模型给 "2026-09-30 14:00" 时会出现「Tool 判合法、
#: 到这里解析失败」，而失败点在 Agent 循环内部，排查成本很高。
#:
#: 为什么不直接 import 那一份：`_common.py` 位于 `app.agent.tools`，而 service
#: 反向依赖 agent 层是层次倒置（agent 依赖 services，不是反过来）。故独立声明，
#: 由 `tests/test_space_service.py::test_time_formats_match_tool_layer` 断言两边
#: 相等 —— 靠测试防漂移，不靠注释。
TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


def _to_dict(row: SpaceResource) -> dict:
    """ORM 行 → 传输结构。字段名用 camelCase，与主文档 6.2 及 TraceStep.observation 一致。"""
    return {
        "id": row.id,
        "spaceName": row.space_name,
        "spaceType": row.space_type,
        "capacity": row.capacity,
        "location": row.location,
        "budget": float(row.budget) if row.budget is not None else None,
        "openStartTime": row.open_start_time.strftime("%H:%M:%S") if row.open_start_time else None,
        "openEndTime": row.open_end_time.strftime("%H:%M:%S") if row.open_end_time else None,
        "status": row.status,
    }


def _parse_time(raw: str, *, field: str) -> datetime:
    """按 `TIME_FORMATS` 逐个试，解不出抛 `ParamInvalidError`。

    与 Tool 层的 `parse_time` 有意不同：那里解不出返回 `None`，因为 Tool 抛异常
    会被 LangGraph 包成 ToolMessage 里的 traceback，模型既不能自纠又污染 trace。
    本层相反——能走到这里的输入已被 Tool 校验过，**解析失败属调用方违约**，
    响亮地失败好过静默返回空集（空集会被误读成「这个时段没有场地」）。
    """
    text = raw.strip().replace("/", "-") if isinstance(raw, str) else raw
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except (TypeError, ValueError):
            continue
    raise ParamInvalidError(f"{field} 无法解析：{raw!r}，期望 YYYY-MM-DD HH:mm:ss。")


async def query_spaces(capacity: int, space_type: int, start_time: str, end_time: str) -> dict:
    """场地查询：按容量下限与类型检索**该时段可订**的场地。

    参数：
        capacity:   容量下限（人）。取「容纳人数 ≥ 该值」。
        space_type: 场地类型，**INT 字典**（主文档 6.3）：1会议室 2展厅 3多功能厅 4户外场地。
                    自然语言到数字的映射由 Prompt 层给出对照表（阶段 4 §3.2），此处不猜。
        start_time: 需求开始时间，`YYYY-MM-DD HH:mm:ss`（本层同时接受
                    `_common.TIME_FORMATS` 的另外三种写法，见 `TIME_FORMATS`）。
        end_time:   需求结束时间，同格式。

    返回：
        {"count": int, "spaces": [ {id, spaceName, spaceType, capacity,
                                   location, budget, openStartTime, openEndTime, status} ]}

        `spaces` 已保证三条：该时段**没有占位订单**、**在开放时段内**、
        容量与类型达标。订不到就是空集，不会返回「订不上的场地」。

    抛异常：
        `ParamInvalidError` —— 时间无法解析，或 `end_time <= start_time`。
        参数合法性本属 Tool 层职责（`query_spaces` Tool 已先行校验并返回
        `ok=False`）；本层再挡一道，是给**绕过 Tool 直接调用 service 的入口**
        （如阶段 7 用例）留的防线。
    """
    start_dt = _parse_time(start_time, field="start_time")
    end_dt = _parse_time(end_time, field="end_time")
    if end_dt <= start_dt:
        raise ParamInvalidError(f"结束时间({end_time})不晚于开始时间({start_time})，时段倒置。")

    # 跨日请求：本系统的场地**按日开放**，`open_start_time` / `open_end_time` 是
    # TIME（不含日期），无法表达跨日区间 —— 若照搬下面两个时刻比较，
    # 「10-15 20:00 ~ 10-16 10:00」这种请求反而会被判为落在开放时段内。
    # 故这里显式按「无场地满足」返回空集：与「该时段没有可用场地」走同一条
    # Agent 路径（模型据空集改期或改问用户），不抛异常打断链路。
    if start_dt.date() != end_dt.date():
        return {"count": 0, "spaces": []}

    # 该时段已有占位订单的场地 id。半开区间：`existing.start < end` 且
    # `existing.end > start`，故「上一场 11:00 结束、下一场 11:00 开始」不算重叠。
    # 口径与 create_order 同取 OCCUPYING_STATUS，见 app/models/reservation.py。
    occupied_space_ids = select(ReserveOrder.space_id).where(
        ReserveOrder.order_status.in_(OCCUPYING_STATUS),
        ReserveOrder.start_time < end_dt,
        ReserveOrder.end_time > start_dt,
    )

    stmt = (
        select(SpaceResource)
        .where(
            SpaceResource.status == 1,
            SpaceResource.space_type == space_type,
            SpaceResource.capacity >= capacity,
            # `space_id` 非空，故 NOT IN 子查询不会踩 NULL 的三值逻辑陷阱
            SpaceResource.id.notin_(occupied_space_ids),
            # 开放时段：NULL 视为不限（种子数据 8 个场地均为非空同日区间）
            or_(
                SpaceResource.open_start_time.is_(None),
                SpaceResource.open_start_time <= start_dt.time(),
            ),
            or_(
                SpaceResource.open_end_time.is_(None),
                SpaceResource.open_end_time >= end_dt.time(),
            ),
        )
        .order_by(SpaceResource.capacity)
    )
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(stmt)).scalars().all()
    return {"count": len(rows), "spaces": [_to_dict(r) for r in rows]}


async def list_available_spaces() -> dict:
    """列出**全部可用场地**（`status=1`），不做类型/容量/时段过滤。

    用途：单次调用快速模式（`app/agent/chains/fast.py`）需要把「全部候选」
    一次性交给模型，由模型在候选里做选择题 —— 省掉多轮「模型决定查什么」的往返。

    过滤只保留「能用」的：`status=1`。容量/类型/时段**有意不过滤** ——
    那正是要交给模型判断的部分；候选规模小时（本项目 9 个场地）无压力，
    规模上千时应改回 `query_spaces` 预筛。
    """
    stmt = (
        select(SpaceResource)
        .where(SpaceResource.status == 1)
        .order_by(SpaceResource.capacity)
    )
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(stmt)).scalars().all()
    return {"count": len(rows), "spaces": [_to_dict(r) for r in rows]}


async def space_occupancy(db: AsyncSession, *, now: datetime | None = None) -> dict[int, str]:
    """
    每个场地**当前**的占用状态：`{space_id: "使用中" | "已被预约"}`。

    **不含空闲的场地** —— 查不到 key 就是空闲（"空闲" 由调用方补，见
    `app/api/resources.py::_space_out`）。

    口径（按时间推导，**不写任何列**）：
        · `使用中`    **已确认**（状态 2）的单，其 `[start, end)` 包含当前时刻
        · `已被预约`  没有正在使用的单，但存在一条**本周内**尚未开始、或在用但
                      **待确认**（状态 1）的单
        两者都不满足 → 空闲（本函数不返回）

    ⚠️ 「使用中」只认**已确认**（2026-10-06 修）
    ------------------------------------------
    初版把「待确认（1）」也算进「使用中」，于是场地 7 因为一条 11:00~13:00 的
    **待确认**单，在 11:13 显示成「使用中」—— 用户直接报「它没有使用，显示使用中」。

    业务上确实说不通，而且本仓库**自己的界面文案**就写着
    （`frontend/src/views/AgentWorkbench.vue`）：
        「确认后才会进入『已确认』，**占用才算真正落实**。」
    所以「正在用但还没确认」的单落到「已被预约」，而不是「使用中」。

    注意：**待确认仍然算「已被预约」**，因为 `OCCUPYING_STATUS`（1 与 2）都占住
    时段 —— 下单判重与 `query_spaces` 都不把它当空闲。区别只在**文案强度**：
    「已被预约」＝时段被占住；「使用中」＝已确认、正在用。

    ⚠️ 为什么**不**改 `space_resource.status`
    ----------------------------------------
    那一列是「可用 / 停用」（`comment="可用状态：1可用 0停用"`），
    且被 5 处查询当作「能不能借」的判据（`space_service.query_spaces`、
    `image_service`、`dashboard_service`、`rules/idle` 等）。
    若预约时把它改成 0，那个场地会**从所有可用场地里消失**，
    而订单结束后又没有人负责改回来 —— 这正是本仓库踩过两次的
    「单向状态机」坑（设备报损那次就是）。
    所以占用状态**只推导、不落库**：它是 (场地, 时刻) 的函数，
    与 `available_count`/剩余量同一条设计原则。

    口径（按时间推导，**不写任何列**）：
        · `使用中`    存在一条活跃单，其 `[start, end)` **包含当前时刻**
        · `已被预约`  没有正在使用的单，但存在一条活跃单落在**本周内**且尚未开始
        两者都不满足 → 空闲（本函数不返回）

    为什么限制在「本周」（2026-10-06 业务口径）
    -----------------------------------------
    「已被预约」只反映**近期的占用**，不是「历史上被订过」。
    下周及以后的单不进这一列 —— 提前两周的预约就让场地长期显示「已被预约」，
    会让这一列失去区分度（场地页几乎全是「已被预约」）。
    想看更远的占用，用 `list_space_bookings`（按天查明细）。

    周界口径：以**周一为一周开始**、周日结束，与主文档
    「相对时间的换算规则」一致（那儿也是「这一周从星期一开始」）。
    本周一 = 今天 − `weekday()` 天；本周日 = 本周一 + 6 天（用日期比较，不看时刻）。

    另：「使用中」在订单状态机里**没有对应取值**（只有 1 待确认 / 2 已确认 /
    3 已取消 / 4 已完成），只能按时间算。不要为了这个显示去加第 5 个状态 ——
    那会波及列表、文案与全部状态机用例。

    参数：
        now : datetime | None  当前时刻，留出口子便于测试。默认取系统时间
                                （与 `order_service` 的判重口径同为本地时间）。
    """
    anchor = now or datetime.now()
    # 本周一 00:00 ~ 本周日 23:59:59（用日期比较，不看时刻）
    week_start = (anchor - timedelta(days=anchor.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_end = week_start + timedelta(days=7)

    # 只取「还在占用中」的活跃单，两个下界缺一不可：
    #   · `end_time > anchor`      排掉已经结束的（它们仍留在活跃集合里没人推终态）
    #   · `start_time < week_end`  排掉下周及以后的（本周口径，见 docstring）
    # SQL 层就排掉，既少读行，也让谓词吃得上 idx_status_start 的最左前缀
    # （order_status 等值 + start_time 范围）。
    #
    # ⚠️ 必须连 `order_status` 一起 select 回来：判定要区分「已确认(2)」与
    #    「待确认(1)」，少了这一列就只能猜。
    rows = (
        await db.execute(
            select(
                ReserveOrder.space_id,
                ReserveOrder.order_status,
                ReserveOrder.start_time,
                ReserveOrder.end_time,
            ).where(
                ReserveOrder.order_status.in_(OCCUPYING_STATUS),
                ReserveOrder.space_id.is_not(None),
                ReserveOrder.end_time > anchor,
                ReserveOrder.start_time < week_end,
            )
        )
    ).all()

    result: dict[int, str] = {}
    for space_id, order_status, start, end in rows:
        verdict = _judge_space(order_status, start, end, anchor=anchor, week_end=week_end)
        if verdict is None:
            continue
        in_use = start <= anchor < end
        # 「使用中」优先级最高：同一场地若既有正在用的已确认单、又有别的单，
        # 不能被后面的「已被预约」覆盖。
        if in_use and order_status == OrderStatus.CONFIRMED:
            result[space_id] = verdict
        else:
            result.setdefault(space_id, verdict)
    return result


def _judge_space(
    order_status: int, start: datetime, end: datetime, *, anchor: datetime, week_end: datetime
) -> str | None:
    """
    一条订单对「它占用的场地此刻该显示什么」的判定。**None = 这条单不该影响显示**。

    抽成独立函数是为了**可归因**：`space_occupancy` 只返回 `{场地: 文案}`，
    看到「使用中」时无从判断是哪条单导致的。有了本函数，可以直接拿一条单
    （甚至一条**排除掉候选单之后**的集合）来问「它会不会让它显示使用中」——
    排查「这个场地为什么显示使用中」时就是靠这个把责任定位到具体单号。

    判定口径（详见 `space_occupancy` 的 docstring）：
        · 已确认 + 在时段内          → 使用中
        · 尚未开始（本周内）          → 已被预约
        · 在时段内但**未确认**        → 已被预约（占住了，但没落实）
        · 已结束                     → None（不该影响显示）
    """
    if order_status not in OCCUPYING_STATUS:
        return None
    in_use = start <= anchor < end
    if in_use and order_status == OrderStatus.CONFIRMED:
        return "使用中"
    if start > anchor or in_use:
        return "已被预约"
    # 已结束（`end_time <= anchor`）：在线库里常见「单子做完了没人推终态」，
    # 不能让它继续占着显示。
    return None


async def list_space_bookings(
    db: AsyncSession,
    space_id: int,
    days: int = 7,
    *,
    start: date | None = None,
) -> list[ReserveOrder]:
    """
    某场地在**未来 N 天内已被占用**的预约明细（含待确认与已确认）。

    与 `query_spaces` 的关系：
        `query_spaces` 回答「这个时段**哪些场地空着**」（剔除占用后返回可用场地）；
        本函数回答反过来的问题 ——「**这个场地**哪些时段被占了」。
        两者共用同一个占用口径 `OCCUPYING_STATUS`（见 app/models/reservation.py）：
        只有状态 1（待确认）与 2（已确认）算占用；已取消 / 已完成都会释放时段。

    参数：
        db       : AsyncSession  会话。由调用方（HTTP 层）持有 ——
                   本函数是**端点用的查询**，不进 Agent Tool，故不像
                   `query_spaces` 那样自管会话；事务边界交给 FastAPI 的 `get_db`。
        space_id : int           场地 ID。调用方需先确认场地存在。
        days     : int           查询未来多少天（从 start 当天 00:00 起算）。
        start    : date | None   起始日期，默认今天。留出口子便于测试与「查历史」。

    返回：
        list[ReserveOrder]，按 `start_time` 升序。**只返回与区间有重叠的订单**，
        跨天占用会原样返回（如 20:00~次日 02:00），由展示层决定怎么裁剪。

    区间是左闭右开的：`existing.start < range_end` 且 `existing.end > range_start`，
    因此「上一场 11:00 结束、下一场 11:00 开始」不算重叠 —— 与 `create_order`
    的判重规则一致，不会出现「接口说占了、下单却说没占」这种自相矛盾。
    """
    base = start or date.today()
    range_start = datetime.combine(base, time.min)
    range_end = range_start + timedelta(days=days)

    stmt = (
        select(ReserveOrder)
        .where(
            ReserveOrder.space_id == space_id,
            ReserveOrder.order_status.in_(OCCUPYING_STATUS),
            ReserveOrder.start_time < range_end,
            ReserveOrder.end_time > range_start,
        )
        .order_by(ReserveOrder.start_time)
    )
    return list((await db.execute(stmt)).scalars().all())
