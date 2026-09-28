# 合并检查清单：模块 3 / 蔡玉礼 的实现合入本分支时

**用途**：本分支（`feature/agent-xuchuan`）与 `origin/integrate/module3` 之间的
**已知合入风险与待办**。每条都附了判定方法——合完逐条核，**别只看构建绿**。

**出处**：2026-09-28 在临时分支 `tmp-verify-c01-02`（= `origin/integrate/module3` @ `1919428`，
用后即删、未推）上把模块 4 的 8 条断言跑了一遍：**蔡玉礼的 7 条判据 7/7 通过**，
只有 3b（并发版）红。下面第 1~3 条就是那次跑出来的。

---

## 1. `RESOURCE_CONFLICT: 409` 映射必须留住 ⚠️

- **在哪**：`backend/app/core/exceptions.py` 的 `_BUSINESS_ERROR_HTTP_STATUS`，
  `ErrorCode.RESOURCE_CONFLICT: 409` 这一条。
- **为什么只在一边**：这是集成侧 2026-09-28 的裁定（补登记 `40901 → 409`），
  **只有模块 4 分支有**；`integrate/module3` 的映射表里没有它。
- **不留住的后果**：`BusinessError(code=40901)` 这条**兼容层**路径回到兜底 **400**，
  同一个「时段冲突」出现两种状态码，前端得写两套分支；
  `test_resource_conflict_is_409_on_both_exception_paths` 红。
- **怎么核**：合并后 `git grep -n "RESOURCE_CONFLICT" -- backend/app/core/exceptions.py` 应命中映射表；
  跑 `pytest backend/tests/test_agent_concurrency.py -k 409`，两条契约用例应绿。

## 2. `CONFLICT_DEVICE_SHORTAGE` 常量必须留住 ⚠️

- **在哪**：`backend/app/services/order_service.py`，`CONFLICT_DEVICE_SHORTAGE = "device_conflict"`。
- **为什么只在一边**：相同取值在他那边是**字面量**，没有具名常量。
- **不留住的后果**：我们的用例文件
  `from app.services.order_service import CONFLICT_DEVICE_SHORTAGE` 会在**收集期 ImportError**
  ——不是红几条，是**一条都跑不起来**。
- **怎么核**：合并后 `pytest backend/tests/test_agent_concurrency.py --collect-only` 能收到 11 例。

## 3. `backend/tests/module4/` 合入时搬迁

- 蔡玉礼那边的 `backend/tests/module4/` 目前是**空壳**（`__init__.py` + 只有 docstring 的 `conftest.py`）；
  我们的 8 条断言在 `backend/tests/test_agent_concurrency.py`（不在该目录下）。
- **本分支先不建该目录**（2026-09-28 裁定）：现在建等于覆盖他的空壳，合并时必冲突。
- **合入时做**：`git mv backend/tests/test_agent_concurrency.py backend/tests/module4/`，
  按 `tests/module3/` 的先例统一布局；同时确认夹具归属（他的 `module4/conftest.py` 与我们的那份谁留）。

## 4. 设备行锁（断言 3b）是否补 —— 待蔡玉礼

- **现象**：临时分支上 3b 红——3 个协程抢同一台 `cap=2` 的设备，**3 单全成**（应恰好 2）。
- **原因**：他唯一的行锁在**场地行**（`order_service.py:142` 的 `FOR UPDATE`，`:504` 同），
  而 `_check_devices`（`:262`）读 `DeviceResource` **不加锁**、`_device_conflicts`（`:195`）
  在 Python 里数重叠单；3b 三单**刻意跨三个不同场地**（同场地会先撞场地冲突），
  那把场地行锁**串行不到**它们。（他那边跑在临时 SQLite 上，`FOR UPDATE` 会被编译掉，
  所以这条在那边**本来就验不了锁**。）
- **结论**：**3b 的 `xfail` 不摘**（2026-09-28 裁定），转告他补**设备行锁**或等价的串行化。
- **怎么核**：补上并合入本分支后，3b 应转绿并可摘掉 `xfail(strict)`。

## 5. `release_occupancy` 删 —— 蔡玉礼执行

- **裁定（2026-09-28）**：**删**。口径是「用时推导、不扣减」，**从不扣减即无回补需求**；
  名字暗示的「释放占用」在新口径下**没有语义**，留着会误导读代码的人。
- **现状**：`state_machine.py:57-63` 的函数体**就是 `pass`**——零行为（不回补 `available_count`、
  不改状态、不释放锁）；唯一调用点 `api/orders.py:251`（取消「已确认」单时），
  `tests/module3/test_orders.py:185/199` 只断言它「被调到」。
- **删除范围**：函数定义 + 调用点 + `import` + 上面那两处 hook 断言。
- **全文**：`contract-alignment.md` §10。

---

## 附：本次核对的原始出处

| 内容 | 出处 |
| --- | --- |
| 临时分支实测（7/8 通过、3b 红因） | `docs/spec/done/stage-07-completion.md` §5.3 |
| 「第四道锁」更正（取消入口存在且可用） | `docs/spec/done/README.md` 附录 / `contract-alignment.md` §9.1 |
| 「不同场地」约束（判据 2/5/7） | `contract-alignment.md` §9.2 |
| `release_occupancy` 裁定 | `contract-alignment.md` §10 / `done/README.md` 附录 |
