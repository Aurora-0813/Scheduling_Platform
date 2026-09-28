# 阶段完成文档归档

> ✅ **本目录已入库**（2026-09-27 起）。`.gitignore` 以 `docs/spec/*` + `!docs/spec/done/`
> 放行本目录下的完成文档；计划书、阶段任务书与模板**仍仅本地保留**。
>
> 该放行是 `done/stage-10-completion.md` 第 5 节**方案 B 的提前落地，项目群裁定尚未追认**——
> 若裁定推翻，回滚 `.gitignore` 那两行即可。
>
> 注意 `docs/spec/*` 的写法不能写成 `docs/spec/`：父目录被排除后 git 不会进入该目录，
> `!` 白名单会失效。原因已写在 `.gitignore` 原位注释里。

每个阶段验收测试通过后，把 `docs/spec/templates/stage-completion-template.md`
复制到本目录，命名为 `stage-NN-completion.md`（NN 与阶段号一致，如 `stage-00-completion.md`），**当天填完**。

- 补写的完成文档没有证据价值——证据要趁热留
- 阶段 7 的完成文档**必须附覆盖率报告的完整原始输出**，不接受"已通过"三个字
- 偏离计划之处必须如实写：工时超了、范围砍了、验收标准被迫放宽，都要记

完成后回到 `docs/spec/README.md` 第 5 节更新阶段状态表，**并把下表同步一遍**（见下方说明）。

---

## 当前状态（团队可见副本）

> 本表是 `docs/spec/README.md` 第 5 节的**副本**。那份文件随整个 `docs/spec/`
> 一起被 `.gitignore` 排除（本地保留），团队在仓库里看不到，所以在这里放一份。
> **改一处必须改两处**：阶段状态变动时，先改本地那份（它是工作稿），再同步到本表。

| 阶段 | 状态 | 完成文档 | 备注 |
| --- | --- | --- | --- |
| 0 前置条件核对 | **部分解除** | [stage-00](stage-00-completion.md) | 原阻塞三条：种子数据**已导入**（场地 8 / 设备 15 / 预约 10，与 6.9 一致）；`backend/.env` **已建、LLM 三项已填且实测可用**（`qwen-plus` + DashScope 兼容模式，2026-09-27 真实调用跑通）；DDL 未执行（表已存在，疑由 M1 建表脚本带入，**待集成组确认**） |
| 1 环境与骨架 | **通过** | [stage-01](stage-01-completion.md) | 依赖装齐、锁文件生成（此前为空文件） |
| 2 契约冻结 | **有条件通过** | [stage-02](stage-02-completion.md) | schema 与 `docs/api.md` 已交付；**缺前端书面回执** |
| 3 依赖就绪度 | **通过** | [stage-03](stage-03-completion.md) | M1 的 `config.py` + `database.py` 已就位，据此产出 service 桩。注：集成组正式版就位前，模块 4 在阶段 6 自行补出了 `core/response.py`、`core/security.py`，见阶段 6 偏离 #2 |
| 4 Tool 层 | **有条件通过** | [stage-04](stage-04-completion.md) | 5 个 Tool 全部落地、三条禁令未破；验收步骤 ①⑤ 依赖阶段 7 用例，改以等价手段取证 |
| 5 Prompt 与组装 | **不通过**（**待重判**） | [stage-05](stage-05-completion.md) | 真实 API 冒烟**已跑通**（`qwen-plus`，4 步 trace / 18.3 秒 / `success=true`），四条通过标准达成 3 条。**差的那条「设备降级为单投影」前提不成立**——`device_resource` 无价格字段，「预算与设备冲突」算不出来，模型交出双投影并说明「无需降级」，判断自洽。**该标准已按裁定 A + C 改写**（硬卡点 #1 已闭环），**状态待重判**。两次冒烟原始输出见 stage-05 §3.1 / §3.2。另暴露：「下周三」被算成 10-04（应 09-30，已做 Prompt 缓解）；真实路径未调 `lock_resources`（已裁定 (a)，Prompt 与 Tool 描述均已改） |
| 6 API 层 | **有条件通过** | [stage-06](stage-06-completion.md) | 六步验收全部执行且符合标准；埋点为进程内计数、正常路径实测在注入假模型下完成 |
| 7 测试 | **有条件通过** | [stage-07](stage-07-completion.md) | **84 例通过 + 2 例 `xfail(strict)`**（新增 `AGENT-S-06` 及其前提护栏两条）；`app/agent` 覆盖率 **92.37%**（阈值 80% 已入 `pytest.ini`）。**`AGENT-C-01/02` 未通过**——模块 3 的 `create_order` 仍是只读桩，标 `xfail(strict)` 并登记在案，不当作通过。另两条限制：`AGENT-S-01~06` 只验了透传与形状（决策质量需真实 LLM，`.env` 三项为空）；`db_session` 连的是只读开发库而非测试库。**阶段 7 完成文档里记的仍是 82 例 / 92.29%**，那是当时的原始输出，不改写 |
| 8 联调准备 | **不通过** | [stage-08](stage-08-completion.md) | mock 数据与路由已交付且实测；**交接清单五项回执一项都没有**（需真实沟通，非代码可替代） |
| 9 提交与合并 | 未开始 | — | 入口条件未满足（阶段 8 不通过），但验收内容（`.env` 不入库、CI 绿灯、tag）与之互不阻塞，可并行 |
| 10 交接与后续 | 未开始 | — | |

