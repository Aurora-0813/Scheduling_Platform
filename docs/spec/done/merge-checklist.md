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
- ⚠️ **`exceptions.py` 正是试合并的 3 个冲突文件之一**（见第 7 节）：
  手工解冲突时，这条映射最容易被顺手丢掉或留成两份。

## 2. `notify_service.py` 是 add/add，且**必须带回 `0db6c18`** ⚠️⚠️

**这条不是「功能待办」，是「本分支能不能合」的硬前提。**

- **在哪**：`backend/app/services/notify_service.py`。本分支是**阶段 3 的桩**，
  模块 7 侧是**真实实现**，两侧各自独立新增同一路径 → git 判 **add/add 冲突**。
  **实测**（`git merge-tree --write-tree HEAD <对方>`）：对 `origin/integ/module7-into-main`
  与 `origin/feat/module7-conflict-notify` **都报 `CONFLICT (add/add)`**。
- **该函数只在 feat 分支上**（2026-09-28 实测）：

  | ref / 提交 | 文件在不在 | 含 `def generate_notification` |
  | --- | --- | --- |
  | `0db6c18`（`refactor(module7): 撤内部 Agent Tool，Tool 层归模块 4`） | 在 | **1 处** ✅ |
  | `f278b35`（`integ/module7-into-main` 的头） | 在 | **0 处** ❌ |
  | `origin/integ/module7-into-main`（整份文件 12 个函数，无该入口） | 在 | **0 处** ❌ |

  `git merge-base --is-ancestor 0db6c18 origin/integ/module7-into-main` → **否**（integ 不含它）。
  → **模块 7 的 v3 必须带回 `0db6c18` 及以后**，否则合进来的 `notify_service.py`
  里根本没有这个函数。
- **不带回的后果**：`backend/app/services/__init__.py:35` 的
  `from app.services.notify_service import generate_notification` 直接 **ImportError**。
  ⚠️ **范围别估小**：`app/services/__init__.py` 是**包入口**，任何 `import app.services.*`
  都会先执行它（Python 语义，非实测）→ 不是「工具层少个函数」，
  而是**整个后端在 import 期就起不来**。
- **同一条链上的第二处**：`backend/app/services/__init__.py` 自己。本分支 `:34-37`
  re-export 了 5 个名字（`query_spaces` / `query_devices` / `create_order` /
  `update_agent_trace` / `generate_notification`），`origin/main` 的版本**一句 import 都没有**
  （只有约定文档）；试合并对 `feat/module7-conflict-notify`
  **正报 `CONFLICT (content): backend/app/services/__init__.py`**。
  **这一行必须取并集**（模块 4 的 re-export + 对方新增），整段取模块 7 版本 = 打掉模块 4 的工具层。
  并集理由已写在文件头 `services/__init__.py:15-32`（四个桩是**叶子**模块，不构成循环导入）。
- **怎么核**（合并后逐条）：
  1. `git grep -n "def generate_notification" -- backend/app/services/notify_service.py`
     → 必须命中 **1 处**；
  2. `git grep -n "notify_service" -- backend/app/services/__init__.py` → 命中那条 re-export；
  3. `cd backend && python -c "import app.services"` → 不报 ImportError；
  4. `pytest backend/tests/test_agent_tools.py -q` → 全绿（该文件正是靠这条 re-export 导入的）。

## 3. `CONFLICT_DEVICE_SHORTAGE` 常量必须留住 ⚠️

- **在哪**：`backend/app/services/order_service.py`，`CONFLICT_DEVICE_SHORTAGE = "device_conflict"`。
- **为什么只在一边**：相同取值在他那边是**字面量**，没有具名常量。
- **不留住的后果**：我们的用例文件
  `from app.services.order_service import CONFLICT_DEVICE_SHORTAGE` 会在**收集期 ImportError**
  ——不是红几条，是**一条都跑不起来**。
- **怎么核**：合并后 `pytest backend/tests/test_agent_concurrency.py --collect-only` 能收到 11 例。

## 4. `backend/tests/module4/` 合入时搬迁

- 蔡玉礼那边的 `backend/tests/module4/` 目前是**空壳**（`__init__.py` + 只有 docstring 的 `conftest.py`）；
  我们的 8 条断言在 `backend/tests/test_agent_concurrency.py`（不在该目录下）。
- **本分支先不建该目录**（2026-09-28 裁定）：现在建等于覆盖他的空壳，合并时必冲突。
- **合入时做**：`git mv backend/tests/test_agent_concurrency.py backend/tests/module4/`，
  按 `tests/module3/` 的先例统一布局；同时确认夹具归属（他的 `module4/conftest.py` 与我们的那份谁留）。

## 5. 设备行锁（断言 3b）是否补 —— 待蔡玉礼

- **现象**：临时分支上 3b 红——3 个协程抢同一台 `cap=2` 的设备，**3 单全成**（应恰好 2）。
- **原因**：他唯一的行锁在**场地行**（`order_service.py:142` 的 `FOR UPDATE`，`:504` 同），
  而 `_check_devices`（`:262`）读 `DeviceResource` **不加锁**、`_device_conflicts`（`:195`）
  在 Python 里数重叠单；3b 三单**刻意跨三个不同场地**（同场地会先撞场地冲突），
  那把场地行锁**串行不到**它们。（他那边跑在临时 SQLite 上，`FOR UPDATE` 会被编译掉，
  所以这条在那边**本来就验不了锁**。）
- **结论**：**3b 的 `xfail` 不摘**（2026-09-28 裁定），转告他补**设备行锁**或等价的串行化。
- **怎么核**：补上并合入本分支后，3b 应转绿并可摘掉 `xfail(strict)`。

## 6. `release_occupancy` 删 —— 蔡玉礼执行

- **裁定（2026-09-28）**：**删**。口径是「用时推导、不扣减」，**从不扣减即无回补需求**；
  名字暗示的「释放占用」在新口径下**没有语义**，留着会误导读代码的人。
- **现状**：`state_machine.py:57-63` 的函数体**就是 `pass`**——零行为（不回补 `available_count`、
  不改状态、不释放锁）；唯一调用点 `api/orders.py:251`（取消「已确认」单时），
  `tests/module3/test_orders.py:185/199` 只断言它「被调到」。
- **删除范围**：函数定义 + 调用点 + `import` + 上面那两处 hook 断言。
- **全文**：`contract-alignment.md` §10。

## 7. 试合并实测：3 处冲突，且 main 不是祖先（2026-09-28）

**做法**（只读，未落任何改动）：`git merge-tree --write-tree HEAD origin/main`
——git 2.55 的试合并，只算不合。退出码 1，合并树 `9141c6d5…`。

**主干漂移记录**：本节的试合并基于 `origin/main` @ **`2fd726e`**。主干另有一次漂移
`b4f4077` → `2fd726e`（`chore(ci): 前端 job 模板的 setup-node 版本更正为 v7`），
实测**只动 `.github/workflows/backend-ci.yml` 一个文件（+5/−1）**，不碰后端代码
——**本节与 CI 红数的结论都不受影响**，不需重测。

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
| `notify_type` 裁定与用例待办（第 2 条的依据） | `done/README.md` 硬卡点 #13 / `contract-alignment.md` §8.2 |
| `notify_service.py` add/add（第 2 条实测） | 本文件 §2 的试合并输出 |
