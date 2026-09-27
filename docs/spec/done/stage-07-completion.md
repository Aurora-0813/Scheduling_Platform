# 阶段 07 完成文档：测试用例

| 项 | 内容 |
| --- | --- |
| 阶段 | 阶段 07 · 测试用例 |
| 对应文档 | `docs/spec/stage-07-testing.md` |
| 负责人 | 徐川 |
| 开始日期 | 2026-09-27 |
| 完成日期 | 2026-09-27 |
| 计划工时 | 4.0 人日 |
| **实际工时** | 0.8 人日（未计 `AGENT-C-01/02` 与真实模型回归——两者都做不了） |
| 验收测试 | `AGENT-STAGE-07` |
| **验收结论** | **有条件通过** —— 21 条用例中 19 条通过（另加 30 条不在编号表内的契约护栏与边界用例，合计 82 条全绿）；`AGENT-C-01/02` **未通过**，因模块 3 的 `create_order` 仍是只读桩 + 测试库无权访问，标记为 `xfail(strict)` 并如实登记 |

> 验收标准原文写着「任一用例失败即阶段未完成，**不允许以『用例本身有问题』结案**」。
> 本阶段据此**没有**把失败改成跳过、也没有放宽断言：`AGENT-C-01/02` 的失败是**真实缺口**
> （被测实现不存在），不是用例写错。它们被标成 `xfail(strict=True)` 而非删除，
> 并叠加 `strict` 使真实现落地后必然变红、强制摘标记。**这是「未通过」，不是「通过」。**

## 1. 本阶段目标与达成情况

目标：把阶段 4~6 交付的东西在断网状态下验一遍，并把覆盖率门槛固化。

| 任务 | 交付物 | 状态 |
| --- | --- | --- |
| 7-1 夹具冒烟 | `tests/conftest.py`（`ScriptedChatModel` + 三个 autouse 护栏） | ✅ |
| 7-2 只读会话夹具 | `tests/conftest.py::db_session` | ⚠️ **有偏差**（连开发库不连测试库，见第 6 节） |
| 7-3 `AGENT-U-01~05` | `tests/test_agent_tools.py`、`tests/test_agent_trace.py` | ✅ 30 例通过 |
| 7-4 `AGENT-S-01~05` | `tests/test_agent_schedule.py` | ✅ 5 例通过（口径见第 4 节） |
| 7-5 `AGENT-E-01~04` | `tests/test_agent_schedule.py` | ✅ 7 例通过 |
| 7-6 `AGENT-I-01~05` | `tests/test_agent_schedule.py` | ✅ 8 例通过 |
| 7-7 `AGENT-C-01/02` | `tests/test_agent_concurrency.py` | ⛔ **xfail，未通过** |
| 7-8 断网复跑 + 覆盖率阈值 | `pytest.ini` | ✅ 92.29%（阈值 80%） |
| 7-9 `docs/test.md` | `docs/test.md` | ✅ |

**实际产出比计划多 30 条用例**：契约护栏 5 条（`conflictType` 枚举、`PlanPayload` 与
`Plan` 字段集、`/api/v1/tools/*` 不存在、工具全 `async`、`LockResourcesArgs` 无 `user_id`）、
trace 边界与 `parse_observation` 各形态、`collect_stamped_messages` 的三条退路、
seeding 前提核对、以及两条**护栏自证**用例（见第 3 节 `[G]`）。它们不在编号表里，
但少一条就会让某条「两处必须同时改」的注释退化成注释。

## 2. 完成判定逐项核对

- [x] `AGENT-U-01~05`（5 条）通过 —— 证据：第 3 节 `[A]`，共 30 例
- [x] `AGENT-S-01~05`（5 条）通过 —— 证据：第 3 节 `[B]`，**口径限制见第 4 节**
- [x] `AGENT-E-01~04`（4 条）通过 —— 证据：第 3 节 `[C]`，共 7 例
- [x] `AGENT-I-01~05`（5 条）通过 —— 证据：第 3 节 `[D]`，共 8 例
- [ ] `AGENT-C-01~02`（2 条）通过 —— ⛔ **未通过**（xfail），见第 5 节
- [x] **断网状态下全部用例通过** —— 证据：第 3 节 `[G]`，
      `test_guard_offline_is_actually_armed` 主动触发拦截确认护栏在场