状态取值：未开始 / 进行中 / 通过 / 有条件通过 / 阻塞（阻塞须注明 blockers 与责任人）。

### 当前硬卡点（按紧急度）

| # | 卡点 | 影响 | 责任人 |
| --- | --- | --- | --- |
| 1 | **场景 A 的验收标准「设备降级为单投影」前提不成立**（`device_resource` 无价格字段，设备不计费，「预算与设备冲突」没有可计算依据） | **已裁定 A + C（2026-09-27 项目群），本项闭环**：A 把标准改为「保住场地 + 说明为何不需降级」，C 另补一条前提真成立的降级用例。已落地：`AGENT-S-01` 断言改写为「`plan` 非空 / `spaceId` 命中 / `reason` 非空且说明无需降级」，新增 `AGENT-S-06`（要两台直播设备、库里只有 1 台可借）及前提护栏 `test_seed_supports_the_degradation_case`。**选项 B（补设备单价口径）未采纳**，留在集成组账上 | 集成组（数据模型 / 总预算口径）+ 徐川（标准措辞） |
| 2 | 阶段 8 五项交接回执全空 | 联调当天才会暴露口径不一致，而这正是阶段 8 存在的意义 | 徐川（发起）+ 蔡玉礼 / 杨睿坤 / 黄嵩 / 前端 / 申云飞（回执） |
| 3 | 模块 3 的 `create_order` 仍是只读桩（`orderId` 恒为 `None`） | 并发与库存扣减（`AGENT-C-01/02`）无法验证——**阶段 7 因此未完全达标**；`agent_trace` 补写链路只能走到「跳过」分支。**补充（2026-09-27）**：① `needConfirm` 已裁定 **(a)**（Agent 一轮内锁 `status=1`，确认只是 1→2 的流转），**但 1→2 这段还没接通**——`PUT /api/v1/orders/{orderId}/confirm` 已在 `origin/feat/module3-caiyuli` 上实现，而 `/api/v1/agent/schedule` 的响应体**不透出 `orderId`**（只有 `plan`/`backupPlan`/`trace`/`needConfirm`），前端拿不到订单号。**该条已实现（`d626966`，2026-09-27）**：`ScheduleData` 新增 `orderId`，取自最后一次成功的 `lock_resources`，降级路径**照样透出**（`plan` 为空但已锁单时仍报，避免落库的单成孤儿）；`docs/api.md` 模块 4 的 data 结构表、示例与 mock 已同步。**仍未接通**的是端到端那一段——本分支的 `create_order` 还是桩，真值要等模块 3 并库；② 蔡玉礼的真实现已在 `origin/feat/module3-caiyuli` 分支上（`core/utils.py` / `state_machine.py` / `ACTIVE_ORDER_STATUSES` 三样本分支**都没有**），等并入 `main` | 蔡玉礼（推）+ 集成组（合入） |
| 4 | `smart_scheduler_test` 访问被拒 | 模块 4 的 `dev_db_session` 只能连只读开发库（强制手段已实现：`_db_readonly_guard` 前置拒绝全部写语句）。**但它同时会把并发用例要验的真实写入一起打死**——测试库权限到位后须对本用例收窄拦截，否则 `AGENT-C-01/02` 仍过不了。**合并后（2026-09-28）夹具分成两套**：正式版的 `db_session` / `client` 走 SQLite 空库（全离线），模块 4 的改名为 `dev_db_session` / `dev_client` 走开发库——两者名字不能再合并，理由写在同一文件 `tests/conftest.py` 的模块 4 段开头 | 申云飞 |
| 5 | ~~`available_count` 扣减/回补口径未定~~ → **口径已定：用时推导，不扣减（2026-09-28 蔡玉礼给出，方案接受）** | **口径（四条，见下方附录）**：① `available_count` 是**静态上限**，不是实时剩余；② **剩余量 = `available_count` − 该时段重叠订单数**（算出来的，不是存的）；③ **不扣减、不回补、不加 §5.5 第 7 步**；④ 取消后名额**自动回来**，无需任何回补代码。<br>**对 `AGENT-C-01/02` 的影响**：C-02 的原判据「锁定后 `available_count` 递减」**作废**——字段本来就不该变，断言它变才是在验一个不存在的实现。新判据照蔡玉礼的 7 条断言改，见附录。<br>**仍未闭环的部分**：判据明确了，**真实现还没到**——`order_service.py` 的 `_device_conflicts` 要按「时段重叠」推导剩余量（蔡玉礼改），且 `_db_readonly_guard` 仍拦真库写入（测试库权限未到位）。**故 C-01/02 继续 `xfail(strict)`，注明「等蔡玉礼改 `_device_conflicts`」**。阶段 7 仍未完全达标 | 蔡玉礼（`_device_conflicts` 实现）+ 申云飞（测试库权限） |

