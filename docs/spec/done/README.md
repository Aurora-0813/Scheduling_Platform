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
| 4 Tool 层 | **通过** | [stage-04](stage-04-completion.md) | 5 个 Tool 全部落地、三条禁令未破。**2026-09-28 收口**：`AGENT-STAGE-04` 五项检查重跑一遍全过（`pytest tests/test_agent_tools.py` **31 passed**；`@router` 零匹配；`AsyncSession` 仅 3 处注释；注入 4 条构造数据只留健康样本）。原「步骤 ①⑤ 依赖阶段 7 用例」的挂账已由阶段 7 补齐并闭合，见 §3.6 |
| 5 Prompt 与组装 | **通过** | [stage-05](stage-05-completion.md) | **2026-09-28 按新标准 A 重跑真冒烟（§3.3）**：`qwen-plus` / 场景 A / `success=true` / `degraded=false` / 6 步 trace / 29.8 秒；`spaceId=4`、`deviceIds=[1,2]`、`reason` 逐条说明为何不需降级、时间戳真实间隔 7/7/2/4/4 秒——**四条全中**。沿革：第一次模型名不兼容 400（§3.1）、第二次`qwen-plus` 跑通但撞上前提不成立的旧标准（§3.2，其「只达成三条」判定已作废）。⚠️ 用的是**本地 `.env` 的 `qwen-plus`，全组 baseline 统一后需复验**；本次新暴露**超时余量仅 155 ms**（29.845 / 30.0 秒），建议演示环境放宽 `AGENT_TIMEOUT` |
| 6 API 层 | **通过** | [stage-06](stage-06-completion.md) | 六步验收全部执行且符合标准。**2026-09-28 重判**：原条件②「正常路径只在假模型下实测」已由阶段 5 真冒烟补齐（真实模型下 `degraded=false`）；原条件①「埋点为进程内计数」不构成本阶段卡点——线上口径是集成组正式版链路，本模块这套仅本地调试用，已列硬卡点表 #10（低优先、非阻塞） |
| 7 测试 | **有条件通过** | [stage-07](stage-07-completion.md) | **84 例通过 + 2 例 `xfail(strict)`**（新增 `AGENT-S-06` 及其前提护栏两条）；`app/agent` 覆盖率 **92.37%**（阈值 80% 已入 `pytest.ini`）。**`AGENT-C-01/02` 未通过**——模块 3 的 `create_order` 仍是只读桩，标 `xfail(strict)` 并登记在案，不当作通过。另两条限制：`AGENT-S-01~06` 只验了透传与形状（决策质量需真实 LLM，`.env` 三项为空）；`db_session` 连的是只读开发库而非测试库。**阶段 7 完成文档里记的仍是 82 例 / 92.29%**，那是当时的原始输出，不改写 |
| 8 联调准备 | **不通过** | [stage-08](stage-08-completion.md) | mock 数据与路由已交付且实测；**交接清单五项回执一项都没有**（需真实沟通，非代码可替代）。**2026-09-28 重判维持不通过**——阶段 4/5/6 均已改判通过，本阶段是全流程里**唯一仍判不通过**的一阶段 |
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
| 5 | ~~`available_count` 扣减/回补口径未定~~ → **口径已定：用时推导，不扣减（2026-09-28 蔡玉礼给出，方案接受）** | **口径（四条，见下方附录）**：① `available_count` 是**静态上限**，不是实时剩余；② **剩余量 = `available_count` − 该时段重叠订单数**（算出来的，不是存的）；③ **不扣减、不回补、不加 §5.5 第 7 步**；④ 取消后名额**自动回来**，无需任何回补代码。<br>**对 `AGENT-C-01/02` 的影响**：C-02 的原判据「锁定后 `available_count` 递减」**作废**——字段本来就不该变，断言它变才是在验一个不存在的实现。**新判据（蔡玉礼的 7 条断言）已 2026-09-28 逐条落地**到 `backend/tests/test_agent_concurrency.py`（10 例：7 条断言 + 1 条并发版 + 1 条 40901 契约 + 1 条桩期实录），见附录。<br>**仍未闭环的部分**：判据**写完了，真实现还没到**——`order_service.py` 的 `_device_conflicts` 要按「时段重叠」推导剩余量（蔡玉礼改），且 `_db_readonly_guard` 仍拦真库写入（测试库权限未到位）。**故 8 条断言继续 `xfail(strict)`，注明「等蔡玉礼改 `_device_conflicts`」**（实跑：518 passed / 8 xfailed，`--runxfail` 复核 8 条**都因桩不落库（`ok=True` 但 `orderId=None`）而失败**，非用例自身写错）。阶段 7 仍未完全达标 | 蔡玉礼（`_device_conflicts` 实现）+ 申云飞（测试库权限） |

