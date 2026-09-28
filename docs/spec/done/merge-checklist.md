# 合并检查清单：模块 3 / 蔡玉礼 的实现合入本分支时

**用途**：本分支（`feature/agent-xuchuan`）合并路径上的**已知风险与待办**。
每条都附了判定方法——合完逐条核，**别只看构建绿**。

**覆盖范围**（2026-09-28 扩过一次）：原先只针对模块 3 / 蔡玉礼的实现，
现在同时覆盖 **模块 5（杨睿坤的时段重叠修复）**、**模块 7（notify 真实实现）**、
以及**主干 `main` 的合并前置与顺序**（第 8、12 条是硬前提，不是功能待办）。

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

**2026-09-28：rebase 已执行（申云飞推 main 之后）**——`git rebase origin/main`
（目标 = `2fd726e`），62 个提交重放，**只在上表这 3 个文件上停下**，一处不多：

| 文件 | 实测冲突性质 | 处置 | 依据 |
| --- | --- | --- | --- |
| `app/agent/prompts/image_prompt.py` | 两边对**同一批超长中文 Prompt** 各折行一次（起点同为 `a98c556`） | **取 main 版** | 三份（merge-base / main / 本分支）的 `ast.dump` **逐字节相同**，且两个字符串常量取值逐字相同 → 纯格式，取谁都不丢语义 |
| `app/api/v1/__init__.py` | 本分支多一行 `agent.router` 注册（main 只有 voice / image 两行） | **取并集**：main 两行 + `agent.router` 一行 | 该文件 docstring 自己写着「补回 `agent.router` 的注册」；只取 main 版会让 `from app.api.v1 import agent` 成为未使用导入（F401）、且 `/api/v1/agent` 路由整块消失 |
| `app/core/exceptions.py` | **两侧代码行完全相同**（`ErrorCode.RESOURCE_CONFLICT: 409,`），只有上方注释措辞不同 | **取 main 版**（`git checkout --ours --`） | main 那份是集成侧的裁定文案（`6e3c8e1`）；取它后本文件与 `origin/main` **逐字节相同** → 第 1 条担心的「留成两条」在 rebase 这条路径上不可能发生 |

rebase 后实测：merge-base = `2fd726e`、落后 main 0 / 领先 62、`git status` 干净、
`pytest -q` 全绿。回滚点：`backup/pre-rebase-3-20260928`（= rebase 前的 `295f624`）。
⚠️ **一处自己造成的返工（记下来免得再犯）**：并集解完我按 **3 空格**对齐写了那三行注释，
而 `ruff format` 要 **2 空格**（正是 main 的形态）——`ruff format --check app/api/v1/__init__.py`
当场报 `would be reformatted`。已改为 2 空格。**「与 main 相同的行，原样照抄」比「对齐好看」重要。**

**main 上还缺整块东西**：

- `backend/app/api/v1/` 只有 `__init__ / auth / health / image / mock / mock_data / monitor / voice`
  ——**没有 `agent.py`，也没有 `orders.py`**；
- `backend/app/services/` 没有 `order_service.py`、`space_service.py`、`device_service.py`。

即 **main 上既没有模块 3 的真实现，也没有模块 4 的入口**。把本分支合进 main，
只是把模块 4 的代码搬到一棵缺模块 3 的树上，**演示主线仍然跑不通**。
（这也是「合并目标该是 `develop` 还是 `main`」必须在项目群定的原因，见
`stage-09-10-prep.md` §3。）

---

## 8. `space_service.py` 的「**静默消失**」风险 —— 比 add/add 更隐蔽 ⚠️⚠️

- **物理事实（2026-09-28 实测）**：`backend/app/services/space_service.py` **只存在于
  本分支**（及其派生的 `origin/feature/ruikun-space-overlap`）。`origin/main` 与
  `origin/feat/module3-caiyuli` / `origin/integrate/module3` **都没有这个文件**。
- **为什么比第 2 条更危险**：`notify_service.py` 是 add/add，**git 至少会报冲突**；
  而一个只在单边存在的文件，只要合并路径**绕开本分支**（例如「把模块 5 的真实现
  直接合进 main」或「从 main 拉新分支再挑拣」），它就**不报冲突、直接不在**——
  **连同杨睿坤这次的时段重叠修复一起消失**，而 CI 是绿的（没人 import 它就不会红）。
