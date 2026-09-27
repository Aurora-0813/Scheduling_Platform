"""订单创建与资源锁定 service —— **桩函数**（阶段 3 任务 3-2）。

来源约定：流程文档阶段 3 §3.1「订单创建 + 资源锁定（模块 3，含 5.5 事务）」｜负责人：蔡玉礼。

==============================================================================
签名已冻结（2026-09-27，蔡玉礼）
==============================================================================
    create_order(*, user_id, space_id, start_time, end_time,
                 device_ids=None, agent_request=None, agent_trace=None, order_status=1)
        -> {ok, orderId, reason, conflictType, conflictDetail}

**业务性失败不抛异常**，一律以 `ok=False` + `conflictType` 返回。

本桩返回体额外恒带 `"stub": True`——这是**桩期专有的第 6 个键**，故意偏离上面的冻结形状：
冻结形状描述的是真实实现，而桩必须能自证「这不是一次真实预约」（阶段 3 防假绿）。
真实实现替换进来时这个键随之消失；**任何断言 `stub` 的代码都是桩期临时代码，一并删除**。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.reservation import ReserveOrder
from app.models.resource import DeviceResource

__all__ = [
    "create_order",
    "CONFLICT_TIME",
    "CONFLICT_DEVICE_MISSING",
    "CONFLICT_DEVICE_UNAVAILABLE",
    "CONFLICT_DEVICE_SHORTAGE",
    "CONFLICT_INVALID_TIME",
]

#: `reserve_order.order_status` 中「占位」的状态（主文档 6.3 表 6）。
#: 1待确认、2已确认；3已取消与4已完成都不占位。
#:
#: ⚠️ 这里取 (1, 2) **比主文档 5.5 第 3 步更严**——5.5 原文写的是
#: 「该场地在目标时段是否存在**已确认**订单」，字面只覆盖 status=2。
#: 但 create_order 的 `order_status` 默认值是 1，若真实实现照 5.5 字面只查 status=2，
#: **Agent 落下的待确认订单就不占位**，并发下会被别人重复预约（模块 7 黄嵩的
#: 冲突监控也会漏报）。二者必须统一，见「待蔡玉礼确认」第 2 条。
OCCUPYING_STATUS = (1, 2)

#: 返回体 `conflictType` 的取值。
#:
#: ⚠️ **以下取值是我方暂定，不是约定。** 全仓唯一定义点就是这里；
#: 蔡玉礼的契约全文（`docs/api.md` 模块 3 小节）到手后，只改本处常量值，
#: 不要把这些字符串散落到 Tool 层或前端。
CONFLICT_TIME = "TIME_CONFLICT"                    # 场地时段冲突
CONFLICT_DEVICE_MISSING = "DEVICE_NOT_FOUND"       # 设备 ID 不存在
CONFLICT_DEVICE_UNAVAILABLE = "DEVICE_UNAVAILABLE"  # 设备非完好状态
CONFLICT_DEVICE_SHORTAGE = "DEVICE_INSUFFICIENT"   # 设备库存不足
CONFLICT_INVALID_TIME = "INVALID_TIME_RANGE"       # 起止时间本身非法

_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M")


def _parse_time(raw: str) -> datetime:
    """解析时间串。模型给的格式不保证唯一，逐个试。

    TODO(蔡玉礼): 若模块 3 对入参格式有强约定，这里应换成对应的单格式校验。
    """
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    raise ValueError(f"无法解析的时间格式：{raw!r}，期望 YYYY-MM-DD HH:mm:ss")


def _fail(conflict_type: str, reason: str, detail: object = None) -> dict:
    """业务性失败的统一返回。**不抛异常**（蔡玉礼冻结的契约要求）。"""
    return {
        "ok": False,
        "orderId": None,
        "reason": reason,
        "conflictType": conflict_type,
        "conflictDetail": detail,
        "stub": True,
    }


async def create_order(
    *,
    user_id: int,
    space_id: int,
    start_time: str,
    end_time: str,
    device_ids: list[int] | None = None,
    agent_request: str | None = None,
    agent_trace: dict | None = None,
    order_status: int = 1,
) -> dict:
    """[桩] 订单创建 + 资源锁定：校验场地时段冲突与设备可用性。

    TODO(蔡玉礼): 替换为模块 3 的真实实现，**替换时只换函数体，签名不动**。

    参数：
        user_id:     预约人 ID。**必填**——由 API 层从 JWT 解出，经 Agent 调用上下文
                     注入；禁止让模型去猜，也禁止从请求体取（主文档 5.1/9.1：从请求体
                     取则任何人都能替别人预约）。2026-09-27 蔡玉礼把本参数正式写进签名，
                     长期挂账的「未决 #1」就此闭环。
        space_id:    场地 ID。
        start_time:  开始时间，`YYYY-MM-DD HH:mm:ss`。
        end_time:    结束时间，同格式。
        device_ids:  设备 ID 列表，可为 None / 空列表。
        agent_request: 用户原始自然语言需求（主文档 6.3 `reserve_order.agent_request`）。
        agent_trace:    AI 思考过程（主文档 6.3 `reserve_order.agent_trace`）。
                        ⚠️ 见下方「待蔡玉礼确认」第 1 条——**本参数在锁定时刻拿不到完整值**。
        order_status:   落库状态，默认 1（待确认）。取值由调用方按「是否需要人工确认」决定。

    返回：
        {"ok": bool, "orderId": int|None, "reason": str,
         "conflictType": str|None, "conflictDetail": object|None}   ← 冻结形状
        外带桩期专有的 "stub": True（真实实现落地后消失）

    ══════════════════════════════════════════════════════════════════════
    待蔡玉礼确认（按硬度排序，均为签名之外的口径问题，不阻塞桩期）
    ══════════════════════════════════════════════════════════════════════
    **1. `agent_trace` 的落库时序——需要一个本签名里没有的 service 函数。**
       主文档 3.3 规定 `agent_trace` 由 LangGraph `messages` 里的 AIMessage / ToolMessage
       按序映射而来。而 `lock_resources` 被调用的那一刻，**本次 Agent 运行还没结束**，
       trace 注定是残缺的——完整 trace 只有在 `create_order` 返回之后才存在。
       所以 `agent_trace` 不可能在 INSERT 时就写全。可行解只有：
         (a) 本函数落 `agent_trace=None`，路由在 Agent 跑完后补一次 UPDATE；
         (b) 本函数落残缺 trace，事后覆盖。
       无论哪种，**都需要一个 `update_agent_trace(order_id, trace)` 之类的业务函数**
       ——Tool 不能直接改库（主文档 4.3），只能走 service 层。该函数不在冻结签名里，
       需补。**若不现在补，阶段 5 组装 trace 落库时必然撞上。**

    **2. `order_status` 默认 1 与主文档 5.5 第 3 步的校验口径不一致。**
       5.5 原文只校验「已确认订单」（字面 status=2）。默认落 1 的话，
       **Agent 创建的待确认订单不占位**，并发下会被人重复预约。
       需定：把 5.5 的校验范围明确成 `status IN (1,2)`，还是 Agent 路径直接落 2。
       本桩暂按 `status IN (1,2)`（更严）实现，即与 5.5 字面**不一致**——
       以谁为准需拍板。

    **3. `conflictType` 的取值枚举。** 见上方常量区，当前值是我方暂定。

    **4. `conflictDetail` 的类型。** 我暂定 object（装冲突订单号 / 时段 / 缺失设备 ID），
       前端屏 3 要按它渲染。若是 string，请明说。

    ══════════════════════════════════════════════════════════════════════
    ⚠️ 本桩**只读，不写库**——与真实实现的差距在此
    ══════════════════════════════════════════════════════════════════════
    真实实现必须严格按主文档 5.5 的顺序：

        BEGIN
          SELECT ... FOR UPDATE 锁定 space_resource 行
          校验 time 重叠（reserve_order 中 order_status IN (1,2)，见待确认第 2 条）
          校验设备可用性
          INSERT reserve_order + 扣减 device_resource.available_count
        COMMIT

    两处从本桩到真实实现的硬缺口：
      - 本桩**没有 FOR UPDATE**，只是普通 SELECT。低并发下测不出差别，
        演示当天并发上来才翻车——这段正确性由 `AGENT-C-01` 把关。
      - 主文档 5.5 六步里**没有「扣减 available_count」这一步**（第 4 步校验完
        直接 INSERT）。`device_resource.available_count` 字段确实存在，
        谁扣、何时扣需要明确，否则设备数会越用越多。

    本桩插入与扣减**一律不做**，原因：
      - 主文档 6.8 红线：测试禁止写 `reserve_order` 正式表；
      - `AGENT-C-01` 的并发语义无法在桩上验，假装能验就是假绿。
    因此 `orderId` 恒为 None，且返回里恒有 `"stub": True`。
    """
    start_dt = _parse_time(start_time)
    end_dt = _parse_time(end_time)

    if end_dt <= start_dt:
        return _fail(
            CONFLICT_INVALID_TIME,
            f"结束时间({end_time})不晚于开始时间({start_time})，拒绝锁定。",
        )

    async with AsyncSessionLocal() as session:
        # ---- 5.5 第 2 步（只读版）：场地时段重叠检测 ----
        # 真实实现此处为 SELECT ... FOR UPDATE，并依赖 idx_space_time 收窄锁范围
        # （space_id, start_time, end_time）。该索引目前**不存在**，见阶段 0 核对结论。
        conflict_stmt = (
            select(ReserveOrder.id, ReserveOrder.start_time, ReserveOrder.end_time)
            .where(
                ReserveOrder.space_id == space_id,
                ReserveOrder.order_status.in_(OCCUPYING_STATUS),
                ReserveOrder.start_time < end_dt,
                ReserveOrder.end_time > start_dt,
            )
            .limit(1)
        )
        conflict = (await session.execute(conflict_stmt)).first()
        if conflict is not None:
            return _fail(
                CONFLICT_TIME,
                (
                    f"场地 {space_id} 在该时段已被占用"
                    f"（订单 {conflict.id}：{conflict.start_time} ~ {conflict.end_time}），"
                    "请改时段或换场地。"
                ),
                detail={
                    "spaceId": space_id,
                    "orderId": conflict.id,
                    "startTime": str(conflict.start_time),
                    "endTime": str(conflict.end_time),
                },
            )

        # ---- 5.5 第 3 步：设备可用性校验 ----
        if device_ids:
            devices_stmt = select(DeviceResource).where(DeviceResource.id.in_(device_ids))
            rows = (await session.execute(devices_stmt)).scalars().all()

            missing = sorted(set(device_ids) - {r.id for r in rows})
            if missing:
                return _fail(
                    CONFLICT_DEVICE_MISSING,
                    f"设备不存在：{missing}。请从可借设备中选择。",
                    detail={"deviceIds": missing},
                )

            broken = [r.id for r in rows if r.device_status != 1]
            if broken:
                return _fail(
                    CONFLICT_DEVICE_UNAVAILABLE,
                    f"设备不可用（非完好状态）：{broken}。请改用替代设备。",
                    detail={"deviceIds": broken},
                )

            short = [r.id for r in rows if r.available_count <= 0]
            if short:
                return _fail(
                    CONFLICT_DEVICE_SHORTAGE,
                    f"设备库存不足（available_count <= 0）：{short}。请改用替代设备。",
                    detail={"deviceIds": short},
                )

    # ---- 5.5 第 4 步：INSERT + 扣减 —— 桩不执行 ----
    _ = (user_id, agent_request, agent_trace, order_status)  # 桩不落库，故不消费
    return {
        "ok": True,
        "orderId": None,
        "reason": (
            f"校验通过（预约人 {user_id}、场地 {space_id}、设备 {device_ids or '无'}、"
            f"{start_time} ~ {end_time}、拟落状态 {order_status}）。"
            "⚠️ 桩未落库、未扣减库存，orderId 为 None。"
        ),
        "conflictType": None,
        "conflictDetail": None,
        "stub": True,
    }
