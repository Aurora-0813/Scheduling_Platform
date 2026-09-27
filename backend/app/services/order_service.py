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
    "update_agent_trace",
    "OCCUPYING_STATUS",
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
#: ✅ **2026-09-27 已与蔡玉礼对齐为下列值**（依据 `docs/spec/contract-alignment.md` 第 3 条，
#: 出自 `docs/api.md` §7.2）。此前阶段 3 的 SCREAMING_SNAKE 取值**已作废**。
#:
#: 两条要点：
#:   1. 命名是 **snake_case**，不是 SCREAMING_SNAKE。
#:   2. 设备类的两种情形**不再拆成两个取值**，统一为 `device_conflict`，
#:      靠 `conflictDetail.conflicts[].reason` 区分「设备停用」(`status`)
#:      与「数量不足」(`exhausted`)。
#:
#: 全仓唯一定义点仍是这里——不要把这些字符串散落到 Tool 层或前端。
CONFLICT_TIME = "time_conflict"              # 场地时段冲突
CONFLICT_DEVICE_MISSING = "not_found"        # 设备 ID 不存在
CONFLICT_DEVICE_UNAVAILABLE = "device_conflict"  # 设备非完好状态（reason=status）
CONFLICT_DEVICE_SHORTAGE = "device_conflict"     # 设备库存不足（reason=exhausted）
CONFLICT_INVALID_TIME = "invalid_param"      # 起止时间本身非法

#: `conflictDetail.conflicts[].reason` 的取值。
#: ⚠️ `docs/api.md` §7.2 的**四种 `conflictDetail` 形状尚未到手**
#: （contract-alignment 第 4、6 条），这里只放出已确认的两个 reason 字面量；
#: 形状补齐前**不要据此改桩**。
CONFLICT_REASON_DEVICE_STATUS = "status"        # 设备停用（device_status != 1）
CONFLICT_REASON_DEVICE_EXHAUSTED = "exhausted"  # 数量不足（available_count <= 0）

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


