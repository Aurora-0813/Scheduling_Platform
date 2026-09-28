"""并发与事务用例（`AGENT-C-01` / `AGENT-C-02`）——**当前标记为 xfail(strict)**。

## 为什么不是「写完就通过」，而是 xfail

这两条验的是主文档 5.5 的事务与行锁：`BEGIN → SELECT ... FOR UPDATE → 时段重叠 →
设备可用 → INSERT + 扣减 → COMMIT`。而模块 3（蔡玉礼）交付的 `create_order`
**目前是只读桩**：不 `FOR UPDATE`、不 INSERT、不扣减，`orderId` 恒为 `None`，
返回体里恒带 `"stub": True`。桩自己的 docstring 写得很直白：

> `AGENT-C-01` 的并发语义无法在桩上验，**假装能验就是假绿**。

所以这两条用例的处境是：**断言是真的，被测实现还不存在**。三种处置里只有 xfail 诚实：

| 处置 | 后果 |
| --- | --- |
| 删掉不写 | 阶段 7 的 21 条用例缺 2 条，且「并发没验」这件事从报告里消失 |
| 改写成能过（只断言「两次调用的返回体结构合法」） | 假绿：它永远会过，即使真实现把行锁写反了 |
| **xfail(strict=True)** | 现状被如实记录；真实现落地后会**变红（XPASS）**，强制摘掉标记 |

`strict=True` 是关键：非严格 xfail 在实现落地、用例真的开始通过时**不会报错**，
这个「本该摘掉的标记」就会一直留着，把已通过的事实伪装成「已知不可用」。
`strict` 下 XPASS 即失败，等于一个「该摘标记了」的提醒。

## 2026-09-28：`available_count` 口径已定，C-02 的断言随之作废

集成组裁定（蔡玉礼给出，方案接受）：**用时推导，不扣减**。
① `available_count` 是**静态上限**，不是实时剩余；② 剩余量 = `available_count` −
**该时段重叠订单数**，是**算出来的**；③ **不扣减、不回补、不加 §5.5 第 7 步**；
④ 取消后名额**自动回来**，无需回补代码。

这直接推翻了 `AGENT-C-02` 原有的两段断言（「锁定后递减 / 失败时不减」）——按新口径
该字段本就不该变，断言它变是在验一个不存在的实现。**新判据照蔡玉礼的 7 条断言改，
改完再摘 `xfail`。** `AGENT-C-01` 的判据不受影响，只是冲突码确认为 **409 + `code=40901`**
（正式版 `core/error_codes.py:72` 与 `core/exceptions.py:181-183` 已有，无需新造）。

**两条都还卡在同一件事上：`order_service._device_conflicts` 要按「时段重叠」推导剩余量
（蔡玉礼）**，外加测试库权限（申云飞）。口径全文见
`docs/spec/done/README.md` 的《附录：`available_count` 口径》。

## 还有第二道锁挡在前面（必须一并解除，否则这两条永远过不了）

阶段 7 §3.2 要求用例连**测试库** `smart_scheduler_test` 并回滚，该库当前
**无权访问**（1044），于是 `conftest.py::_db_readonly_guard` 拦下了所有写语句，
用来保证连开发库时不污染种子数据。这意味着**即使蔡玉礼的真实现落地**，
真实的行锁与扣减也会被这道拦截打死（`WriteForbiddenError`），用例仍过不了。

要让这两条真正跑起来，三件事缺一不可：

1. 蔡玉礼替换 `create_order` / `update_agent_trace` 的真实实现
2. **测试库权限**（集成组）——并发用例必须能真写、真回滚
3. `_db_readonly_guard` 对这两个文件**放开**（否则第 1、2 步到位也没用）

在此之前，**不得声称 `AGENT-C-01` 已通过**——阶段 7 的通过标准里有它一条。
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.models.resource import DeviceResource
from app.services import create_order
from app.services.order_service import CONFLICT_TIME

#: 两条用例共用：开发库里 space 6 在该时段**没有任何订单**（见 conftest 的 `FREE_SLOT`）。
#: 只有用空闲时段，「恰好一个成功」才是一个有意义的断言——用已占用时段的话
#: 两个都失败，也能「恰好零个成功」，测不出行锁。
_TWO = 2


async def _lock(space_id: int, start: str, end: str, *, user_id: int, device_ids=None):  # noqa: ANN001, ANN202
    """一次锁定尝试。身份**显式传参**——不得从请求体或模型那里取（主文档 5.1 / 9.1）。"""
    return await create_order(
        user_id=user_id,
        space_id=space_id,
        start_time=start,
        end_time=end,
        device_ids=device_ids,
    )


async def _available_count(session, device_id: int) -> int:  # noqa: ANN001
    stmt = select(DeviceResource.available_count).where(DeviceResource.id == device_id)
    return (await session.execute(stmt)).scalar_one()


# --------------------------------------------------------------------------
# AGENT-C-01
# --------------------------------------------------------------------------
@pytest.mark.xfail(
    strict=True,
    reason=(
        "create_order 仍是只读桩：没有 SELECT ... FOR UPDATE，也没有 INSERT，"
        "两次并发锁定都会返回 ok=True，因此「恰好一个成功」必然不成立。"
        "真实现落地 + 测试库权限到位 + 写库拦截放开后，本用例应转为通过并摘掉本标记。"
        "（2026-09-28：冲突码已确认用 409 + code=40901，正式版 core/error_codes.py:72 与 "
        "core/exceptions.py:181-183 已有，无需新造；**还等蔡玉礼改 order_service._device_conflicts"
        "（按「时段重叠」推导剩余量）**，判定口径见 docs/test.md §3.5 与 "
        "docs/spec/done/README.md 的《附录：available_count 口径》。）"
    ),
)
async def test_c01_concurrent_locks_on_the_same_slot_exactly_one_wins(slots) -> None:  # noqa: ANN001
    """`AGENT-C-01` 两个协程同时锁定**同一场地同一时段**：恰好一个成功，另一个收到冲突提示。

    这是阶段 7 里**唯一无法靠「看代码正确」保证**的用例：5.5 的顺序写对了才过，
    写错了在低并发下测不出来，演示当天并发上来就翻车。

    用 `asyncio.gather` 让两个协程真的同时在飞——**不要写成顺序两次调用**：
    顺序调用下即使没有行锁也会「恰好一个成功」（第二个撞上第一个已提交的订单），
    那是在验重叠检测，不是在验锁。
    """
    start, end = slots["free"]

    results = await asyncio.gather(
        _lock(6, start, end, user_id=1),
        _lock(6, start, end, user_id=2),
    )

    succeeded = [r for r in results if r.get("ok")]
    conflicted = [r for r in results if not r.get("ok")]

    assert len(succeeded) == 1, (
        f"同一场地同一时段被成功了 {len(succeeded)} 次——行锁没起作用。"
        f"返回体：{results}"
    )
    assert len(conflicted) == 1
    assert conflicted[0]["conflictType"] == CONFLICT_TIME
    # 冲突方必须拿到可据以改方案的结构化信息，否则模型只能宣布失败
    assert conflicted[0]["conflictDetail"] is not None


async def test_c01_stub_state_is_recorded_not_glossed_over(slots) -> None:  # noqa: ANN001
    """记录桩期的真实状态：校验通过也不落库。

    ⚠️ **本条是桩期临时用例**（断言 `stub` 键与 `orderId is None`）。
    蔡玉礼的真实现落地后本条会失败——那时应当**删除**它，而不是放宽断言；
    它存在的意义只是让「AGENT-C-01 未通过」这件事在测试输出里看得见。
    """
    start, end = slots["free"]

    result = await _lock(6, start, end, user_id=1, device_ids=[1])

    assert result["ok"] is True
    assert result["orderId"] is None, "桩竟然落库了——先确认这是有意的，再改本用例"
    assert result.get("stub") is True


# --------------------------------------------------------------------------
# AGENT-C-02
# --------------------------------------------------------------------------
@pytest.mark.xfail(
    strict=True,
    reason=(
        "create_order 桩不扣减 available_count，锁定后库存不变，因此本用例必然不成立。"
        "（2026-09-28 更新：口径已定「用时推导，不扣减」——available_count 是**静态上限**，"
        "剩余量 = available_count − 该时段重叠订单数，是算出来的；本用例下面这两段断言"
        "**本身已作废**（按新口径该字段不该变）。新判据照蔡玉礼的 7 条断言改，改完再摘本标记。"
        "**还等蔡玉礼改 order_service._device_conflicts（按「时段重叠」推导剩余量）**，"
        "外加测试库权限。口径全文见 docs/spec/done/README.md《附录：available_count 口径》。）"
    ),
)
async def test_c02_device_count_decrements_on_lock_and_survives_failure(dev_db_session, slots, seed) -> None:  # noqa: ANN001
    """`AGENT-C-02` 设备数量扣减：锁定成功后 `available_count` 递减；**失败时（回滚）不减**。

    ⚠️ **2026-09-28：本用例的两段断言已作废，等改写。** 口径定为「用时推导，不扣减」——
    `available_count` 是静态上限，剩余量 = `available_count` − 该时段重叠订单数（算出来的），
    该字段本就**不该**随锁定变化。断言它递减，是在验一个不存在的实现。
    新判据照蔡玉礼的 7 条断言改后再摘 `xfail`；在那之前保留本文件并保持 `xfail(strict)`
    ——`strict` 保证改写落地后若仍红会直接报错，不会静默错过。

    下面这段是作废前的原文，保留以记录判据沿革：
    两段都必要，只验前一段会把「减了但失败时没回补」这种实现判为通过——
    那正是设备数会越用越少（或越多）的成因。
    """
    device_id = seed["projectors"][0]
    free_start, free_end = slots["free"]
    busy_start, busy_end = slots["occupied"]

    before = await _available_count(dev_db_session, device_id)

    ok = await _lock(6, free_start, free_end, user_id=1, device_ids=[device_id])
    assert ok["ok"] is True
    after_success = await _available_count(dev_db_session, device_id)
    assert after_success == before - 1, f"锁定后库存没扣：{before} → {after_success}"

    # 失败路径：场地在目标时段已被占用（reserve_order id=9 占着 space 4）
    failed = await _lock(4, busy_start, busy_end, user_id=1, device_ids=[device_id])
    assert failed["ok"] is False
    after_failure = await _available_count(dev_db_session, device_id)
    assert after_failure == after_success, "失败的锁定把库存也扣了——回滚没做或做了没生效"


async def test_c02_stub_state_is_recorded_not_glossed_over(dev_db_session, slots, seed) -> None:  # noqa: ANN001
    """记录桩期的真实状态：不扣减、不回补，只做校验。

    ⚠️ 同样是**桩期临时用例**，真实现落地后应删除。
    """
    device_id = seed["projectors"][0]
    start, end = slots["free"]

    before = await _available_count(dev_db_session, device_id)
    result = await _lock(6, start, end, user_id=1, device_ids=[device_id])
    after = await _available_count(dev_db_session, device_id)

    assert result["ok"] is True
    assert after == before, "桩开始扣减库存了——先确认口径，再改本用例"