| 6 | ~~`backend/.env.example` 出厂即 `AUTH_BYPASS=true`~~ **已在 `origin/main` 修复，且已随合并消解，本项闭环** | 本分支的 `backend/.env.example:45` 仍是 `AUTH_BYPASS=true`（`2474343`「贾世杰：完成模块」），任何人 `cp` 即带放行模式；**但集成组已在 `origin/main`（`9f30d3a`，2026-09-28）改掉**：`.env.example:125` 为 `false`，`config.py:297` 另加硬拦——`AUTH_BYPASS=true` 且非 dev 环境直接报错。**2026-09-28 已 rebase 到 `9f30d3a`，合并后本分支 `.env.example:125` 实测为 `false`，该项自然消解。** 本机 `backend/.env` 未显式设置该项，取 `config.py` 默认 `False`。**裁定：暂缓，不阻塞推送**（已报项目群，报告当日即由集成组闭环） | 集成组（**已完成**）+ 徐川（答辩/部署前自检 `.env` 实为 `false`） |
| 7 | **同名实现：三份 `get_current_user`、两份 `register_exception_handlers`、两份路由注册中枢** | **本项已在合并中闭环（2026-09-28，rebase 到 `9f30d3a`）**。身份依赖：模块 4 的两份已先删掉（`cfb75f0` 删 `core/security.py` 的 `CurrentUser` / `get_current_user`，`dcc89e7` 把 agent 改指 `api/deps.py`），合并时冲突直接取正式版，**全应用只剩 `api/deps.py` 一份**；异常体系：`register_exception_handlers` 收敛到 `core/response.py`，`core/exceptions.py` 只留 `BizError` 层级与码表。**模块 4 自建的 `core/response.py::ApiError` / `CODE_OK` 与 `core/security.py::create_access_token` / `create_refresh_token` 在正式版里都不存在**，调用点已就地改掉：`api/v1/agent.py` 的 503 路径改用 `BusinessError(code=41003)`（正式版码表里 41003 已映射 503），路由补上 `response_model=ApiResponse[ScheduleData]`（原先写 `-> dict` 返回值注解，正式版严格校验会把它判成 500）；用例改用 `create_token` / `ErrorCode`。路由中枢：`api/v1/router.py`（模块 4 的第二份）已删除，只留 `api/v1/__init__.py` | 徐川（**已完成**） |
| 8 | **本机 `smart_dev` 环境缺 `requirements.txt` 已声明的测试依赖（`aiosqlite==0.22.1` / `alembic==1.20.0`）** | 合并前只有模块 4 的用例跑得动（连真库、不用 SQLite），正式版重写的 `conftest` 与 image / voice / auth 用例全部依赖 `aiosqlite`，缺失时**整个套件在收集阶段就 ERROR**，红数无从谈起（此前记的「image/voice 用例继承红」根因即此）。**本次已在本机补装这两项**（`pip install --no-deps aiosqlite==0.22.1 alembic==1.20.0 Mako MarkupSafe`，未动其他依赖）。<br>⚠️ **2026-09-28 更正——原先「`backend/alembic/` 遮蔽同名包」的结论是错的，申云飞复现不到并给出三条反证，我复核后确认他对我错**：`import alembic` 解析到 `site-packages\alembic\__init__.py`；`python -m alembic --version` 在仓库根与 `backend/` 下**都是 1.20.0、退出码 0**；`alembic.__main__` 确实存在于 site-packages。原因是 `backend/alembic/` 无 `__init__.py`、只能算**命名空间包**，而命名空间包在整条 `sys.path` 扫完之前**只是候选**，命中 site-packages 的**常规包**即让位——**不构成遮蔽**。当时报 `No module named 'alembic.autogenerate'` 的真实原因就是 `alembic` **没装**。**补装后 `tests/integration/test_migrations.py` 收集 8 例、8 passed，无需任何仓库结构改动。本项闭环。** | 徐川（本机补装，**已完成**） |
| 9 | ~~模块 4 的 mock / 监控两处契约，被 `origin/main` 的正式版实现推翻~~ → **mock 数据源已统一，本项闭环（`25b3ee3`，2026-09-28）** | **（2026-09-28 合并后登记，同日闭环）** 合并时 `api/v1/mock.py` / `mock_data.py` / `api/v1/monitor.py` 均取正式版（模块 4 的分支版只有本模块一段，覆盖会删掉模块 5/6/7/8/10 的 mock 路由）。<br>①**mock 响应体**（原「4 步 vs 7 步」不一致）——**集成组已在 `25b3ee3` 修掉**：`mock_data.AGENT_SCHEDULE` 改为**读 `docs/mock/agent_schedule.json` 的 `data` 段**，json 成为唯一真源，响应体随之从 4 步变 **7 步**。路径解析兼容两种检出布局（仓库根 `docs/mock/` 优先，`backend/` 独立检出退回 `backend/docs/mock/`），都读不到则打 ERROR 日志并返回空 `data`（不让演示数据缺失把应用启动带崩，交给用例暴露）。**本分支 rebase 到 `25b3ee3` 时该 json 已由对方并入，本模块那个创建 json 的提交被 git 判定为 `already upstream` 自动丢弃，无冲突。** 核对结果：`api/v1/mock.py` 两边**零差异**；唯一差异是 json 多一行 `"orderId": 101`（本分支 `27d9156` 加的，属冻结契约字段），是**超集**不是冲突。新增的 `tests/api/test_agent_schedule_mock.py`（7 例）**已跑过，全绿**。<br>②**监控口径四处不同**（不鉴权 / `avgLatency` 单位秒 / `successRate` 按 HTTP 状态码 / Redis 存储）——**已按正式版改写 `docs/api.md` 模块 10 整节**，并有回归用例兜底。这一半不是缺陷，是模块 4 的文档原本落后于正式版实现，改文档即闭环。<br>**遗留（另立）**：模块 4 的 `agent_service.record_call` 已无读端（`agent.py` 仍在调），属待清理项 | 申云飞（mock 唯一真源，**已完成**）+ 徐川（文档已改完；`record_call` 清理待裁定） |
| **10** | ~~`agent_service.record_call` / `snapshot` / `reset` 已无读端，是模块 4 阶段 6 自建埋点的残留~~ → **裁定：保留，已加注释（2026-09-28）** | **低优先、非阻塞。** 监控正式口径已由集成组实现（`middlewares/agent_metrics.py` → `core/metrics.py` 的 `MetricStore`（Redis）→ `services/monitor_service.py` → `GET /api/v1/monitor/agent`），模块 4 的进程内计数**在线上没有任何读端**，`agent.py` 仍调 `record_call`、`conftest` 仍用 `reset` 清夹具。**裁定：保留**——直调 Agent 时用它快速看一眼「跑了几次、成功几次」很顺手，删掉反而少个本地排障抓手。<br>**已落地**：`app/services/agent_service.py::record_call` 的 docstring 已写明「**本地调试用，正式埋点走 `app/middlewares/agent_metrics.py`**」，并列出两侧口径差异（判成功依据 / `avgLatency` 单位 / 降级是否单列）与两个已知边界（进程重启清零、多 worker 各报一份），**明确「不要拿它当监控数据源」**。<br>⚠️ **未动** `app/api/v1/agent.py`（仍在调 `record_call`）与 `tests/conftest.py`（`reset_metrics` 夹具仍用 `reset`）——按裁定只加注释，不改代码路径 | 徐川（**已完成**，无需他人） |
| **11** | ~~`AGENT_TIMEOUT` 默认 30 秒，真冒烟实测余量不足（2026-09-28 登记）~~ → **已裁定并已执行：30 → 60（2026-09-28）** | **低优先、非阻塞（演示前处理）→ 本轮已处理。** 本模块 `app/core/config.py:189` 的默认值已由 `30.0` 改为 **`60.0`**，`.env.example:216` 由 `30` 改为 **`60`**，本机 `backend/.env` 已补 `AGENT_TIMEOUT=60`（该文件未跟踪、不入库）；实测 `settings.AGENT_TIMEOUT = 60.0`、`LLM_TIMEOUT = 60`（两者同值）。**改前的记录照录**：**本地 `.env` 未设该键**，所以本次真冒烟跑的就是这个 30 秒默认值——场景 A 实测 `latency_ms=29845`，**余量仅 155 ms**。<br>**为什么危险**：真实耗时几乎全在网络与模型排队，超时后走的是**降级路径**（`builder.py:398` 的 `asyncio.wait_for` → `_degrade(..., "timeout")`），返回 `200` + 友好提示并保留已收集的 trace。接口层**看不出异常**，现场只会发现「方案没出来」，而成功率/告警都不响。<br>**建议**：演示环境 `AGENT_TIMEOUT=60`。**改哪几处待裁定**：① `config.py` 默认值（本模块自有文件）② `backend/.env.example:216`（本模块的「Agent 运行参数」段，该文件最近两次修改均为本模块 `xuchuan`）③ 本地 `.env`（不入库，需演示机各自加）。<br>**⚠️ 改之前要知道的两件事**：<br>① 这个值**同时**喂两处——`ChatOpenAI(timeout=)` 的**单次请求**超时（`builder.py:96`）与 `run_schedule` 的**整体**超时（`builder.py:398`），`config.py:184-189` 的注释写明「整体超时必须不小于单次，否则模型还在正常生成、外层先把协程掐了」。30→60 是两者同抬，方向安全；但 `LLM_MAX_RETRIES=1` 之下，「单次 60 / 整体 60」意味着**一次慢请求就能吃满全部预算**、模型没第二次机会。若要更稳，组合应是「整体 90 / 单次 60」，那需要把这一个键**拆成两个**（本模块可做，但属接口变更，待裁定）。<br>② **「30 是否正式版默认」的核查结论：目前不成立。** `origin/main` 上模块 4 的实现**尚未并入**（只有 `app/agent/` 的空骨架：`__init__.py` × 3 + `prompts/image_prompt.py`），`git grep AGENT_TIMEOUT origin/main` 只命中 `docs/api.md:134` 一句文档描述，`config.py` 与 `.env.example` 里都没有这个键。**并入 `main` 之后，本处的 30.0 才会成为正式版默认**——按这个口径记为本条卡点。 <br>**2026-09-28 已执行（三项）**：① `config.py` 默认值 → `60.0`（并把「为何上调」写进注释）② `.env.example` → `60`（注释附 155 ms 的实测依据）③ 本机 `.env` → 追加 `AGENT_TIMEOUT=60`。**未采用**「拆成两个键（整体 90 / 单次 60）」的方案——属接口变更，留作后续选项（见下方「⚠️ 改之前要知道的两件事」①）。**回归**：`pytest` 全套 `521 passed / 4 deselected / 8 xfailed`（改后复跑），无用例依赖该默认值（两条相关用例用 `monkeypatch` 设为 0.05） | 徐川（**已完成**，2026-09-28） |