- **同类还有**：`device_service.py`（模块 5 的设备查询桩，同样只在本分支）。
- **怎么核**（合并**前**先立基线，合并**后**逐条比对）：

  ```bash
  git ls-tree --name-only origin/main -- backend/app/services/space_service.py   # 期望：空
  git ls-tree --name-only origin/feat/module3-caiyuli -- backend/app/services/space_service.py  # 期望：空
  git ls-tree --name-only origin/feature/agent-xuchuan -- backend/app/services/space_service.py # 期望：有
  # 合并后（在目标分支上）：
  git grep -n "occupied_space_ids" -- backend/app/services/space_service.py      # 期望：命中（时段重叠修复还在）
  git grep -n "def _parse_time" -- backend/app/services/space_service.py         # 期望：命中
  ```

- **处置**：**合并必须经本分支**（把本分支合进目标分支），或**显式 cherry-pick**
  `space_service.py` 与 `device_service.py` 两个文件。**不要用「挑提交」的方式绕**——
  绕过的路径上没有任何机制会提醒少了一个文件。

### 8.1 `services/` 目录结构事实（三边对照）

| 文件 | `origin/main` | 蔡 `feat/module3-caiyuli` | 本分支（模块 4） |
| --- | --- | --- | --- |
| `__init__.py` | ✅ | ✅ | ✅（含 5 条 re-export，见第 2 条） |
| `asr_service.py` | ✅ | ✅ | ✅ |
| `format_service.py` | ✅ | ✅ | ✅ |
| `image_service.py` / `image_storage.py` | ✅ | ✅ | ✅ |
| `monitor_service.py` / `risk_service.py` | ✅ | —（蔡分支无） | ✅ |
| `auth_service.py` | ✅ | — | ✅ |
| `message_service.py` | — | ✅ | — |
| `agent_client.py` | — | ✅ | — |
| **`order_service.py`** | ❌ **无** | ✅ **真实现** | ✅ **桩**（合并必冲突，桩要整体让位） |
| **`space_service.py`** | ❌ **无** | ❌ **无** | ✅ **桩 + 杨睿坤的时段重叠修复** |
| **`device_service.py`** | ❌ **无** | ❌ **无** | ✅ 桩 |
| **`notify_service.py`** | ❌ **无** | ❌ **无** | ✅ 桩（模块 7 侧另有真实现 → add/add，见第 2 条） |
| **`agent_service.py`** | ❌ **无** | ❌ **无** | ✅ 模块 4 自己的 |

**两条结论**：
1. **`order_service.py` 是本分支与蔡分支「同路径、两个都非空」的唯一一处**——
   我们的是桩、他的是真实现，合并后**必须整体取他的**（我们的桩的所有权到此为止）。
   牵连：第 3 条那个 `CONFLICT_DEVICE_SHORTAGE` 常量、以及我们的
   `test_agent_concurrency.py` 的导入，都要在**取他版本之后**逐个复核。
2. **`space_service.py` 的落点取决于合并顺序**：若先合模块 5/杨的分支再合本分支，
   本分支的这份会与杨那份在同一路径相遇（同源，通常干净）；若合并路径绕过本分支，
   它就直接不在（见本节开头）。

## 9. `app/models/reservation.py` 与蔡玉礼分支**必冲突** ⚠️

- **在哪**：`backend/app/models/reservation.py`。蔡分支已把占用口径收敛到该文件
  （`ACTIVE_ORDER_STATUSES`，见第 10 条）；杨睿坤的时段重叠修复又在**同一个文件**加了
  `OCCUPYING_STATUS`。**同文件、同主题、两侧都改** → 合并必冲突。
