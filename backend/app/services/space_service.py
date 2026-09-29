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

__all__ = ["query_spaces", "list_space_bookings", "TIME_FORMATS"]

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


async def list_space_bookings(
    db: AsyncSession,
    space_id: int,
    days: int = 7,
    *,
    start: date | None = None,
) -> list[ReserveOrder]:
    """某场地在**未来 N 天内已被占用**的预约明细（含待确认与已确认）。

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