| **12** | ~~`generate_notification` 归属分叉：黄嵩侧另给过一份 `(order_id, notify_type, reason) -> str` 的冲突签名，且"交付 Tool 还是 service"未澄清（阶段 3 的 E2）~~ → **已裁定：选 A（唯一与主文档一致）（2026-09-28 黄嵩核对主文档后确认），本项闭环** | **裁定内容**：**Tool 层归模块 4**（按主文档 5.3 的**冻结签名**，`app/agent/tools/generate_notification.py` 留在本模块）；**模块 7 的 service 层保留**（`app/services/notify_service.py` 的桩由黄嵩真实实现替换，**只换函数体、签名不动**）；黄嵩的 `notify_tools.py` **不挂进 `AGENT_TOOLS`**。<br>**本模块零代码变更**（2026-09-28 实测）：`AGENT_TOOLS` 仍是 **5 个**（`query_spaces` / `query_devices` / `lock_resources` / `generate_notification` / `submit_plan`），`app/agent/tools/` 下无 `notify_tools.py`，`generate_notification(order_info: OrderInfo) -> dict` 签名未动。<br>**为什么选 A**：5.3 已冻结 Tool 签名，且模块 3 / 5 / 7 走的是同一个形状——「模块 4 定 Tool 签名、对方实现 service」；改由模块 7 提供通知 Tool 会让工具清单与 5.3 分叉，**「谁在何时把通知落库」出现两套**。通知 Tool 的入参是 `OrderInfo`（含 `orderId`），其触发时机是 Agent 决策链的一环，留在本模块才谈得上「一轮内锁单 → 通知」这个顺序。<br>**注意**：裁定是**口径**层面的，黄嵩的**书面回执仍缺**（阶段 8 交接清单第 3 项）<br>**2026-09-28 黄嵩复核后的两条补充（全文见 `docs/spec/contract-alignment.md` §8.1）**：① **选 A 是唯一与主文档一致的方案** —— 他核对了主文档 5.3 模块 4 的原文，`docs/开发流程.md:391` 写的就是 `generate_notification(order_info)`（`-` 之后的那一条），与 Tool 层冻结签名**逐字相同**；B 方案的 `(order_id, notify_type, reason) -> str` 在主文档里**没有任何出处**。② **更正他上一轮「模块 7 单方面冻结」的说法** —— 那条结论来自一次**漏检**：`git grep` 在 `core.quotepath` 默认 `true` 时会把中文路径**转义**成八进制串（`"docs/\345\274\200\345\217\221\346\265\201\347\250\213.md"`），扫结果时认不出是哪个文件，`开发流程.md` 于是被当成「没提过这件事」；复现见 §8.1 | 黄嵩（确认，**已完成**）+ 徐川（登记） |
| **13** | **`notify_type` 映射：「延期致歉」在 6.3 的 INT 字典（1 预约提醒 / 2 变更致歉 / 3 故障告警）内无对应值（未决 #6）** | **已裁定：不扩字典（2026-09-28，黄嵩）**，`延期致歉` 映射到既有值 **2（变更致歉）**。模块 7 已按此实现（`notify_templates.py` 的 `ToneSpec(key="延期致歉", notify_type=2)`）并有落库断言 `notify_type == 2`。<br>**本分支的状态**：`app/services/notify_service.py` **仍是桩**，该类型仍返回 `ok=False` + 原因说明——**这是预期状态**，桩就是按「字典外取值一律失败并说明原因」设计的；**改它没有意义**（service 未替换，改成映射 2 是与未落地实现对齐）。等模块 7 落 `main`、service 层映射生效后**自然消解**。<br>**待办（模块 4 侧）**：届时把 `backend/tests/test_agent_tools.py` 里 `test_generate_notification_unmapped_type_fails_closed` 的 `assert result["ok"] is False` 改为断言 **Tool 返回值** `result["notifyType"] == 2`（键名是**驼峰 `notifyType`**，不是 DB 列名 `notify_type`），用例名与 docstring 一并改<br>⚠️ **同时要核一个契约点**：本模块 Tool 用 `result.get("notifyType")` 从 service 返回值取值（`backend/app/agent/tools/generate_notification.py:71`）。若模块 7 的真实 service 返回 `notify_type`（与其 DB 列同名），这里会**静默拿到 `None`** —— `ok=True` 但 `title`/`content` 为 `None`，不报错，模型只看到空文案。模块 7 落 `main` 时需连同键名一并核<br>**2026-09-28 黄嵩确认补充（全文见 `contract-alignment.md` §8.2）**：主文档 5.3 模块 7 的端点原文是 `POST /api/v1/notify/generate`：`{ "type": "延期致歉", "orderInfo": {} }` → `{ "title": "...", "content": "..." }`（`docs/开发流程.md:409`）——**入参用中文枚举、响应体不含 `notify_type`**，故「延期致歉 → 2」的 INT 取值是**模块 7 的纯内部存储**，不对外构成契约，两端无需在此对齐字段 | 黄嵩（裁定 + 实现，**已完成**）+ 集成组（落 `main`，待）+ 徐川（用例期望值同步，待） |