- [x] `app/agent/` 覆盖率 ≥ 80%，阈值已写入 `pytest.ini` —— 证据：第 3 节 `[E]`，92.29%
- [x] 全部用例已记录到 `docs/test.md` —— 证据：`docs/test.md` 第三、四节
- [x] 无任何用例写 `reserve_order` 正式表 —— 证据：第 3 节 `[G]`，
      `test_guard_db_writes_are_actually_blocked` 主动触发写拦截

## 3. 验收测试执行记录

| 项 | 内容 |
| --- | --- |
| 测试编号 | `AGENT-STAGE-07` |
| 执行环境 | Windows 11；conda 环境 `smart_dev`（Python 3.11.9）；SSH 隧道 3308 通；开发库 `smart_scheduler_dev`；进程内 ASGI 客户端 |
| 执行命令 | `cd backend && PYTHONIOENCODING=utf-8 "F:/conda_envs/envs_dirs/smart_dev/python.exe" -m pytest -q` |
| 执行时间 | 2026-09-27 19:30 |

### `[A]`~`[D]` 用例逐条输出（原始，未改写）

```
concurrency.py::test_c01_concurrent_locks_on_the_same_slot_exactly_one_wins XFAIL [  3%]
concurrency.py::test_c01_stub_state_is_recorded_not_glossed_over          PASSED [  6%]
concurrency.py::test_c02_device_count_decrements_on_lock_and_survives_failure XFAIL [9%]
concurrency.py::test_c02_stub_state_is_recorded_not_glossed_over          PASSED [ 12%]
schedule.py::test_s01_budget_downgrade_keeps_space_drops_one_projector    PASSED [ 15%]
schedule.py::test_s02_split_request_is_carried_through                    PASSED [ 18%]
schedule.py::test_s03_device_substitution_replaces_type                   PASSED [ 21%]
schedule.py::test_s04_contradictory_request_returns_null_plan_with_suggestions PASSED [24%]
schedule.py::test_s05_merged_activity_keeps_the_saving_in_reason          PASSED [ 27%]
schedule.py::test_e01_non_json_reply_degrades_with_model_text             PASSED [ 30%]
schedule.py::test_e01_fenced_json_in_text_is_salvaged                     PASSED [ 33%]
schedule.py::test_e02_slow_model_degrades_on_timeout                      PASSED [ 36%]
schedule.py::test_e02_timeout_keeps_the_steps_already_collected           PASSED [ 39%]
schedule.py::test_e03_empty_query_result_yields_no_plan                   PASSED [ 42%]
schedule.py::test_e04_tool_exception_is_not_a_500                         PASSED [ 45%]
schedule.py::test_e04_runtime_error_in_the_stream_degrades_not_500        PASSED [ 48%]
schedule.py::test_i01_normal_call_returns_full_unified_body               PASSED [ 51%]
schedule.py::test_i02_missing_authorization_is_401                        PASSED [ 54%]
schedule.py::test_i03_empty_text_is_422_without_calling_the_model         PASSED [ 57%]
schedule.py::test_i04_identity_comes_only_from_jwt[payload0]              PASSED [ 60%]
schedule.py::test_i04_identity_comes_only_from_jwt[payload1]              PASSED [ 63%]
schedule.py::test_i04_identity_comes_only_from_jwt[payload2]              PASSED [ 66%]
schedule.py::test_i05_response_carries_no_secrets                         PASSED [ 69%]
schedule.py::test_i05_unavailable_llm_returns_503_naming_fields_not_values PASSED [72%]
schedule.py::test_i05_build_model_gate_and_no_implicit_key                PASSED [ 75%]
schedule.py::test_i05_never_registers_tool_routes                         PASSED [ 78%]
schedule.py::test_guard_offline_is_actually_armed                         PASSED [ 81%]
schedule.py::test_guard_db_writes_are_actually_blocked                    PASSED [ 84%]
tools.py::test_guard_lock_resources_conflict_enum_matches_service         PASSED [ 87%]
tools.py::test_guard_submit_plan_payload_matches_response_schema          PASSED [ 90%]
tools.py::test_guard_no_tools_routes_registered                           PASSED [ 93%]
tools.py::test_guard_all_tools_are_async                                  PASSED [ 96%]
tools.py::test_guard_lock_resources_args_have_no_user_id                  PASSED [100%]
================ 31 passed, 51 deselected, 2 xfailed in 16.88s ================
```