- ⚠️ **更正（2026-09-28，杨睿坤指出 + 我们实测复核）**：先前记的「本文件**直接取蔡玉礼
  版本**」是**错的**——「蔡玉礼版本」有两个 ref，内容差得很远：

  | ref | blob | `__table_args__` | `Index(` | `idx_` | 说明 |
  | --- | --- | --- | --- | --- | --- |
  | `origin/main` | `e51a9dfe` | 1 | **4** | 8 | 四条索引声明（`idx_user_id` / `idx_space_time` / `idx_status` / `idx_status_start`，`:64-68`） |
  | **本分支** | `e51a9dfe` | 1 | **4** | 8 | **与 main 逐字节相同**（本分支在这个文件上没有自己的改动） |
  | `origin/feat/module3-caiyuli` | `1005e27b` | **0** | **0** | **0** | **旧版**：四条索引声明一条都没有，他分支也没有建索引的迁移；还丢了 `PK_TYPE`（退回 `BigInteger`）、把 `device_ids`/`agent_trace` 的 `list` 标注改回 `dict` |
  | `origin/integrate/module3` | `92f546c7` | 1 | **4** | 8 | = **main 版 + `ACTIVE_ORDER_STATUSES` 共 21 行、删除 0 行** → **main 的干净超集** |
  | `origin/feature/ruikun-space-overlap` | `795d3496` | 1 | **4** | 8 | 本分支版 + 杨的 `OCCUPYING_STATUS` |

  **盲取 `feat/module3-caiyuli` 版的后果（静默，CI 不会红）**：四条 `Index` 声明从模型层消失
  ——**库里的索引还在**，但模型不再声明它，`alembic revision --autogenerate` 之后会**反过来
  提议 `DROP INDEX`**；顺带丢掉 `PK_TYPE`（模块 3 对团队版的唯一偏离，见 `core/database.py`）
  与两处 `list` 标注。**没有测试会拦住这些**。
- **正确做法**：**三方合并**，最终版本须同时含：
  1. **`ACTIVE_ORDER_STATUSES`**（蔡的写法，用 `OrderStatus.PENDING/CONFIRMED` 枚举成员，不写字面量）
     —— 本轮收敛的唯一真值，见第 10 条；
  2. **main 的四条 `Index` 声明**；
  3. `PK_TYPE` 主键与 `device_ids` / `agent_trace` 的 **`list`** 标注（这两项**本来就是 main 版的**，
     不是蔡带来的 —— 杨的更正里把它们记成「蔡的」，此处按实测更正归属，**要求本身不变：最终必须有**）；
  4. **删掉** `OCCUPYING_STATUS` 定义及其整段注释（注释里已写好这三步，见杨睿坤 `fd6910d`）。
  **最省事的等价做法**：直接取 `origin/integrate/module3` 那一版（它是 main 的超集，四条索引
  与 `PK_TYPE` 都在），再把 `space_service.py` / `test_space_service.py` 改用名（见下）。
- **然后改 2 处**：
  1. **`app/services/space_service.py`**：`from app.models.reservation import OCCUPYING_STATUS, ...`
     → 取 `ACTIVE_ORDER_STATUSES`；查询里的 `ReserveOrder.order_status.in_(OCCUPYING_STATUS)`
     同步改（实测当前在 `space_service.py:35` 与 `:132`）。
  2. **`backend/tests/test_space_service.py`**：护栏用例
     `test_occupying_status_matches_order_service` 改为断言 `ACTIVE_ORDER_STATUSES`
     （用例名与 docstring 一并改，别再叫「matches_order_service」）。
- **怎么核**（第一条是这次更正的重点——**数一数 `Index(`**）：

  ```bash
  for R in origin/main origin/feature/agent-xuchuan origin/integrate/module3 origin/feat/module3-caiyuli; do
    printf "%-40s Index( = %s\n" "$R" \
      "$(git show $R:backend/app/models/reservation.py | grep -c 'Index(')"
  done   # 期望：前三个都 4；feat/module3-caiyuli 是 0（旧版，别取它）
  # 合并后（在目标分支上）：
  git grep -c "Index(" -- backend/app/models/reservation.py          # 期望：4
  git grep -c "ACTIVE_ORDER_STATUSES" -- backend/app/models/reservation.py  # 期望：≥1
  git grep -n "OCCUPYING_STATUS" -- backend/app                       # 期望：0 命中
  pytest backend/tests/test_space_service.py -q --no-cov              # 期望：23 passed
  ```
- **反面**：保留我们的 `OCCUPYING_STATUS` 不改 → 全仓出现两套占用口径，且**没人知道
  哪份生效**——杨的护栏只钉「模型层 == 模块 3 `order_service`」，**钉不到蔡那份**。