| 6 | ~~`backend/.env.example` 出厂即 `AUTH_BYPASS=true`~~ **已在 `origin/main` 修复，且已随合并消解，本项闭环** | 本分支的 `backend/.env.example:45` 仍是 `AUTH_BYPASS=true`（`2474343`「贾世杰：完成模块」），任何人 `cp` 即带放行模式；**但集成组已在 `origin/main`（`9f30d3a`，2026-09-28）改掉**：`.env.example:125` 为 `false`，`config.py:297` 另加硬拦——`AUTH_BYPASS=true` 且非 dev 环境直接报错。**2026-09-28 已 rebase 到 `9f30d3a`，合并后本分支 `.env.example:125` 实测为 `false`，该项自然消解。** 本机 `backend/.env` 未显式设置该项，取 `config.py` 默认 `False`。**裁定：暂缓，不阻塞推送**（已报项目群，报告当日即由集成组闭环） | 集成组（**已完成**）+ 徐川（答辩/部署前自检 `.env` 实为 `false`） |
| 7 | **同名实现：三份 `get_current_user`、两份 `register_exception_handlers`、两份路由注册中枢** | **本项已在合并中闭环（2026-09-28，rebase 到 `9f30d3a`）**。身份依赖：模块 4 的两份已先删掉（`cfb75f0` 删 `core/security.py` 的 `CurrentUser` / `get_current_user`，`dcc89e7` 把 agent 改指 `api/deps.py`），合并时冲突直接取正式版，**全应用只剩 `api/deps.py` 一份**；异常体系：`register_exception_handlers` 收敛到 `core/response.py`，`core/exceptions.py` 只留 `BizError` 层级与码表。**模块 4 自建的 `core/response.py::ApiError` / `CODE_OK` 与 `core/security.py::create_access_token` / `create_refresh_token` 在正式版里都不存在**，调用点已就地改掉：`api/v1/agent.py` 的 503 路径改用 `BusinessError(code=41003)`（正式版码表里 41003 已映射 503），路由补上 `response_model=ApiResponse[ScheduleData]`（原先写 `-> dict` 返回值注解，正式版严格校验会把它判成 500）；用例改用 `create_token` / `ErrorCode`。路由中枢：`api/v1/router.py`（模块 4 的第二份）已删除，只留 `api/v1/__init__.py` | 徐川（**已完成**） |
| 8 | **本机 `smart_dev` 环境缺 `requirements.txt` 已声明的测试依赖（`aiosqlite==0.22.1` / `alembic==1.20.0`）** | 合并前只有模块 4 的用例跑得动（连真库、不用 SQLite），正式版重写的 `conftest` 与 image / voice / auth 用例全部依赖 `aiosqlite`，缺失时**整个套件在收集阶段就 ERROR**，红数无从谈起（此前记的「image/voice 用例继承红」根因即此）。**本次已在本机补装这两项**（`pip install --no-deps aiosqlite==0.22.1 alembic==1.20.0 Mako MarkupSafe`，未动其他依赖）。<br>⚠️ **2026-09-28 更正——原先「`backend/alembic/` 遮蔽同名包」的结论是错的，申云飞复现不到并给出三条反证，我复核后确认他对我错**：`import alembic` 解析到 `site-packages\alembic\__init__.py`；`python -m alembic --version` 在仓库根与 `backend/` 下**都是 1.20.0、退出码 0**；`alembic.__main__` 确实存在于 site-packages。原因是 `backend/alembic/` 无 `__init__.py`、只能算**命名空间包**，而命名空间包在整条 `sys.path` 扫完之前**只是候选**，命中 site-packages 的**常规包**即让位——**不构成遮蔽**。当时报 `No module named 'alembic.autogenerate'` 的真实原因就是 `alembic` **没装**。**补装后 `tests/integration/test_migrations.py` 收集 8 例、8 passed，无需任何仓库结构改动。本项闭环。** | 徐川（本机补装，**已完成**） |
| 9 | ~~模块 4 的 mock / 监控两处契约，被 `origin/main` 的正式版实现推翻~~ → **mock 数据源已统一，本项闭环（`25b3ee3`，2026-09-28）** | **（2026-09-28 合并后登记，同日闭环）** 合并时 `api/v1/mock.py` / `mock_data.py` / `api/v1/monitor.py` 均取正式版（模块 4 的分支版只有本模块一段，覆盖会删掉模块 5/6/7/8/10 的 mock 路由）。<br>①**mock 响应体**（原「4 步 vs 7 步」不一致）——**集成组已在 `25b3ee3` 修掉**：`mock_data.AGENT_SCHEDULE` 改为**读 `docs/mock/agent_schedule.json` 的 `data` 段**，json 成为唯一真源，响应体随之从 4 步变 **7 步**。路径解析兼容两种检出布局（仓库根 `docs/mock/` 优先，`backend/` 独立检出退回 `backend/docs/mock/`），都读不到则打 ERROR 日志并返回空 `data`（不让演示数据缺失把应用启动带崩，交给用例暴露）。**本分支 rebase 到 `25b3ee3` 时该 json 已由对方并入，本模块那个创建 json 的提交被 git 判定为 `already upstream` 自动丢弃，无冲突。** 核对结果：`api/v1/mock.py` 两边**零差异**；唯一差异是 json 多一行 `"orderId": 101`（本分支 `27d9156` 加的，属冻结契约字段），是**超集**不是冲突。新增的 `tests/api/test_agent_schedule_mock.py`（7 例）**已跑过，全绿**。<br>②**监控口径四处不同**（不鉴权 / `avgLatency` 单位秒 / `successRate` 按 HTTP 状态码 / Redis 存储）——**已按正式版改写 `docs/api.md` 模块 10 整节**，并有回归用例兜底。这一半不是缺陷，是模块 4 的文档原本落后于正式版实现，改文档即闭环。<br>**遗留（另立）**：模块 4 的 `agent_service.record_call` 已无读端（`agent.py` 仍在调），属待清理项 | 申云飞（mock 唯一真源，**已完成**）+ 徐川（文档已改完；`record_call` 清理待裁定） |

