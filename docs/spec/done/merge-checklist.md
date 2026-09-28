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
- **2026-09-28 更新（风险变了，务必看）**：这一条**`origin/main` 上现在也有了**——
  main 的 `6e3c8e1 fix(api): 兼容层补 40901→409，两条抛法状态码对齐`
  （`backend/app/core/exceptions.py:301`）。集成侧当初的裁定是「补登记」，main 那边也照做了。
  于是风险从「会不会丢」变成 **「合并后会不会留成两条重名键、或取值不一致」**。
- **不留住（或留成两条、取值走样）的后果**：`BusinessError(code=40901)` 这条**兼容层**路径
  回到兜底 **400**，同一个「时段冲突」出现两种状态码，前端得写两套分支；
  `test_resource_conflict_is_409_on_both_exception_paths` 红。
- **怎么核**：合并后 `git grep -n "RESOURCE_CONFLICT" -- backend/app/core/exceptions.py`
  应**恰好一条**且值为 `409`；跑 `pytest backend/tests/test_agent_concurrency.py -k 409`，
  两条契约用例应绿。
- ⚠️ **`exceptions.py` 正是试合并的 3 个冲突文件之一**（见第 6 节）：
  手工解冲突时，这条映射最容易被顺手丢掉或留成两份。

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

## 6. 试合并实测：3 处冲突，且 main 不是祖先（2026-09-28）

**做法**（只读，未落任何改动）：`git merge-tree --write-tree HEAD origin/main`
——git 2.55 的试合并，只算不合。退出码 1，合并树 `9141c6d5…`。

| 冲突文件 | 性质 |
| --- | --- |
| `backend/app/agent/prompts/image_prompt.py` | **本模块文件**：两边各跑过一次 `ruff format`，同一批行在格式化处相撞 |
| `backend/app/api/v1/__init__.py` | 路由注册表：同上，两边各格式化过 |
| `backend/app/core/exceptions.py` | 第 1 条那条 409 映射所在的文件，两边都动过 |

三处都是**格式 / 同址改动相撞**，不是语义分歧——但**必须有人手工解**，
解完要复跑第 1 条核对与 `ruff format --check`。

**`origin/main` 不是本分支的祖先**：本分支 58 个提交、main 独有 6 个，
merge-base `98c54ea`。所以**不能快进合并**，只能真合（或 rebase）。

**main 上还缺整块东西**：

- `backend/app/api/v1/` 只有 `__init__ / auth / health / image / mock / mock_data / monitor / voice`
  ——**没有 `agent.py`，也没有 `orders.py`**；
- `backend/app/services/` 没有 `order_service.py`、`space_service.py`、`device_service.py`。

即 **main 上既没有模块 3 的真实现，也没有模块 4 的入口**。把本分支合进 main，
只是把模块 4 的代码搬到一棵缺模块 3 的树上，**演示主线仍然跑不通**。
（这也是「合并目标该是 `develop` 还是 `main`」必须在项目群定的原因，见
`stage-09-10-prep.md` §3。）

---

## 附：本次核对的原始出处

| 内容 | 出处 |
| --- | --- |
| 临时分支实测（7/8 通过、3b 红因） | `docs/spec/done/stage-07-completion.md` §5.3 |
| 「第四道锁」更正（取消入口存在且可用） | `docs/spec/done/README.md` 附录 / `contract-alignment.md` §9.1 |
| 「不同场地」约束（判据 2/5/7） | `contract-alignment.md` §9.2 |
| `release_occupancy` 裁定 | `contract-alignment.md` §10 / `done/README.md` 附录 |
| 试合并 3 处冲突、main 缺模块 3/4 文件 | `stage-09-10-prep.md` §2、§3 |
| CI 红数实测（本模块 0 条） | `stage-09-10-prep.md` §2 |