原「阶段 3 唯一硬卡点」（`backend/app/core/` 为空）**已解除**：`config.py` 与 `database.py` 已就位，阶段 3 据此通过。

### 2026-09-28 裁定通知（本轮 · 与集成组 / 模块 3 交界处）

> 本轮五条裁定，逐条写明「裁定内容 / 依据 / 去向」。**凡涉及他人文件或团队文档的，
> 本模块只登记口径、不代改**——DDL、团队文档与仓库结构的改动一律走集成组。

| # | 事项 | 裁定 | 依据与去向 |
| --- | --- | --- | --- |
| 1 | **索引迁移的存在性判断（汇总二.3 的 (a)/(b) 取舍）** | **认可申云飞的做法（选 a）**：迁移内**保留显式清单**（`INDEX_SPECS`，11 条），存在性判定取「**列序列完全相同（含顺序）**」，**同列即跳过**、不重复建；**不取**「前缀相同」 | 前缀判定会让 6.6 点名的索引在 `SHOW INDEX` 里**彻底不出现**，正是「三方复现报索引缺失」那类误判的来源；按列判能挡住 MySQL 为每个外键自动建的 `..._ibfk_N`（名字与 6.6 对不上，只比名字会在同一列上再建一条重复索引，白占空间且不报错）。证据：`98c54ea` 的实测（手工造出 `..._ibfk_N` 现场 → `idx_space_id` / `idx_device_id` 不再重复建、其余 9 条照常；重复执行 11 条全跳过、无 `Duplicate key name`）＋用例 `test_upgrade_skips_columns_already_indexed_under_another_name`。**本模块无需返工** |
| 2 | **`idx_status_start` 是否收编进主文档 §6.6** | **不收编**。它是给模块 3 的「设备维度时段占用统计」补的**权宜之计**——权宜之计不进规格；文档口径**保持「6.6 之外、集成组确认后补」** | 该索引的彻底解法是 `order_device` 关联表或 MySQL 8.0.17+ 的 JSON 多值索引，都超出本轮范围；`98c54ea` 已写明「§6.6 若要收编，需同步改团队文档，本轮未改 §6.6 本身」。现状措辞已核对一致：`backend/docs/database.md` 全篇「**6.6 之外**」（§3.4 标题 / 索引表 / 维护表各一处）、`deploy.md:314`「6.6 的 10 个 + 3.4 的 `idx_status_start`」、`开发流程说明文档.md:603` 同口径。**收编要走 6.7 流程，责任人集成组，不在本模块** |
| 3 | **CI 与 pre-commit 的位置（移位）** | **归集成组，不是本模块** | CI 现在**等于不存在**：GitHub 只读**仓库根**的 `.github/workflows/`，而 workflow 在 `backend/.github/workflows/ci.yml`——匿名 API 复核 `total_count: 0`（0 workflow / 0 run），该文件自带的表头也承认不会执行。移位 = 移到仓库根 ＋ `working-directory: backend` 限定，属**仓库结构**改动。同理 `.pre-commit-config.yaml` 在 `backend/` 而钩子要装在**仓库根**的 `.git/hooks/`，一并归集成组。**对阶段 9 的影响**：入口条件 ③「CI 已就位且能跑通」的责任人是集成组 |
| 4 | **`no-secrets-file` 钩子失效** | **归集成组，修 `files` 正则** | 实测（2026-09-28）：`files: ^\.env(\.|$)|\.pem$|\.key$|secrets\.json$` 里的 `^` 锚定使 **`backend/.env` 匹配不上**——`.env` 匹配、`backend/.env` **不匹配**，而真实文件正是 `backend/.env`。第二道防线也缺：`.git/hooks/` 下只有 `*.sample`，钩子**从未安装**（`pre-commit` 命令本身装了）。**修法**：去掉锚定，或写成 `(^|/)\.env(\.|$)`。属集成组文件 |
| 5 | **历史凭据是否轮换** | **负责人决定：不轮换**；补记一句风险 | 已记入 `docs/database.md` 的补记：**`pre-commit` 修好之前，`backend/.env` 可能又被提交**（现为**未跟踪**状态，但钩子未安装、正则也匹配不上，两道防线都不生效；`.gitignore` 的 `.env` 规则只对**未跟踪**文件有效，`git add -f` 或文件重回索引即失效）。⚠️ `git rm --cached` 只摘掉索引，**历史里那份仍然可用** |

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