`[G]` = 护栏自证两条（`test_guard_offline_is_actually_armed`、
`test_guard_db_writes_are_actually_blocked`）。它们主动去触发拦截：**「断网跑通」与
「没写正式表」都是否定性结论，只报「跑完了、没报错」证明不了——没报错也可能是拦截根本没生效。**

### `[E]` 全量运行 + 覆盖率（原始输出，逐字照抄）

```
x.x..................................................................... [ 85%]
............                                                             [100%]
=============================== tests coverage ================================
_______________ coverage: platform win32, python 3.11.9-final-0 _______________

Name                                       Stmts   Miss  Cover   Missing
------------------------------------------------------------------------
app\agent\__init__.py                          0      0   100%
app\agent\chains\__init__.py                   0      0   100%
app\agent\chains\builder.py                  178     29    84%   134, 146-147, 149, 158-159, 185, 196, 213, 255-259, 279, 283, 302-311, 320, 423, 450-454
app\agent\chains\trace.py                    136      3    98%   103, 137, 189
app\agent\context.py                          19      0   100%
app\agent\prompts\__init__.py                  0      0   100%
app\agent\prompts\scheduler.py                 9      0   100%
app\agent\tools\__init__.py                    7      0   100%
app\agent\tools\_common.py                    22      3    86%   33, 35, 52
app\agent\tools\generate_notification.py      19      0   100%
app\agent\tools\lock_resources.py             33      1    97%   124
app\agent\tools\query_devices.py              23      1    96%   90
app\agent\tools\query_spaces.py               26      0   100%
app\agent\tools\submit_plan.py                21      1    95%   95
------------------------------------------------------------------------
TOTAL                                        493     38    92%
Required test coverage of 80% reached. Total coverage: 92.29%
82 passed, 2 xfailed in 21.75s
```

首行 `x.x` = `AGENT-C-01` / `AGENT-C-02` 各一个 `xfail`（`x`）夹一个通过（`.`）。

未覆盖的 38 行集中在**降级路径的容错分支**（不是主干逻辑）：

| 位置 | 未覆盖内容 | 后续 |
| --- | --- | --- |
| `builder.py` 134~320 段 | `extract_plan_from_text` 的畸形输入分支、`_normalize_submission` 的次要分支、`_last_ai_text` 的 list 形态 content | 可补，价值中等 |
| `builder.py` 450-454 | `_compose_user_message` 的 `image_context` 拼接（**模块 2 的图像上下文入口**） | 模块 2 交付形状确定后补 |
| `builder.py` 423 | `plan_without_space` 降级分支（拿到结构但 `spaceId` 为空） | 可补 |
| `trace.py` 103/137/189 | `_summarize` 的个别 action 分支、`build_trace` 的异常输入兜底 | 可补 |

**四行不到 8%**，不足以让「覆盖率达标」变成一句空话；但也不声称已覆盖全部容错路径。

## 4. `AGENT-S-01~05` 的通过口径（**必读，否则会高估这五条**）

五条场景用例把「模型怎么决策」当作**输入**喂进来（`ScriptedChatModel` 按脚本调
`query_spaces` → `query_devices` → `submit_plan`），系统侧全是真的：真的 `create_agent`
组装、真的 `ToolNode`、真的工具查开发库、真的 trace 提取、真的统一响应体。

**因此它们验的是「透传与形状」，不是「判断质量」**：