## 10. 占用口径常量：四处并存，收敛到蔡玉礼的 `ACTIVE_ORDER_STATUSES`

**（2026-09-28 裁定：本次不预先改名，合并时一次性收敛。）**

| # | 位置 | 名字 | 取值 | 谁能钉住它 |
| --- | --- | --- | --- | --- |
| 1 | 本分支 `app/services/order_service.py:47` | `OCCUPYING_STATUS = (1, 2)` | 字面量 | 杨的护栏钉的是第 2 处 vs **本处** |
| 2 | 杨分支 `app/models/reservation.py:49` | `OCCUPYING_STATUS = (1, 2)` | 字面量 | 上面那条护栏的另一端 |
| 3 | 模块 7 `app/services/rules/base.py:46` | `ACTIVE_ORDER_STATUSES = (1, 2)` | 字面量 | **无人钉**（模块 7 自己一份） |
| 4 | **蔡玉礼 `app/models/reservation.py:34`（`integrate/module3` `:29`）** | `ACTIVE_ORDER_STATUSES` | `(OrderStatus.PENDING.value, OrderStatus.CONFIRMED.value)` | 蔡自己的注释即权威 |

- **三处值是否都等于 `(1, 2)`**：**是**（第 4 处用枚举成员表达，值同为 `(1, 2)`；
  其定义处注释明写「这里是当前**唯一**的占用口径真值」，`order_service` §5.5 第 3/4 步、
  `api/conflicts.py`、`api/agent.py` 四处共用）。
- **命名建议（收敛方向）**：**统一到 `ACTIVE_ORDER_STATUSES`**，落地在
  `app/models/reservation.py` 一条定义，其余三处改 import——理由：① 蔡那份是唯一
  在**模型层**、且已声明为真值的；② 用枚举成员比字面量 `(1, 2)` 抗漂移；
  ③ `OCCUPYING_STATUS` 与 `_ALLOWED_CREATE_STATUS`（`order_service.py`，含义是
  「创建时允许传入的状态」）语义不同，**别合并**——蔡的注释专门警告过这一点。
- **⚠️ 一处需在群里更正的既有说法**：先前流传的「模块 4 `space_service.py`（桩）里有
  `OCCUPYING_STATUS`」**不实**——实测 `space_service.py` 里**没有**该常量（桩不按时段过滤，
  只筛 `status / space_type / capacity`），定义在 **`order_service.py:47`**。四处的位置以上表为准。

## 11. `order_service.py` 合入时必须过 ruff ⚠️

- **他为什么一个字没动**（杨睿坤的说法，**已实测属实**）：
  `app/services/order_service.py` 现状 **`ruff check` 通过、`ruff format --check` 不通过**
  （`ruff 0.16.9`）。动它就会被 pre-commit 的 `ruff-format` 钩子连带重排，
  给正在改这个文件的人制造无关冲突。
- **实测证据**：

  ```bash
  ruff check app/services/order_service.py          # All checks passed!
  ruff format --check app/services/order_service.py # 1 file would be reformatted
  ```

  它想改的是：模块 docstring 后的空行、一组**用空格对齐的行尾注释**（`:59-68`）、
  以及 `:282` 那个列表推导的换行。**纯格式，零语义**。
- **这债是谁的**：文件是**模块 3 的交付物**（`order_service` 属模块 3），但
  `git log -1` 显示当前内容**最后一次改动是我们**（`41c9941` / `4706b6b` 的桩），
  即**桩是我们写的**，格式债随桩而来。当时 ruff 清理只覆盖了模块 4 自己的文件
  （`app/agent/**`、`app/schemas/agent.py`、`app/api/v1/agent.py`、`app/services/agent_service.py`、
  `tests/test_agent_*.py`）——按「不碰别人模块文件」的约束**故意没动它**。
- **处置**：**合并时**（蔡的真实现替换掉这份桩之后）跑一次
  `cd backend && ruff format app/services/order_service.py && ruff check app/services/order_service.py`。
  **本次不预先修**：修了也是被整体替换掉的代码，白造一次冲突。
- **同类（本分支范围内、同样「check 过 / format 不过」的我们的桩文件）**：
  `app/services/__init__.py`、`app/services/device_service.py`、`app/services/notify_service.py`、
  `app/services/space_service.py`——都是「模块 docstring 后缺空行」这类，
  **随各自的真实现落地时一并消失**，本次同样不动。
  （本模块自己的 22 个文件 `ruff check` / `format --check` 全绿，已复核。）