**蔡玉礼的判据文档（7 条断言）—— 2026-09-28 到手并已落地**

设 `available_count = 2`（落地时取开发库实测容量为 2 的**设备 id=8「音响04」**）：

| # | 断言 | 落地用例（`tests/test_agent_concurrency.py`） | 期望 |
| --- | --- | --- | --- |
| 1 | 无重叠订单，建第 1 单占用该设备 → 成功，`order_status=1` | `test_assert_1_first_order_on_free_slot_succeeds_and_is_persisted` | `ok=True`、`orderId` 非空、库里状态 1 |
| 2 | 已有 1 单占用 T，建第 2 单**同设备**同 T → 成功（`2 ≤ cap`） | `test_assert_2_second_order_same_device_same_slot_succeeds_at_capacity` | `ok=True` |
| 3 | 已有 2 单占用 T，建第 3 单同设备同 T → **拒绝，409 + `code=40901`** | `test_assert_3_third_order_same_device_same_slot_is_rejected` | `ok=False`、`conflictType=device_conflict`（`exhausted`） |
| 3b | **（并发版，保留原 `AGENT-C-01` 的行锁语义）** 并发 3 单 → 恰好 2 单成功 | `test_assert_3b_three_concurrent_orders_on_a_cap_two_device_exactly_two_win` | `len(成功)==2`、`len(拒绝)==1` |
| 4 | 已有 2 单占用 T，把其中一单 cancel（→3）→ 成功 | `test_assert_4_cancel_one_of_two_frees_the_device_slot` | 取消接口 200、库里状态 3 |
| 5 | 承上，再建第 3 单同设备同 T → 成功（回落到 `1 < 2`） | `test_assert_5_after_cancel_third_order_succeeds_capacity_is_derived` | `ok=True` |
| 6 | 已有 2 单占用 T，与 T **相邻但不重叠**的 T' → 成功（**半开区间**） | `test_assert_6_adjacent_non_overlapping_slot_succeeds_half_open` | `ok=True`（`[09,11)` 与 `[11,12)` 端点相接不算重合） |
| 7 | 已有 2 单占用 T，第 3 单用**不同设备**同一 T → 成功（容量按设备各算） | `test_assert_7_other_device_same_slot_succeeds_capacity_is_per_device` | `ok=True` |