| 验到了 | 没验到 |
| --- | --- |
| 模型写在 `reason` 里的降级/替代理由一字不少地到达用户 | 800 元预算下**该不该**把双投影降成单投影 |
| `backup_plan`（snake_case 入参）正确落到 `backupPlan` 字段 | 40 人需求下**该不该**拆成两个场地 |
| 矛盾场景下 ≥3 条修改建议原样透传、`plan` 不为 `null` 编造 | 投影仪借不到时**会不会**想到换显示屏 |
| 两次锁定各自成步、替代路径在 trace 留痕 | 同团队两场活动**该不该**合并 |

决策质量的验证需要**真实 LLM**，卡在 `backend/.env` 的 `LLM_MODEL_NAME` /
`LLM_API_KEY` / `LLM_BASE_URL` 三项为空。补齐后应补一轮真实模型回归，结果另记。

五条场景各自的**前提**（种子数据里确实存在「预算恰好卡在场地价上」「没有 40 人的会议室」
「显示屏可借」这些约束）由 `test_seed_supports_the_five_scenarios` 对着**真库**验——
那部分不依赖模型，是真实结论，且种子数据一变它会指名道姓地报出哪条场景的前提没了。

## 5. `AGENT-C-01/02` 为什么未通过，以及怎样才算通过

两条用例的**断言是真的、被测实现还不存在**。模块 3（蔡玉礼）的 `create_order`
目前是**只读桩**：不 `FOR UPDATE`、不 INSERT、不扣减，`orderId` 恒为 `None`。
桩自己的 docstring 写着：

> `AGENT-C-01` 的并发语义无法在桩上验，**假装能验就是假绿**。

三种处置里只有 `xfail(strict=True)` 诚实：

| 处置 | 后果 |
| --- | --- |
| 删掉不写 | 21 条用例缺 2 条，「并发没验」这件事从报告里消失 |
| 改写成能过（只断言返回体结构合法） | 假绿：永远会过，即使真实现把行锁写反 |
| **`xfail(strict=True)`** | 现状如实记录；真实现落地后**变红（XPASS）**，强制摘标记 |

### 要让它们真正跑起来，三件事缺一不可

1. 蔡玉礼替换 `create_order` / `update_agent_trace` 的**真实实现**
2. **测试库权限**（集成组）——并发用例必须能真写、真回滚
3. `conftest.py::_db_readonly_guard` 对这两个文件**放开**——否则第 1、2 步到位也会被
   拦成 `WriteForbiddenError`

**第 3 条容易被漏掉**：当前为了连开发库不污染数据，写语句被前置拒绝（第 6 节的偏差）。
这道拦截恰好会把并发用例要验的真实写入一起打死。它是「无测试库权限」的替代方案带来的
副作用，解铃还须系铃人。

另有两例 `test_c0*_stub_state_is_recorded_not_glossed_over` **刻意断言桩的当前行为**
（`orderId` 为 `None`、`stub=True`、库存不变），是**桩期临时用例**。真实现落地后会失败
——那时应当**删除**，而不是放宽断言。

## 6. 偏差与如实登记

| # | 阶段文档要求 | 实际做法 | 原因 | 影响 |
| --- | --- | --- | --- | --- |
| 1 | §3.2 连 `smart_scheduler_test`，用例后回滚 | 连开发库 `smart_scheduler_dev`；**写入被前置拦截，无需回滚** | 测试库报 **1044 无权访问**（集成组） | 未取得权限前**不得声称已符合 6.8** |
| 2 | §3.5 `AGENT-E-02` 用「假模型抛 `TimeoutError`」 | 用 `delay` + 改小 `AGENT_TIMEOUT`；另加一条替换 `collect_stamped_messages` 的用例 | 慢模型在**第一次模型调用**就卡住，一步都不会被打点，验不出「保留中断前步骤」 | 无（覆盖更强） |
| 3 | §3.4 `AGENT-S-01~05` 验五个决策场景 | 见第 4 节口径 | `.env` 无 LLM 三项 | 决策质量**未验证** |
| 4 | §3.8 断网跑一遍 | socket 拦截（autouse）而非物理断网 | 关网卡要管理员权限，且会连 SSH 隧道一起断（连库用例就没法跑） | 拦截覆盖更精确，且**每条用例**都生效 |
| 5 | §3.7 `AGENT-C-01/02` 通过 | `xfail(strict=True)` | 见第 5 节 | **阶段未完全达标** |