原「阶段 3 唯一硬卡点」（`backend/app/core/` 为空）**已解除**：`config.py` 与 `database.py` 已就位，阶段 3 据此通过。

### 附录：`available_count` 口径（2026-09-28 蔡玉礼给出，方案接受）

> 本附录是硬卡点 #5 的正式口径记录。**后续任何关于设备库存的判定、文档措辞与用例断言，
> 一律以本节为准**；与它冲突的旧表述（含 `docs/spec/stage-04-tools.md` 与模块 3 分支上
> `docs/待集成组确认清单.md` P2 节的「待定」描述）均已作废。

**口径：用时推导，不扣减。**

| # | 规则 | 含义 |
| --- | --- | --- |
| 1 | `available_count` 是**静态上限**，不是实时剩余 | 它描述「这类设备总共有几台可借」，一旦导入就不再随下单变化 |
| 2 | **剩余量 = `available_count` − 该时段重叠订单数** | 剩余是**算出来的**，不是存下来的。统计口径是「与该时段重叠的订单」 |
| 3 | **不扣减、不回补、不加 §5.5 第 7 步** | 主文档 §5.5 的事务六步**保持六步**，不新增占用维护步骤 |
| 4 | 取消后名额**自动回来**，无需回补代码 | 订单不再是「重叠订单」，推导结果自然还原——不存在漏回补导致永久少库存的路径 |

**为什么取这个方案**：单方面扣减会造出**第二份真值**——场地/设备占用已经能从 `reserve_order`
按「状态 + 时间窗口」派生，再维护一个计数器就是同一件事存两遍，一旦不一致无法判断谁对。
用时推导天然不会产生两份真值，也天然与「过期订单不再占用」一致。这与模块 3 在
`docs/待集成组确认清单.md` P2 节里的**建议 (b)** 是同一件事，口径一致。

**对判据与用例的影响**：

