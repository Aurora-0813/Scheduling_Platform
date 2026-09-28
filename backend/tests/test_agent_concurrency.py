"""`available_count` 容量口径判据（`AGENT-C-01` / `AGENT-C-02`）——**当前标记为 xfail(strict)**。

## 为什么不是「写完就通过」，而是 xfail

这些断言验的是主文档 5.5 的事务与容量判定：`BEGIN → SELECT ... FOR UPDATE →
时段重叠 → 设备可用 → INSERT → COMMIT`。而模块 3（蔡玉礼）交付的 `create_order`
**目前是只读桩**：不 `FOR UPDATE`、不 INSERT、不计数，`orderId` 恒为 `None`，
返回体里恒带 `"stub": True`。桩自己的 docstring 写得很直白：

> `AGENT-C-01` 的并发语义无法在桩上验，**假装能验就是假绿**。

所以这些用例的处境是：**断言是真的，被测实现还不存在**。三种处置里只有 xfail 诚实：

| 处置 | 后果 |
| --- | --- |
| 删掉不写 | 阶段 7 的用例缺这一块，且「容量口径没验」这件事从报告里消失 |
| 改写成能过（只断言「返回体结构合法」） | 假绿：它永远会过，即使真实现把容量算反了 |
| **xfail(strict=True)** | 现状被如实记录；真实现落地后会**变红（XPASS）**，强制摘掉标记 |

`strict=True` 是关键：非严格 xfail 在实现落地、用例真的开始通过时**不会报错**，
这个「本该摘掉的标记」就会一直留着，把已通过的事实伪装成「已知不可用」。
`strict` 下 XPASS 即失败，等于一个「该摘标记了」的提醒。

## 判据沿革：2026-09-28 口径已定，原 C-01/C-02 的断言作废并替换

集成组裁定（蔡玉礼给出，方案接受）：**用时推导，不扣减**。
① `available_count` 是**静态上限**，不是实时剩余；② 剩余量 = `available_count` −
**该时段重叠订单数**，是**算出来的**；③ **不扣减、不回补、不加 §5.5 第 7 步**；
④ 取消后名额**自动回来**，无需回补代码。

这推翻了 `AGENT-C-02` 原有的两段断言（「锁定后递减 / 失败时不减」）——按新口径
该字段本就**不该**变，断言它变是在验一个不存在的实现。原 C-01 的
「同场地同时段并发恰好一个成功」也随之**升级**：容量为 2 的设备上，
并发 3 单应恰好 2 单成功（见 `test_assert_3b`）。

**现行判据 = 蔡玉礼的 7 条断言，逐条落地如下**（设 `available_count = 2`，
用开发库实测容量为 2 的 **设备 id=8 音响04**）：

| # | 断言 | 本文件用例 | 场地 / 设备 |
| --- | --- | --- | --- |
| 1 | 无重叠订单，建第 1 单占用该设备 → 成功，`order_status=1` | `test_assert_1_...` | 6 / 8 |
| 2 | 已有 1 单占用 T，建第 2 单同设备同 T → 成功（2 ≤ cap） | `test_assert_2_...` | 7 / 8 |
| 3 | 已有 2 单占用 T，建第 3 单同设备同 T → **拒绝，409 + `code=40901`** | `test_assert_3_...` | 8 / 8 |
| 3b | （并发版，保留原 C-01 的行锁语义）并发 3 单 → 恰好 2 单成功 | `test_assert_3b_...` | 6/7/8 / 8 |
| 4 | 已有 2 单占用 T，把其中一单 cancel（→3）→ 成功 | `test_assert_4_...` | 6 / 8 |
| 5 | 承上，再建第 3 单同设备同 T → 成功（回落到 1 < 2） | `test_assert_5_...` | 8 / 8 |
| 6 | 已有 2 单占用 T，与 T 相邻但不重叠的 T' → 成功（**半开区间**） | `test_assert_6_...` | 6 / 8 |
| 7 | 已有 2 单占用 T，第 3 单用**不同设备**同一 T → 成功（容量按设备各算） | `test_assert_7_...` | 8 / 7 |

**两次「场地」的选择不是随手写的**：`create_order` 的 §5.5 第 2 步先查**场地**时段
重叠，同一场地同一 T 的第二单会先撞 `CONFLICT_TIME`——那样测的是场地冲突，
不是设备容量。所以「同一设备多单」必须落在**不同场地**（6/7/8 在该时段都空，
实测：T 内只有 `reserve_order` id=5 占着 space 2）。

**冲突码已核实，无需新造**：`code=40901` = `ErrorCode.RESOURCE_CONFLICT`
（`app/core/error_codes.py:72`），HTTP 映射 `409` 由
`app/core/exceptions.py:181-183` 的 `ResourceConflictError.http_status` 给出。
⚠️ `40900/40902/40903` 也都映射到 `409`，判据里只写「409」时**要连业务码一起核**，
否则拿别的 409 也算过。该映射由 `test_resource_conflict_maps_to_40901_with_http_409`
单独把关（**这条能过，不挂 xfail**——它是契约事实，不是待实现的断言）。

## 三条锁挡在前面（必须一并解除，否则这些断言永远过不了）

1. **蔡玉礼改 `order_service._device_conflicts`**：按「时段重叠」推导剩余量
   （`剩余 = available_count − 该时段重叠订单数`），替换 `create_order` 的只读桩。
2. **测试库权限**（集成组，硬卡点 #4）：`smart_scheduler_test` 报 1044 无权访问，
   目前只能连开发库。
3. **`conftest._db_readonly_guard` 对写库放开**（依赖第 2 条）：它现在拦下一切写语句
   （`WriteForbiddenError`），真实现即便落地，INSERT 也会被这道拦截打死。

断言 4/5 还多第四道：**模块 3 的取消入口 `PUT /api/v1/orders/{orderId}/cancel` 未交付**
（路径见 `开发流程.md:381`，与 `Permission.ORDER_CANCEL`、`mock.py:93` 的镜像一致）。
本仓库没有这条真实路由，调用会 404。**不要为了让它过而改成直接改库**——
测试禁写正式表（主文档 6.8）。

在此之前，**不得声称 `AGENT-C-01` / `AGENT-C-02` 已通过**——阶段 7 的通过标准里有它们。
口径全文见 `docs/spec/done/README.md` 的《附录：`available_count` 口径》与 `docs/test.md` §3.5。
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.core.exceptions import ResourceConflictError
from app.models.reservation import ReserveOrder
from app.models.resource import DeviceResource
from app.services import create_order
from app.services.order_service import CONFLICT_DEVICE_SHORTAGE

# --------------------------------------------------------------------------
# 断言基准（开发库实测，2026-09-28；种子一变这里必须同步改，docs/test.md §3.2）
# --------------------------------------------------------------------------
#: 容量为 **2** 的设备：`device_resource` id=8 「音响04」（total=2, avail=2, status=1）。
#: 蔡玉礼的 7 条断言设的就是 `available_count=2`，所以这里必须是这个 id——
#: 换成 `projectors`（1/1）第 2 条断言就没有意义了。
_DEV_CAP2 = 8
#: 「第 3 单用不同设备」用的另一台（id=7「音响03」，cap=1，T 内零占用）。
#: 它的 cap 是 1 而不是 2，**这正是断言 7 要的**：设备 8 已满与设备 7 无关。
_DEV_ALT = 7
#: 三个场地（综合楼大礼堂 / 综合楼小多功能厅 / 中心广场）。
#: T 时段内**都空**——同一设备的多单必须分散在不同场地，理由见模块 docstring。
_SPACES = (6, 7, 8)
#: T：`conftest.FREE_SLOT` 的同一时段。space 6/7/8 在此段无任何订单。
_SLOT = ("2026-10-15 09:00:00", "2026-10-15 11:00:00")
#: T'：与 T **相邻但不重叠**（半开区间 `[09:00,11:00)` 与 `[11:00,12:00)`）。
#: 端点相接处（11:00）**不算重合**——断言 6 验的就是这一点。
_ADJACENT_SLOT = ("2026-10-15 11:00:00", "2026-10-15 12:00:00")

_XFAIL_REASON = (
    "断言是真的，被测实现还不存在，三道锁一道没解："
    "① 蔡玉礼的 create_order 仍是只读桩（不 SELECT ... FOR UPDATE、不 INSERT、"
    "不按「时段重叠」计数），_device_conflicts 尚未改成计数比较；"
    "② smart_scheduler_test 无权访问（1044，申云飞），用例只能连开发库；"
    "③ conftest._db_readonly_guard 据此拦下一切写语句，桩落库必然 WriteForbiddenError。"
    "（断言 4/5 另需模块 3 的 PUT /api/v1/orders/{orderId}/cancel。）"
    "三处到位后本用例应转为通过并摘掉本标记。"
)


async def _lock(space_id: int, start: str, end: str, *, user_id: int, device_ids=None):  # noqa: ANN001, ANN202
    """一次锁定尝试。身份**显式传参**——不得从请求体或模型那里取（主文档 5.1 / 9.1）。"""
    return await create_order(
        user_id=user_id,
        space_id=space_id,
        start_time=start,
        end_time=end,
        device_ids=device_ids,
    )


async def _order_status(session, order_id: int) -> int | None:  # noqa: ANN001
    """读订单状态。

    ⚠️ **必须先 `rollback()` 结束本会话可能已开启的事务**：MySQL 默认隔离级别是
    REPEATABLE READ，同一会话里若在此之前已经读过库，快照就固定在那一刻，
    `create_order` 事后提交的行**看不见**，断言会以「订单不存在」的形式假失败。
    这与被测实现无关，纯属读证据的手法。
    """
    await session.rollback()
    stmt = select(ReserveOrder.order_status).where(ReserveOrder.id == order_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def _available_count(session, device_id: int) -> int:  # noqa: ANN001
    """读设备的 `available_count`（静态上限）。同样先结束事务，理由见 `_order_status`。"""
    await session.rollback()
    stmt = select(DeviceResource.available_count).where(DeviceResource.id == device_id)
    return (await session.execute(stmt)).scalar_one()


async def _seed_two_orders_on_the_same_device() -> list[int]:
    """断言 3~7 的共同前置：**设备 8 在 T 被 2 单占满**。

    两单落在**不同场地**（space 6 / space 7）：同场地同 T 的第二单会先撞
    `CONFLICT_TIME`（§5.5 第 2 步查的是场地），与设备容量无关。
    """
    first = await _lock(_SPACES[0], *_SLOT, user_id=1, device_ids=[_DEV_CAP2])
    second = await _lock(_SPACES[1], *_SLOT, user_id=2, device_ids=[_DEV_CAP2])
    assert first["ok"] is True and first["orderId"] is not None, f"前置单 1 未落库：{first}"
    assert second["ok"] is True and second["orderId"] is not None, f"前置单 2 未落库：{second}"
    return [first["orderId"], second["orderId"]]


async def _cancel(client, order_id: int, auth: dict[str, str]):  # noqa: ANN001, ANN202
    """走模块 3 的取消入口 `PUT /api/v1/orders/{orderId}/cancel`。

    该路径取自 `开发流程.md:381` 的冻结接口清单，与 `Permission.ORDER_CANCEL`、
    `app/api/v1/mock.py:93` 的 mock 镜像一致——**不是我现编的**。
    本仓库当前没有这条真实路由（模块 3 未交付），调用会 404；**这是断言 4 现在
    必然失败的原因之一，不要为了让它过而改成直接 `UPDATE reserve_order`**
    （测试禁写正式表，主文档 6.8，且那样验的是测试自己而不是实现）。
    """
    return await client.put(f"/api/v1/orders/{order_id}/cancel", headers=auth)


# --------------------------------------------------------------------------
# 契约事实：40901 ↔ HTTP 409（**能过，不挂 xfail**）
# --------------------------------------------------------------------------
def test_resource_conflict_maps_to_40901_with_http_409() -> None:
    """判据里写的「409 + `code=40901`」在正式版里已经存在，不是待造的东西。

    ⚠️ `40900/40902/40903` 也都映射到 `409`：判据只写「409」时，
    必须**连业务码一起核**，否则拿别的 409 也算过。所以这条同时钉住业务码与状态码。
    """
    assert ResourceConflictError.code == 40901
    assert ResourceConflictError.http_status == 409


# --------------------------------------------------------------------------
# 断言 1~7（蔡玉礼的口径判据）
# --------------------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason=_XFAIL_REASON)
async def test_assert_1_first_order_on_free_slot_succeeds_and_is_persisted(dev_db_session) -> None:  # noqa: ANN001
    """**断言 1**：无重叠订单时建第 1 单占用该设备 → 成功，`order_status=1`。

    `order_status=1`（待确认）是 §5.5 第 3 步的校验范围决定的：Agent 建的待确认单
    **也占位**，否则并发下会被人重复预约（桩期 docstring「待蔡玉礼确认」第 2 条）。
    只断言 `ok=True` 不够——桩也返回 `ok=True`，落库与否要看 `orderId` 与库里的行。
    """
    result = await _lock(_SPACES[0], *_SLOT, user_id=1, device_ids=[_DEV_CAP2])

    assert result["ok"] is True, result
    assert result["orderId"] is not None, f"没落库就没有 orderId：{result}"
    assert await _order_status(dev_db_session, result["orderId"]) == 1


@pytest.mark.xfail(strict=True, reason=_XFAIL_REASON)
async def test_assert_2_second_order_same_device_same_slot_succeeds_at_capacity() -> None:
    """**断言 2**：已有 1 单占用 T，建第 2 单**同设备**同 T → 成功（`2 ≤ cap`）。

    「同设备」才能占满容量，所以两单必须落在不同场地（见 `_seed_two_orders_...` 的说明）。
    这一条把「cap = 2 是**上限**而不是独占」钉住：写成独占（第 2 单就拒）会在这里红。
    """
    first = await _lock(_SPACES[0], *_SLOT, user_id=1, device_ids=[_DEV_CAP2])
    assert first["ok"] is True, f"第 1 单就没成，本断言无从谈起：{first}"

    second = await _lock(_SPACES[1], *_SLOT, user_id=2, device_ids=[_DEV_CAP2])

    assert second["ok"] is True, f"`available_count=2` 却只容得下 1 单，容量被当成了独占：{second}"
    assert second["orderId"] is not None, second


@pytest.mark.xfail(strict=True, reason=_XFAIL_REASON)
async def test_assert_3_third_order_same_device_same_slot_is_rejected() -> None:
    """**断言 3**：已有 2 单占用 T，建第 3 单同设备同 T → **拒绝，409 + `code=40901`**。

    拒绝的判据是 `ok=False` 且 `conflictType` 指向**设备库存不足**
    （`CONFLICT_DEVICE_SHORTAGE` = `device_conflict`，靠 `conflictDetail.conflicts[].reason`
    = `exhausted` 与「设备停用」区分）。

    ⚠️ HTTP 409 / `code=40901` 不是本函数产出的——`create_order` 是 service，
    没有状态行。状态码由模块 3 的订单 API 按 `ResourceConflictError` 映射，
    该映射由 `test_resource_conflict_maps_to_40901_with_http_409` 单独把关；
    **这里断言的是「拒绝」这件事本身**，不能拿「反正 40901 存在」当作本用例通过。
    """
    await _seed_two_orders_on_the_same_device()

    third = await _lock(_SPACES[2], *_SLOT, user_id=3, device_ids=[_DEV_CAP2])

    assert third["ok"] is False, f"第 3 单成了——容量是 2 却不是计数比较（或压根没算）：{third}"
    assert third["conflictType"] == CONFLICT_DEVICE_SHORTAGE, third
    # 冲突方必须拿到可据以改方案的结构化信息，否则模型只能宣布失败
    assert third["conflictDetail"] is not None


@pytest.mark.xfail(strict=True, reason=_XFAIL_REASON)
async def test_assert_3b_three_concurrent_orders_on_a_cap_two_device_exactly_two_win() -> None:
    """**断言 3 的并发版**（保留原 `AGENT-C-01` 的行锁语义）。

    原 C-01 是「同场地同时段并发恰好 1 单成功」；容量改为 2 之后，正确的不变量
    是「**恰好 2 单成功**」：3 个协程同时抢同一台设备，第 3 个必须看见前两个已提交的
    占用行。它比断言 3（顺序调用）更严——顺序调用下即使没有 `FOR UPDATE` 也可能过，
    并发下漏了锁就会 3 单全成。

    **不要写成顺序三次调用**：那是在验重叠检测，不是在验锁。
    """
    results = await asyncio.gather(*(
        _lock(space, *_SLOT, user_id=user_id, device_ids=[_DEV_CAP2])
        for user_id, space in enumerate(_SPACES, start=1)
    ))

    succeeded = [r for r in results if r.get("ok")]
    rejected = [r for r in results if not r.get("ok")]

    assert len(succeeded) == 2, (
        f"容量 2 的设备被成功了 {len(succeeded)} 次——计数比较或行锁没起作用。返回体：{results}"
    )
    assert len(rejected) == 1, results
    assert rejected[0]["conflictType"] == CONFLICT_DEVICE_SHORTAGE, rejected[0]


@pytest.mark.xfail(strict=True, reason=_XFAIL_REASON)
async def test_assert_4_cancel_one_of_two_frees_the_device_slot(dev_client, dev_db_session, auth) -> None:  # noqa: ANN001
    """**断言 4**：已有 2 单占用 T，把其中一单 cancel（→3）→ 成功。

    这一条是「用时推导」与「扣减 + 回补」的分水岭：扣减方案下，取消必须**另有**
    回补代码名额才回得来；本方案下取消只是让重叠订单数从 2 掉到 1，什么都不用补。
    断言落在「取消成功且库里状态变 3」——**名额回没回来由断言 5 验**，两件事分开。
    """
    order_ids = await _seed_two_orders_on_the_same_device()

    resp = await _cancel(dev_client, order_ids[0], auth)

    assert resp.status_code == 200, f"取消接口没通（模块 3 未交付时为 404）：{resp.text}"
    assert await _order_status(dev_db_session, order_ids[0]) == 3


@pytest.mark.xfail(strict=True, reason=_XFAIL_REASON)
async def test_assert_5_after_cancel_third_order_succeeds_capacity_is_derived(dev_client) -> None:  # noqa: ANN001
    """**断言 5**：承上，再建第 3 单同设备同 T → 成功（回落到 `1 < 2`）。

    这是 4 个规则里第 ②④ 条的联合验证：剩余量是**算出来的**，取消后自动回落，
    **不需要任何回补代码**。若实现走了「扣减 + 回补」而回补漏了，
    断言 4 可能照样绿，这一条会红——这正是两条要分开写的原因。
    """
    order_ids = await _seed_two_orders_on_the_same_device()
    resp = await _cancel(dev_client, order_ids[0], auth)
    assert resp.status_code == 200, f"取消接口没通（模块 3 未交付时为 404）：{resp.text}"

    third = await _lock(_SPACES[2], *_SLOT, user_id=3, device_ids=[_DEV_CAP2])

    assert third["ok"] is True, (
        f"取消一单后剩余名额没回落（0 占用 + 1 生效 = 1 < 2，本该能建）：{third}"
    )
    assert third["orderId"] is not None, third


@pytest.mark.xfail(strict=True, reason=_XFAIL_REASON)
async def test_assert_6_adjacent_non_overlapping_slot_succeeds_half_open() -> None:
    """**断言 6**：已有 2 单占用 T，与 T **相邻但不重叠**的 T' → 成功（**半开区间**）。

    重叠判定必须是 `start < 对方end AND end > 对方start`（半开 `[start, end)`）：
    端点相接的 11:00 **不算重合**。写成闭区间（`<= / >=`）就会把 11:00 判成冲突，
    把本该能排的相邻场次挡掉——演示时表现为「明明没撞却说撞了」。

    这里刻意用**同一场地（space 6）+ 同一设备**：场地与设备任一环写成闭区间都会红。
    前置两单照旧占满 device 8 的 T。
    """
    await _seed_two_orders_on_the_same_device()
    adjacent_start, adjacent_end = _ADJACENT_SLOT

    result = await _lock(
        _SPACES[0], adjacent_start, adjacent_end, user_id=3, device_ids=[_DEV_CAP2]
    )

    assert result["ok"] is True, (
        f"与 T 端点相接的 T'（{adjacent_start} ~ {adjacent_end}）被判成冲突——"
        f"重叠检测用了闭区间。返回体：{result}"
    )
    assert result["orderId"] is not None, result


@pytest.mark.xfail(strict=True, reason=_XFAIL_REASON)
async def test_assert_7_other_device_same_slot_succeeds_capacity_is_per_device() -> None:
    """**断言 7**：已有 2 单占用 T，第 3 单用**不同设备**同一 T → 成功（容量按设备各算）。

    容量是**每台设备各自的**，不是全局共享额度：device 8 满了不影响 device 7。
    把容量错算成「全局剩余」时，这一条会把该建的单挡掉（模型于是只能宣布失败，
    而其实换个设备就能成）。

    备用设备 id=7（音响03）的 `available_count` 是 **1** 且 T 内零占用，
    所以它上面只建**一单**——建两单会撞它自己的 cap，那是断言 3 的事，不是本条的。
    """
    await _seed_two_orders_on_the_same_device()

    result = await _lock(_SPACES[2], *_SLOT, user_id=3, device_ids=[_DEV_ALT])

    assert result["ok"] is True, f"设备容量被算成了全局额度：{result}"
    assert result["orderId"] is not None, result


# --------------------------------------------------------------------------
# 桩期实录（**能过**，不挂 xfail；真实现落地后按下面 docstring 处理）
# --------------------------------------------------------------------------
async def test_stub_state_is_recorded_not_glossed_over(dev_db_session, slots, seed) -> None:  # noqa: ANN001
    """记录桩期的真实状态，让「`AGENT-C-01` 未通过」这件事在测试输出里看得见。

    ⚠️ **本条是桩期临时用例**（断言 `stub` 键、`orderId is None`）。
    蔡玉礼的真实现落地后本条会失败——那时应当**删除**它，而不是放宽断言。

    例外的一条：**`available_count` 前后不变**。按 2026-09-28 的新口径
    「用时推导，不扣减」，这**不再是桩期特征，而是长期期望**——该字段是静态上限，
    任何时候都不该被锁定动作改动。真实现落地后这一句要**保留**（挪进断言用例亦可），
    另两句随 `stub` 键一起删。
    """
    start, end = slots["free"]
    device_id = seed["speakers"][3]
    assert device_id == _DEV_CAP2, "种子变了：断言基准 `_DEV_CAP2` 必须同步改"

    before = await _available_count(dev_db_session, device_id)
    result = await _lock(_SPACES[0], start, end, user_id=1, device_ids=[device_id])
    after = await _available_count(dev_db_session, device_id)

    assert result["ok"] is True
    assert result["orderId"] is None, "桩竟然落库了——先确认这是有意的，再改本用例"
    assert result.get("stub") is True
    assert after == before, "静态上限被改动了——新口径是「用时推导，不扣减」，不该变"