偏差 1 的补充说明：「回滚」这一步在连开发库的前提下本来就是错的安全手段——它保护的是
「用例自己的写」，而用例压根不许写。真正的保护是**拦截**：回滚方案在用例中途崩掉时可能
留下半截数据，拦截是每次都生效的前置拒绝。安全性更高，但**不等于合规**，所以照记。

## 7. 本阶段修掉的两个真实缺陷（不在计划内）

写用例的过程中撞出两处**生产代码**的问题，都已修：

| # | 缺陷 | 危害 | 修法 |
| --- | --- | --- | --- |
| 1 | `lock_resources` 里 `device_ids=list(device_ids or [])` 对字符串**逐字符迭代** | `device_ids="12"` 静默变成 `[1, 2]` → 一次传错类型的调用变成一次**成功且看起来正确**的预约。`order_service` 专门为此写了拒绝分支，Tool 层这一 `list()` 恰好把它拆掉 | 在 Tool 层显式挡类型，并复用 `invalid_param` + `actionHint` |
| 2 | 用例直调工具时传裸 `dict`，工具体内 `.model_dump()` 抛 `AttributeError` | 不是线上缺陷，但暴露了一处**隐含假设**：工具体假定框架已把入参转成 Pydantic 模型。Agent 路径确实如此（`submit_plan` 的实跑可证），直调路径不是 | 用例改传 `OrderInfo` 实例（按生产形状），并写明理由 |

另外修掉一处**测试基础设施**问题：`pytest-asyncio` 默认每条用例一个新事件循环，而
`asyncmy` 的连接与创建它的循环绑定、连接池是进程级的 → 池里旧连接指向已关闭的 loop，
表现为 `asyncmy.errors.InternalError: network operation failed`（内层
`AttributeError: 'NoneType' object has no attribute 'send'`），**且只在复用池化连接的
用例上偶发**，极易误判成「数据库不稳定」。已在 `pytest.ini` 固定
`asyncio_default_test_loop_scope = session` 并写明原因。

## 8. 未闭环清单（按硬度排序，均需他人）

| # | 事项 | 归属 | 卡住什么 |
| --- | --- | --- | --- |
| 1 | `create_order` / `update_agent_trace` 真实实现 | 蔡玉礼（模块 3） | `AGENT-C-01/02` 无法通过；`agent_trace` 补写恒失败 |
| 2 | `smart_scheduler_test` 访问权限 | 集成组 | 阶段 7 §3.2 合规性；并发用例的写入前提 |
| 3 | `.env` 的 LLM 三项 | 徐川（本地填即可） | 五场景的**决策质量**回归 |
| 4 | DDL 版本与 6.7 的逐条比对 | 集成组 | 种子数据基线（`docs/test.md` 第一节） |
| 5 | `conflictDetail` 的四种形状（contract-alignment 第 4、6 条） | 蔡玉礼 | 前端屏 3 冲突渲染；`device_conflict` 的 reason 区分已按两条落地，另两条未到手 |
| 6 | 未决 #6：`延期致歉` 无对应 INT 值 | 黄嵩 + 集成组 | `generate_notification` 该类型**失败并说明原因**（不擅自映射），用例钉住了这个行为 |
| 7 | `order_status` 默认 1 与主文档 5.5 第 3 步的校验口径 | 蔡玉礼 | 已暂按更严的 `status IN (1,2)` 实现，标记为与 5.5 字面不一致 |
| 8 | **模块 1/2 的接口用例在本环境恒红（9 例）** | 模块 1（郑宇豪）/ 模块 2 | 见下方说明。**非本模块引入，本模块也不修** |

### 第 8 条：image/voice 用例继承红（2026-09-27 定性）

`tests/test_image_api.py`（5 例）与 `tests/test_voice_api.py`（4 例）在本环境**恒红**，
断言处一律是 `assert 401 == 200` / `assert 401 == 400`，即响应体 `code=401`。