- `AGENT-C-02` 的原判据「锁定后 `available_count` 正确递减、回滚时不减」**整条作废**——
  按本口径该字段根本不该变，断言它变是在验一个不存在的实现。新判据照下节的 7 条断言改。
- 硬卡点 #5 里「`AGENT-C-01/02` 的判据本身不存在」这一条**已解除**：判据现在存在了。
  但**真实现仍未到位**，C-01/02 继续 `xfail(strict)`，详见下表。

**蔡玉礼的判据文档（7 条断言）**

> ⚠️ **原文未到位**：蔡玉礼的判据文档**没有随本次消息传来，也不在仓库任何分支上**
> （已查 `origin/feature/agent-xuchuan`、`origin/main`、`origin/feat/module3-caiyuli`
> 三个分支的 tip 与近期提交，均无此文档；`origin/feat/module3-caiyuli` 的最新一份是
> `693ce0a`「补记合并实际执行结果与两处待集成组签字的口径」，其中的 P2 节是**提问**，
> 不是结论）。**为避免把推测写成他人结论，此处留空位、等原文补入**，不下笔。
> 补齐后本节直接贴在下面，并据此改写 `AGENT-C-01/02` 的断言。
>
> **我已能独立确认的一条**（见下）：第 3 条的 `409 + code=40901` **正式版里存在**，
> 不需要新造，详见下一节。

**已核实：`40901` 与 409 映射都在正式版里**

| 项 | 位置 | 实测 |
| --- | --- | --- |
| 业务码 `40901` | `backend/app/core/error_codes.py:72` | `RESOURCE_CONFLICT = 40901` ✅ |
| HTTP 映射 409 | `backend/app/core/exceptions.py:181-183` | `class ResourceConflictError(BizError)`，`code = ErrorCode.RESOURCE_CONFLICT`，`http_status = 409` ✅ |

同段还确认了 409xx 一族的其余三个（`CONFLICT = 40900` / `USERNAME_EXISTS = 40902` /
`ORDER_STATUS_CONFLICT = 40903`，同样各自 `http_status = 409`），因此 409 这一档
**不是只有 40901 能走**——判据里若出现 409 但码不是 40901，需按上表核对是不是撞了另外三个。
**无需新增任何码，也无需改 `error_codes.py` 或 `exceptions.py`。**

**仍卡着 C-01/02 真跑通的两件事**

| # | 卡点 | 归属 |
| --- | --- | --- |
| 1 | `order_service.py` 的 `_device_conflicts` 要按「时段重叠」推导剩余量（现在是 `available_count > 0` 的静态校验） | 蔡玉礼 |
| 2 | `smart_scheduler_test` 1044 无权 → `_db_readonly_guard` 仍拦真库写入；或改走降级路径 | 申云飞 |

### LLM 配置 baseline（模块 4 公布 · 2026-09-27）

模块 8 索要的 baseline，可直接照抄。**Key 各人各把，只放本地 `backend/.env`，不入库。**

| 项 | 取值 | 说明 |
| --- | --- | --- |
| `LLM_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | DashScope 的 OpenAI 兼容端点，公开 URL，不含凭据 |
| `LLM_MODEL_NAME` | `qwen-plus` | 全组统一取值。**模型必须支持 Function Calling** |
| `LLM_API_KEY` | 各自申请（DashScope） | 真实值只在本地 `.env`；仓库与文档一律占位 |
| `LLM_TEMPERATURE` | `0.0`（`settings` 默认） | 调度决策要可复现；调高会让同一需求两次给出不同方案 |
| `LLM_MAX_RETRIES` | `1`（`settings` 默认） | 外层已有 `AGENT_TIMEOUT` 兜底，重试不宜多 |

变量名三项已与模块 8 对齐。注意 `backend/.env` 由 `pydantic-settings` 读入，
**不是**导出到进程环境变量——直接用 `os.getenv("LLM_MODEL_NAME")` 会拿到 `None`。

**反例（已实测）：`qwen-math-turbo` 不可用。** 它是数学专用模型，无 Function Calling
能力，且输入上限 3072 token；本模块的 Prompt + 工具 schema 约 6968 字符，
实测直接 `400 InternalError.Algo.InvalidParameter`。换 `qwen-plus` 后跑通。
（2026-09-27，证据见 [stage-05](stage-05-completion.md) §3.1 / §3.2：4 步 trace、
18.3 秒、`success=true`。）

**未经实测、待模块 8 验证**：`with_structured_output` 在 langchain-openai 1.5.0 的
`method` 默认值是 `json_schema`（签名已确认），DashScope 是否接受该格式我方没有走过
这条路——本模块用的是 `create_agent` + Tool，不经过 `with_structured_output`。