**落地时的两处工程判断（不是判据本身的改动，记此备查）**：

- **同一设备的多单必须落在不同场地**：`create_order` 的 §5.5 第 2 步先查**场地**时段重叠，
  同场地同 T 的第二单会先撞 `CONFLICT_TIME`——那样测的是场地冲突，不是设备容量。
  故断言 2/3/5/7 的前置单用 space 6 + space 7，第 3 单用 space 8。
  （实测：T = `2026-10-15 09:00–11:00` 内全库只有 `reserve_order` id=5 占着 space 2，
  space 6/7/8 在该段都空。）
- **断言 3 里的 409/40901 不在 `create_order` 这一层**：它是 service，没有状态行。
  状态码由模块 3 的订单 API 按 `ResourceConflictError` 映射，故该映射另立一条
  **能过、不挂 xfail** 的契约用例 `test_resource_conflict_maps_to_40901_with_http_409`
  单独把关（`code==40901`、`http_status==409`），服务层用例只断言「拒绝」这件事本身。
  **不能拿「反正 40901 存在」当作断言 3 通过。**
- **断言 4/5 多一道卡**：取消要调模块 3 的 `PUT /api/v1/orders/{orderId}/cancel`
  （路径见 `docs/开发流程.md:381`，与 `Permission.ORDER_CANCEL`、`mock.py:93` 的镜像一致），
  本仓库**没有这条真实路由**，调用即 404。**不改成直接 `UPDATE reserve_order`**——
  测试禁写正式表（主文档 6.8），改成改库验的就不是实现了。