**根因**：`image.py` 与 `voice.py` 的两个接口都挂 `Depends(get_current_user)`
（`app/api/deps.py`，真 JWT 校验），而 `AUTH_BYPASS` 在 `config.py:36` 与 `origin/main`
上**都是 `False`**、`.env` 也没开。用例不带 `Authorization` 头 → 走 `AuthError` →
`code=401`。

**定性依据（两条独立证据，均已实跑）**：

1. 临时 `AUTH_BYPASS=true` 复跑这 9 例 → **14 passed**（含另 5 例）——证明根因就是鉴权闸门；
2. 拉一个**纯净 `origin/main`（`6f6f6ff`）worktree** 复跑 `test_image_api.py`
   + `test_voice_api.py` → **同样这 9 例红，逐条同名**——证明是模块 1/2 的继承问题，
   与本模块的 rebase 无关。

**结论**：属模块 1/2 自身的用例与环境问题，**模块 4 不修**——修它要动别人的
路由依赖或改 `AUTH_BYPASS` 默认值，两者都越界（`AUTH_BYPASS=false` 是安全默认值，
为让用例变绿而改默认值是拿部署安全换 CI 绿灯）。留待模块 1/2 与集成组处置。
在**本模块**的验收口径里，这 9 例不计入分子分母。

## 9. 建议

1. **`AGENT-C-01/02` 应当在 M3 评审上作为唯一未达标项点名**——它是阶段 7 通过标准里
   明写的一条，而它卡在别人手里。不要在汇报里把它算作「已通过」。
2. 测试库权限拿到后，第一件事是**把 `_db_readonly_guard` 收窄到非并发用例**，
   否则第 5 节的第 3 步会一直挡着。
3. 真实 LLM 配好后补一轮五场景回归，**只补决策质量那部分断言**（现有五条用例改成
   断言「模型的真实输出合理」需要重写，不要直接复用脚本模型）。
4. `docs/test.md` 第一节的环境基线是**每次 M4 联调前**要重核的项，不是一次性文档。

## 10. 完成后

- [x] 本文件写入 `docs/spec/done/`
- [x] `docs/spec/README.md` 阶段状态表更新为「有条件通过」
- [x] `docs/test.md` 用例清单、环境基线、覆盖率实测结果更新
- [x] 代码与用例提交（commit 信息含本文件路径）

---

## 附录:db_writes 标记与 `_db_readonly_guard` 收窄方案

> **状态：方案，待实施（未动任何代码）。** 2026-09-27 拟定。
> 与第 5 节「要让它们真正跑起来，三件事缺一不可」配套——其中第 3 条
> （收窄拦截）的具体做法落在本附录。第 1、2 条不在本方案射程内。

### 一、结论先行：收窄是**必要条件，不是充分条件**

即使 `_db_readonly_guard` 对并发用例放开写入，`AGENT-C-01/02` **仍然过不了**——
C-02 要断言的「锁定后 `available_count` 递减 / 失败时不减」**没有可供对照的依据**：
主文档 §5.5 六步里既没有扣减也没有回补，口径未定（硬卡点 **#5**）。
本方案解开的只是「写不进去」这一层。**不要把「guard 收窄完成」读成「C-01/02 能过了」。**

### 二、关键约束（决定了方案不能取巧）

`_db_readonly_guard` 是 `scope="session"` 的闭包，挂在 `before_cursor_execute` 上，
**看不到 `request`**；而 C-01 验的是**真并发下的行锁**。这条约束直接排除掉最顺手的做法。

#### C-01 排除「让被测代码加入用例的外层事务」

「把 `order_service` 用的会话绑到测试的外层事务、`commit()` 变成 `begin_nested()`、
用例结束整事务回滚」，是清理数据最干净的做法，**但只能用于 C-02，不能用于 C-01**：

两个协程共享同一个连接时，`SELECT ... FOR UPDATE` 的锁**不可能互相阻塞**——第二个
协程根本不会被挡住，于是「恰好一个成功」**必然成立**。用例会通过，但它验的不是行锁，
是重叠检测。**这正是 `xfail(strict=True)` 要防的那类假绿**，只不过这次它披着
「真实现已落地、用例转绿」的外衣，比桩期的假绿更难发现。