def _coerce_int(value: object) -> int | None:
    """尽力转整数。转不了返回 None（由调用方转成业务失败）。

    `True`/`False` 要挡掉——Python 里 `isinstance(True, int)` 为真，
    不挡的话 `device_ids=[True]` 会静默变成设备 ID 1。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


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
    # ---- 入参容错（2026-09-27 对齐结果第 3 条，一并对齐）----
    # 背景：LLM 与前端都可能把 ID 传成字符串。两种情形的处置**刻意不同**：
    #   `space_id="101"`   → 转成整数。无害，转了就能用。
    #   `device_ids="1"`   → **必须挡掉报错**。不挡的话 `for x in "1"` 会**逐字符迭代**，
    #                        静默变成 `[1]`——错得无声无息，比报错危险得多。
    coerced_space_id = _coerce_int(space_id)
    if coerced_space_id is None:
        return _fail(CONFLICT_INVALID_TIME, f"space_id 无法解析为整数：{space_id!r}。")
    space_id = coerced_space_id

    if device_ids is not None and not isinstance(device_ids, (list, tuple)):
        return _fail(
            CONFLICT_INVALID_TIME,
            f"device_ids 必须是数组，收到 {type(device_ids).__name__}（{device_ids!r}）。"
            "传字符串会被逐字符迭代成错误的 ID 列表，故直接拒绝。",
        )
    if device_ids:
        bad = [d for d in device_ids if _coerce_int(d) is None]
        if bad:
            return _fail(CONFLICT_INVALID_TIME, f"device_ids 含非整数项：{bad}。")
        device_ids = [_coerce_int(d) for d in device_ids]

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
        # 两种情形共用 `device_conflict`，靠 conflicts[].reason 区分（对齐结果第 3 条）。
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

            conflicts = [
                {"deviceId": r.id, "reason": CONFLICT_REASON_DEVICE_STATUS}
                for r in rows if r.device_status != 1
            ]
            if conflicts:
                return _fail(
                    CONFLICT_DEVICE_UNAVAILABLE,
                    f"设备不可用（非完好状态）：{[c['deviceId'] for c in conflicts]}。"
                    "请改用替代设备。",
                    detail={"conflicts": conflicts},
                )

            conflicts = [
                {"deviceId": r.id, "reason": CONFLICT_REASON_DEVICE_EXHAUSTED}
                for r in rows if r.available_count <= 0
            ]
            if conflicts:
                return _fail(
                    CONFLICT_DEVICE_SHORTAGE,
                    f"设备库存不足（available_count <= 0）：{[c['deviceId'] for c in conflicts]}。"
                    "请改用替代设备。",
                    detail={"conflicts": conflicts},
                )
            # ⚠️ 校验通过后**不做任何扣减**。对齐结果第 5 条：主文档 5.5 六步里既没有
            # 扣减、也没有取消时回补，单方面扣会造出第二份真值。当前口径是
            # 「只校验 available_count > 0，不落任何写入」，正式口径待集成组给。

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


async def update_agent_trace(*, order_id: int, user_id: int, agent_trace: dict | None) -> dict:
    """[桩] 补写 `reserve_order.agent_trace`。

    TODO(蔡玉礼): 替换为模块 3 的真实实现，**替换时只换函数体，签名不动**。

    ══════════════════════════════════════════════════════════════════════
    签名来源：2026-09-27 与蔡玉礼对齐第 1 条（`contract-alignment.md`）
    ══════════════════════════════════════════════════════════════════════
        update_agent_trace(order_id, user_id, agent_trace)

    | 项 | 约定 | 本桩是否遵守 |
    | --- | --- | --- |
    | 参数限定 | **keyword-only**（与 `create_order` 同规矩） | 是 |
    | 签名含 `db` | 否——会话与事务边界由函数自管 | 是 |
    | `user_id` | **必须进签名**，用于**归属校验** | 是（见下） |
    | 失败语义 | 业务性失败返回 `ok=false`，**不抛异常** | 是 |
    | 返回值 | 与 `create_order` 同构，含 `ok` | 是 |

    **为什么 `user_id` 必须进签名**：没有它，任何调用方拿到一个 `orderId`
    就能改别人的 trace——而 trace 会在 PC 后台展示（答辩溯源），
    等于开放了一个「篡改他人记录」的口子。主文档 5.1 要求身份一律受控。

    ══════════════════════════════════════════════════════════════════════
    为什么需要这个函数（它不是「多出来的」）
    ══════════════════════════════════════════════════════════════════════
    `lock_resources` 被调用那一刻，本次 Agent 运行**还没结束**，trace 注定残缺；
    完整 trace 只有 `create_order` 返回之后才存在。而 Tool 不能直接改库（主文档 4.3），
    所以必须有一个独立的 service 函数来补这次 UPDATE。

    时序采用方案 **(a)**：`create_order` 落 `agent_trace=None`，路由在 Agent 跑完后
    调本函数补一次。不采用方案 (b)（落残缺 trace 再覆盖）——残缺 trace 会被前端
    **当成完整链路渲染**，而 `TC-26` / `TC-30` 验收的恰恰是「溯源完整」，
    且覆盖存在并发窗口。`None` 的语义是干净的：**尚未生成**。

    ⚠️ 本桩**不写库**：不 UPDATE、恒返回 `ok=False`，与 `create_order` 桩同一处置
    （主文档 6.8 红线：测试禁止写 `reserve_order` 正式表）。返回体恒带 `"stub": True`。
    """
    _ = (order_id, user_id, agent_trace)  # 桩不落库，故不消费
    return {
        "ok": False,
        "orderId": order_id,
        "reason": (
            "update_agent_trace 仍是桩：未写库。"
            "真实实现落地前，agent_trace 不会出现在 reserve_order 中。"
        ),
        "stub": True,
    }