**已核实：`40901` 与 409 映射都在正式版里**

| 项 | 位置 | 实测 |
| --- | --- | --- |
| 业务码 `40901` | `backend/app/core/error_codes.py:72` | `RESOURCE_CONFLICT = 40901` ✅ |
| HTTP 映射 409 | `backend/app/core/exceptions.py:181-183` | `class ResourceConflictError(BizError)`，`code = ErrorCode.RESOURCE_CONFLICT`，`http_status = 409` ✅ |

同段还确认了 409xx 一族的其余三个（`CONFLICT = 40900` / `USERNAME_EXISTS = 40902` /
`ORDER_STATUS_CONFLICT = 40903`，同样各自 `http_status = 409`），因此 409 这一档
**不是只有 40901 能走**——判据里若出现 409 但码不是 40901，需按上表核对是不是撞了另外三个。
**无需新增任何码，也无需改 `error_codes.py` 或 `exceptions.py`。**

**仍卡着这 8 条断言真跑通的四件事**

| # | 卡点 | 归属 | 影响范围 |
| --- | --- | --- | --- |
| 1 | `order_service.py` 的 `_device_conflicts` 要按「时段重叠」推导剩余量（现在是 `available_count > 0` 的静态校验），并把只读桩换成真实现 | 蔡玉礼 | 全部 8 条 |
| 2 | `smart_scheduler_test` 1044 无权 → `_db_readonly_guard` 仍拦真库写入；或改走降级路径 | 申云飞 | 全部 8 条 |
| 3 | 模块 3 的取消入口 `PUT /api/v1/orders/{orderId}/cancel` 未交付（`开发流程.md:381` 的冻结路径，本仓库无此真实路由） | 蔡玉礼 | 仅断言 4/5 |
| 4 | 断言 4/5 的「取消」只能走上面的真实入口，**不得改成直接改库**（测试禁写正式表，主文档 6.8） | 徐川（守线） | 仅断言 4/5 |