→ **C-01 必须真连接、真事务、真提交**，数据清理只能放到 teardown 做。

### 三、三层设计

**第一层：默认拒绝不变，改成「标记 + 可变标志」**

| 步 | 做法 | 要点 |
| --- | --- | --- |
| 1 | `pytest.ini` 注册 `db_writes` marker | 不注册会产生 `PytestUnknownMarkWarning` |
| 2 | 新增 **function-scoped autouse 夹具**：读 `request.node.get_closest_marker("db_writes")`，命中则置真，`finally` 一定复位 | 守卫是 session 级闭包、看不到 `request`，必须由夹具把判断结果传给守卫 |
| 3 | `_db_readonly_guard` 的 `_guard` 首行判断标志，为真即 `return` | 改的是 `conftest.py` 一个函数体，改动面极小 |

- 用**模块级布尔**而不是 `ContextVar`：`asyncio.gather` 会建子 task，`ContextVar` 的值
  会被继承、也能用，但值在 task 内改动不外传，语义更容易踩错；用例串行跑时布尔足够。
  **若将来并行跑用例，这里必须换成 `ContextVar`。**
- **现有自证用例 `test_guard_db_writes_are_actually_blocked` 一行都不用改**：它打的是不带
  标记的 `db_session`，继续证明「默认拒绝没被放松」。

**第二层：不污染种子——靠「真写 + 自己清理」，不是靠回滚**

| 用例 | 清理方式 |
| --- | --- |
| C-01 | 造的订单在 `agent_request` 里带**本用例独有的哨兵串**（如 `"[C-01-test] <uuid>"`）；teardown 用 `DELETE ... WHERE id IN (...) AND agent_request = '<哨兵>'` **精确删除并断言删除行数**，非零残留即失败并打印残留 id |
| C-02 | teardown 先把 `available_count` 恢复到用例前读到的值、再删订单，并断言恢复后与基线相等 |

**首选仍是测试库**：`smart_scheduler_test` 脏了可以整库重建，开发库不能。所以带
`db_writes` 的用例在连开发库时，**必须在测试输出与文档里如实标注为降级路径**，
不得声称已合规（与第 6 节偏差 #1 同一口径）。

**第三层：加一条反向自证**

阶段 7 §3.8 对否定性结论的要求是「不要只凭『应该不联网』推断」。同理，
**「守卫收窄了」这件事也要有证据**——否则「标记生效了」与「守卫根本没生效」
在测试输出上无法区分。做法：新增一条带 `db_writes` 标记、真的写入成功（写后立即删）
的自证用例。

### 四、验证步骤（实施后逐条执行）

1. **未带标记的写入仍被拒** —— 现有 `test_guard_db_writes_are_actually_blocked` 输出不变。
2. **带标记的写入通得过** —— 新增的反向自证用例。
3. **跑完 C-01/C-02 后手工复核**：`reserve_order` 行数回到 **10**、
   `device_resource` 那 15 行的 `available_count` 回到种子原值。

### 五、实施前提：三样缺一不可

| # | 前提 | 谁给 | 不给会怎样 |
| --- | --- | --- | --- |
| 1 | `smart_scheduler_test` 权限（**或**走降级路径，并在输出/文档里明确标注） | 申云飞 / 集成组 | 只能连开发库，清理靠自己删，用例中途崩就会残留 |
| 2 | 模块 3 真实现落 `main` | 蔡玉礼（推）+ 集成组（合入） | 标记加上去了，两条仍是 `xfail`，白做 |
| 3 | `available_count` 扣减/回补**口径**（缺的是规则，不是字段） | 集成组 | C-02 的断言没有判据——**放开写入也验不了** |

### 六、与第 9 节建议 2 的关系（措辞以免歧义为准）

第 9 节建议 2 写的是「把 `_db_readonly_guard` 收窄到非并发用例」。**方向要反过来**：
不是「对非并发用例收窄」，而是**默认拒绝保持不变，只对带 `db_writes` 标记的并发用例
放行**。实施口径以本附录第三节为准。