## 12. 次序硬约束：**模块 7 的 v3 必须先落 `main`，本分支再合** ⚠️⚠️

- **事实**：`origin/main` **根本没有** `backend/app/services/notify_service.py`
  （第 8.1 节表里那一行 ❌），而本分支的 `services/__init__.py:34-37` re-export 了
  `generate_notification`（见第 2 条）。
- **顺序反了的后果**：先合本分支 → main 上有了 re-export 却没有那个函数 →
  `import app.services.*` 处 **ImportError** → **工具层全线崩**。
  所以不是「建议先」而是**硬约束**。
- **解该冲突的取法**：**取模块 7 的真实实现 + 保留那 4 行 re-export**；
  ⚠️ **取桩会让模块 7 的真实实现静默消失**（桩也是「合法」的一份文件，git 不再报错）。
- **怎么核**：

  ```bash
  git ls-tree --name-only origin/main -- backend/app/services/notify_service.py  # 合模块 7 前：空；之后：有
  git grep -n "def generate_notification" -- backend/app/services/notify_service.py   # 必须 1 处
  git grep -n "generate_notification" -- backend/app/services/__init__.py             # re-export 还在
  cd backend && python -c "import app.services"                                       # 不报 ImportError
  ```

## 13. 「3 处」与「17 处」是两个问题，**别互相套**

| 数 | 是什么 | 基点 | 复现命令 |
| --- | --- | --- | --- |
| **3 处** | **本分支** × `main` | `98c54ea4` | `git merge-tree --write-tree origin/main backup/pre-rebase-3-20260928` |
| **17 处** | **模块 7 `integ/module7-into-main`** × `main` | `6f6f6ff` | `git merge-tree --write-tree origin/main origin/integ/module7-into-main` |

两个数**都已实测复现**（各 3 条、17 条 `CONFLICT` 行；17 处里含 4 条 add/add：
`core/__init__.py`、`core/security.py`、`schemas/common.py`、`tests/__init__.py` 等）。
差异来源是**分支不同**（本分支 vs 模块 7 的集成分支）、**基点不同**（`98c54ea` vs `6f6f6ff`），
不是谁数错了。**引用时必须带上是哪两条分支**，否则「模块 4 说 3 处、模块 7 说 17 处」会变成
互相矛盾的口径。

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
| 模块 7 真实现的返回形状与异常口径（第 2、12 条） | `origin/feat/module7-conflict-notify:backend/app/services/notify_service.py:575-645`（`:605-607` 是 `try/except` 转 `ok=False`，`:637-642` 是成功返回含驼峰 `notifyType`、无 `stub`） |
| 杨睿坤时段重叠修复的核对（第 8、9、10 条） | 临时分支 `tmp-verify-overlap`（= `origin/feature/ruikun-space-overlap` @ `fd6910d`，**用后即删、未推**）实测：`pytest backend/tests/test_space_service.py` **23 passed**，含他点名的 4 条（`test_occupying_status_excludes[1]` / `[2]` / `test_touching_intervals_do_not_count_as_overlap` / `test_stage03_reported_case_is_fixed`） |
| 占用口径四处定义、`services/` 结构表（第 8.1、10 条） | 本节 §8.1 / §10 的 `git grep -n`、`git ls-tree` 原始输出 |
| 四条 `Index` 声明与各 ref 对照（第 9 条更正） | 本节 §9 的 `git show <ref>:...reservation.py \| grep -c 'Index('` 输出；`git diff --stat origin/main origin/integrate/module3 -- backend/app/models/reservation.py` = **+21 / −0** |
| 「3 处 / 17 处」复现（第 13 条） | 本节 §13 的 `git merge-tree --write-tree` 输出 |
| `order_service.py` 的 ruff 现状（第 11 条） | `ruff 0.16.9`（conda 环境 `smart_dev`）在本分支实测：check 通过、format 不过 |
| 本分支 rebase 到 `main` 的实测（第 7 节） | 本节 §7 的 rebase 输出；回滚点 `backup/pre-rebase-3-20260928` |