### LLM 配置 baseline（模块 4 公布 · 2026-09-27）

模块 8 索要的 baseline，可直接照抄。**Key 各人各把，只放本地 `backend/.env`，不入库。**

| 项 | 取值 | 说明 |
| --- | --- | --- |
| `LLM_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | DashScope 的 OpenAI 兼容端点，公开 URL，不含凭据 |
| `LLM_MODEL_NAME` | `qwen-plus` | 全组统一取值。**模型必须支持 Function Calling** |
| `LLM_API_KEY` | 各自申请（DashScope） | 真实值只在本地 `.env`；仓库与文档一律占位 |
| `LLM_TEMPERATURE` | `0.0`（`settings` 默认） | 调度决策要可复现；调高会让同一需求两次给出不同方案 |
| `LLM_MAX_RETRIES` | `1`（`settings` 默认） | 外层已有 `AGENT_TIMEOUT` 兜底，重试不宜多 |
| `AGENT_TIMEOUT` | **`60`（演示环境建议值）**；`settings` 默认仍是 `30.0` | ⚠️ 见下方专段，30 秒余量实测只剩 155 ms |

> ### ⚠️ `AGENT_TIMEOUT` 演示环境建议 60 秒
>
> **30 秒下场景 A 实测余量仅 155ms（29.845 / 30.0 秒），超时走降级返回 200，现场看不出异常。**
>
> 依据：2026-09-28 真冒烟（`qwen-plus`，场景 A），原始输出见
> [stage-05](stage-05-completion.md) §3.3。超时后的行为是契约内的**正常返回**——
> `200` + 友好提示 + 保留已收集的 trace（`builder.py:398` → `_degrade(..., "timeout")`），
> 所以成功率不跌、接口不报错，**只有方案没出来**。
>
> 该值同时是单次请求超时与整轮超时（见硬卡点 #11 的①），**改哪几处待裁定**：
> `config.py` 默认值 / `.env.example` / 本地 `.env`。

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
