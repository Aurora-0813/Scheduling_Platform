# 测试用例文档

> 本文件为全组共用，按模块追加。当前包含：
> **模块 4 — 核心调度 Agent**（环境基线、假 LLM 夹具结论、AGENT-\* 用例清单）
> **模块 7 — AI 冲突预警与智能通知**（运行方式、用例总览、关键用例说明、端到端步骤）
>
> 依据《项目文档.md》10.1~10.3（测试规范）、6.8（测试库）、6.9（种子数据）、11.1~11.2。
> 接口变更或种子数据变更时，本文件须同步更新。

---

## 一、环境基线

> 用途：各模块联调时他人照此复现。**本小节必须与实际执行结果一致，未核对项如实标注。**

| 项 | 值 | 状态 |
| --- | --- | --- |
| 核对日期 | 2026-09-24（模块 4）／2026-09-27（模块 7 合并回归） | ✅ 已核对 |
| Python 版本 | 3.11.9 | ✅ 已核对 |
| conda 环境 | `smart_dev`（**路径因机器而异**：模块 4 为 `F:\conda_envs\envs_dirs\smart_dev`，模块 7 为 `D:\conda\envs_dirs\smart_dev`） | ✅ 已核对 |
| 依赖安装方式 | `pip install -r backend/requirements.txt`（版本全量 `==` 锁定） | ✅ 已执行 |
| 关键版本 | langchain 1.3.11 / langchain-openai 1.5.0 / langchain-classic 1.0.0 / langchain-core 1.6.4 / langgraph 1.2.12 | ✅ 已核对 |
| 数据库驱动 | asyncmy 0.2.10 | ✅ 已安装 |
| 认证依赖 | passlib 1.7.4 + bcrypt 4.0.1（哈希自检 `verify: True`） | ✅ 已核对 |
| 锁文件 | `backend/requirements.lock` | ✅ 已生成 |
| 离线回归（模块 7，合并后） | `447 passed, 3 skipped`（共 450 条，3 条为 live 默认跳过） | ✅ 已执行（2026-09-27） |
| 覆盖率（合并后） | 全量 `app/` 1784 语句 / 94%；剔除模块 4 尚未实现的 `app/schemas/agent.py` 后为 96% | ✅ 已执行 |
| 迁移依赖 | **`alembic` 与 `pymysql` 均未安装，且不在 `requirements.txt` / `requirements.lock` 中** | ⛔ 阻塞：`alembic upgrade head` 当前无人可跑 |
| DDL 版本 | 未核对 | ⛔ 阻塞：无有效 `.env` 凭据（`DB_PASSWORD` 为空），无法连库 |
| 种子数据条数 | 未核对（期望 场地 8 / 设备 15 / 预约 10） | ⛔ 阻塞：同上 |
| 测试库 | 未核对（`smart_scheduler_test`） | ⛔ 阻塞：同上 |

**未核对项的阻塞原因**：`backend/.env` 无数据库密码、且未起 SSH 隧道（`ssh -L 3308:127.0.0.1:3307 <user>@<云服务器IP> -N`），无数据库连接凭据；6.7 的 DDL 与 6.9 的种子数据尚未由集成组执行。补齐后须重跑基线核对并更新本表。

> **迁移依赖这一项是会绊住所有人的坑**：仓库里有 `backend/alembic/` 和一份初始迁移脚本，但 `alembic`、`pymysql` 两个包既没装、也没写进任何依赖文件 —— 照文档装完依赖的人**跑不了迁移**。补依赖属集成组决定，不由模块 7 擅自改锁定清单。

### 运行环境注意

终端为 GBK 码页时，脚本输出的中文会显示为乱码（内容无误）。跑中文输出脚本时加编码声明：

```bash
PYTHONIOENCODING=utf-8 python tests/smoke_fake_llm.py
```

---

## 二、假 LLM 夹具结论（核心调度 Agent 模块）

**结论：`FakeMessagesListChatModel` 与 `GenericFakeChatModel` 均不可用，须使用自实现 `bind_tools` 的 `StubChatModel`。**

### 验证方法

脚本：`backend/tests/smoke_fake_llm.py`

```bash
cd backend && python tests/smoke_fake_llm.py
```

原理：`create_agent` 内部会调用 `model.bind_tools(tools)`。基类 `BaseChatModel.bind_tools` 的默认实现直接抛 `NotImplementedError`，凡是没覆写该方法的假模型类，挂到 `create_agent` 上都会失败。

### 实测结果（langchain-core 1.6.4）

| 夹具 | 结果 | 说明 |
| --- | --- | --- |
| `FakeMessagesListChatModel` | ❌ FAIL | `NotImplementedError: bind_tools` |
| `GenericFakeChatModel` | ❌ FAIL | `NotImplementedError: bind_tools` |
| `StubChatModel`（自实现 `bind_tools`） | ✅ PASS | 绑定成功，4 条消息，1 条 `ToolMessage` |

**注意**：《核心调度Agent开发流程.md》阶段 7.1 预警了 `FakeMessagesListChatModel` 不可用，但推荐的替代方案 `GenericFakeChatModel` **同样不可用**。该处文档已过时，需按本结论修正。

### ⚠️ 与模块 7 的关系：两条结论并不矛盾，适用范围不同

模块 7 的用例**大量使用 `FakeMessagesListChatModel`**（见 `app/agent/chains/llm.py::build_fake_llm`、`tests/conftest.py`），这与上面的结论并不冲突：

| 模块 | 是否需要 `bind_tools` | 可用夹具 |
| --- | --- | --- |
| 模块 4（本小节结论） | **需要** —— 走 `create_agent` ReAct 图，必须能绑定工具 | 只能用 `StubChatModel` |
| 模块 7 | **不需要** —— 单轮结构化生成，所需事实在 service 层已组装完毕，不挂工具 | `FakeMessagesListChatModel` 即可 |

失败的原因是 `create_agent` 会调 `bind_tools`，而模块 7 根本不调。**不要把本小节的结论套到模块 7 的用例上**，反之亦然。两个夹具并存是刻意的。

### 后续用例的夹具方案

`tests/conftest.py` 的 `fake_llm` 夹具使用 `StubChatModel`：

```python
class StubChatModel(BaseChatModel):
    """自实现 bind_tools 的替代夹具，供 create_agent 使用。"""
    responses: list[AIMessage] = []
    _cursor: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "stub-chat-model"

    def bind_tools(self, tools, **kwargs):
        """create_agent 必需。基类默认实现直接抛 NotImplementedError。"""
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        idx = min(self._cursor, len(self.responses) - 1)
        self._cursor += 1
        return ChatResult(generations=[ChatGeneration(message=self.responses[idx])])
```

说明：

- `bind_tools` 返回 `self` —— 夹具不需要真正绑定工具，只要不抛异常即可
- `_cursor` 用 `PrivateAttr` 而非普通字段，否则会被 pydantic 当成模型字段参与校验
- 响应列表按调用顺序消费：第一次调用返回带 `tool_calls` 的 `AIMessage`，第二次返回最终答复

---

## 三、运行方式与离线保证（模块 7）

```bash
# 准备工作（一次性）：创建环境并安装依赖
conda create -n smart_dev python=3.11.9 -y
conda activate smart_dev
pip install -r backend/requirements.txt

# 全量测试（离线可跑，不需要数据库 / Redis / 大模型 API）
cd backend
python -m pytest tests -q

# 真实 API 冒烟（主文档 10.2 要求只做一次，默认跳过）
#   Windows PowerShell: $env:RUN_LIVE_LLM="1"
#   Linux / macOS:      export RUN_LIVE_LLM=1
python -m pytest tests -m live -v
```

> `python -m pytest` 必须从 `backend/` 目录执行：`backend/pytest.ini` 是 pytest 的 rootdir，
> 里面的 `asyncio_mode = auto` 与 `markers` 定义都依赖它被读到。

### 离线保证

| 外部依赖 | 测试中的替代物 |
| :--- | :--- |
| MySQL | 完全不连。规则是同步纯函数，直接构造快照；服务层与接口层注入假会话 |
| 大模型 API | 由 `app/agent/chains/llm.py::build_fake_llm` 统一构造（模块 7 用 `FakeMessagesListChatModel`，模块 4 用 `StubChatModel`，理由见第二节） |
| Redis | `MemoryDedup`（进程内实现），或 `FakeRedis` 桩 |

**不使用 `aiosqlite`**：一是 3.1 的技术栈里没有它，二是 MySQL 专有类型（`BIGINT UNSIGNED`、`DATETIME`）在 SQLite 上语义不同，用 SQLite 测出来的结论不可信。

`backend/pytest.ini` 已设置 `asyncio_mode = auto`。**缺了它，所有 async 用例会被静默跳过**（pytest-asyncio 报 warning 但不报错），测试结果会假绿。

> 同理，**同步数据库驱动也不该成为测试依赖**。`app/core/database.py` 的同步引擎（`sync_engine` / `SyncSessionLocal`）是**惰性创建**的：`create_engine()` 在调用那一刻就会解析 DBAPI，若写在模块顶层，「import app.core.database」就要求本机装着 `pymysql`，整套离线测试会在收集阶段直接 `ModuleNotFoundError`。合并团队代码时实测踩过这个坑（7 个测试模块无法收集）。两条护栏用例守着它：`test_sync_engine_is_not_created_at_import_time`（AST 层面）与 `test_importing_database_module_leaves_the_sync_engine_unbuilt`（运行时）。

---

## 四、用例总览（模块 7）

| 测试文件 | 用例数 | 覆盖内容 |
| :--- | ---: | :--- |
| `tests/unit/test_rules_base.py` | 18 | 规则公共设施：时间格式化、归一化、名字查询、阈值快照 |
| `tests/unit/test_rules_continuous.py` | 11 | 连续活动无休息：命中/边界/脏数据 |
| `tests/unit/test_rules_capacity.py` | 13 | 容量远超需求：双条件阈值、参会人数缺失时跳过 |
| `tests/unit/test_rules_high_value.py` | 13 | 高价值设备低优先级：白名单、角色判定 |
| `tests/unit/test_rules_overuse.py` | 16 | 资源过度占用：跨天切分、区间合并、单日累计 |
| `tests/unit/test_rules_idle.py` | 10 | 长期闲置 |
| `tests/unit/test_registry.py` | 6 | 规则注册表：逐条隔离、单条崩溃不影响整体 |
| `tests/unit/test_templates.py` | 29 | 3 语气 × 3 角色共 9 套模板全渲染、缺字段、超长截断 |
| `tests/unit/test_json_utils.py` | 17 | JSON 六级容错解析、多模态 content 兼容 |
| `tests/test_notify_chain.py` | 16 | 文案生成四级降级阶梯 |
| `tests/test_extract_chain.py` | 34 | 参会人数抽取：AI 优先、正则兜底、失败返回 None |
| `tests/unit/test_llm_builder.py` | 12 | LLM 出口：真分支参数、成本护栏、假 LLM 夹具可连打 |
| `tests/unit/test_dedup.py` | 31 | 去重指纹、三种后端、Redis 故障降级 |
| `tests/unit/test_db_reads.py` | 34 | 数据库读取层：JOIN 结果映射、固定查询数、N+1 护栏 |
| `tests/unit/test_notify_service.py` | 36 | 角色语气映射、事实优先级、收件人解析、派发幂等 |
| `tests/unit/test_conflict_service.py` | 26 | 扫描编排：四段切分、不在持有连接时调 AI、汇总计数 |
| `tests/unit/test_notify_events.py` | 23 | 事件载荷解析、受众判定、订阅接线 |
| `tests/unit/test_notify_tools.py` | 15 | Agent 工具契约与失败处理 |
| `tests/unit/test_config.py` | 19 | 环境模板、端口口径、驱动规范、同步引擎惰性化 |
| `tests/api/test_conflicts_api.py` | 12 | `GET /conflicts/scan` 契约与鉴权 |
| `tests/api/test_notify_api.py` | 19 | `POST /notify/generate` 契约、身份安全、幂等 |
| `tests/test_scheduler.py` | 18 | 周期任务：可中断睡眠、异常不杀循环、抖动 |
| `tests/test_events.py` | 19 | 事件总线：非阻塞发布、异常隔离、载荷只读 |
| `tests/test_live_smoke.py` | 3 | 真实 API 冒烟（默认跳过） |
| **合计** | **450** | 其中 3 条为 live 用例，默认跳过 |

> 表中数字为 `pytest --collect-only` 的实际收集数（含参数化用例），不是测试函数个数。

### 为什么单独测「数据库读取层」

`test_db_reads.py` 用「按调用顺序返回预设结果集」的假会话，把 SQL 返回的元组喂给真实实现。
值得单独成文件的原因是：`load_order_snapshot` 用**一条 JOIN 取 11 个字段并按下标取值**，
`load_rule_context` 用**固定 5 条查询**组装快照 —— 下标写错、JOIN 少一张表、多一次惰性加载，
都不会在纯函数测试里暴露，只会在连上真库那一刻炸掉。该文件同时断言
「订单查询带 `LIMIT`」「管理员一条 JOIN 查完，不做 N+1」，把性能约束固化成用例。

---

## 五、主文档 10.2 强制降级用例（模块 7）

文档要求「必须覆盖两类降级用例」，对应实现与用例：

| 要求 | 用例 | 断言 |
| :--- | :--- | :--- |
| 大模型返回非 JSON 时降级为自然语言 | `test_notify_chain.py::test_prose_is_kept_as_content` | `source == "ai_text"`，`degraded_reason == "json_parse_failed"`，正文复用模型原文、标题回退模板 |
| 外部 API 超时降级 | `test_notify_chain.py::test_timeout_degrades_to_template` | 真跑 `asyncio.wait_for` 超时分支（假模型 `sleep=0.6` + `timeout=0.05`），断言 `degraded_reason == "timeout"` 且耗时 < 0.5s |
| 外部 API 调用失败降级 | `test_notify_chain.py::test_api_error_degrades_to_template` | 模型抛 `RuntimeError`，断言 `degraded_reason == "api_error"` |
| AI 总开关关闭 | `test_notify_chain.py::test_ai_disabled_never_calls_the_model` | `AI_ENABLED=False` → `source == "template"`，`degraded_reason == "ai_disabled"`，且注入「一调用就抛异常」的模型证明它确实没被调用 |

> 超时用例**不是 mock 掉超时逻辑**，而是用真实的 `asyncio.wait_for` 走完整链路 —— mock 掉超时等于没测。
> 同理，「API 失败」夹具必须覆盖 `_generate` 而不是 `_call`：`BaseChatModel` 上并不存在 `_call`，覆盖它只是死代码，异常永远不会抛出。

---

## 六、模块 7 关键用例说明

### 6.1 契约字段形状（防回归）

| 用例 | 断言 |
| :--- | :--- |
| `test_conflicts_api.py::test_scan_returns_the_four_contract_fields` | `set(item) == {"conflictType", "orderIds", "suggestion", "ruleCode"}`，多一个少一个都失败 |
| `test_conflicts_api.py::test_scan_never_leaks_snake_case_keys` | 响应里不得出现 `conflict_type` 等下划线键名 |
| `test_notify_api.py::test_generate_returns_exactly_title_and_content` | `set(data) == {"title", "content"}`，内部字段（降级来源等）不得泄漏 |
| `test_conflicts_api.py::test_idle_conflict_returns_empty_order_ids` | 无关联订单时返回 `[]` 而非 `null` |

### 6.2 身份与事实的来源安全

| 用例 | 断言 |
| :--- | :--- |
| `test_notify_api.py::test_payload_user_id_cannot_redirect_the_notification` | 载荷塞 `userId=999` 不会让通知发给 999（主文档 5.1 防身份伪造） |
| `test_notify_api.py::test_payload_cannot_overwrite_database_facts` | 载荷的场地名不能覆盖库中事实，不会被 AI 写进正式通知 |
| `test_notify_service.py::test_identity_keys_in_payload_are_dropped` | `userId` / `receiverId` / `notifyType` 等键一律被丢弃 |
| `test_notify_events.py::test_identity_keys_never_reach_the_facts` | 事件载荷里的身份字段同样不得进入文案 |
| `test_notify_api.py::test_payload_cannot_override_the_tone` | 语气只认顶层 `type`，载荷里的 `notifyType` 无效 |
| `test_conflicts_api.py::test_scan_rejects_a_forged_token` | 用别的密钥签的 token 返回 401 |

### 6.3 架构约束（主文档 4.2 / 9.3 / 12.1）

| 用例 | 断言 |
| :--- | :--- |
| `test_conflict_service.py::test_scan_job_does_not_hold_a_session_while_calling_ai` | 调 AI 时打开的会话数为 0 —— 一次调用 3~20 秒，占死连接池对 2 核 2G 是致命的 |
| `test_conflict_service.py::test_scan_job_opens_only_the_read_transaction_when_nothing_hits` | 无命中时不进入写库段 |
| `test_conflict_service.py::test_scan_job_works_with_ai_fully_disabled` | `AI_ENABLED=False` 时扫描链路完整可用（4.2「移除 AI 后降级为硬冲突检测」） |
| `test_notify_tools.py::test_tool_signature_has_no_database_session` | Tool 签名里没有任何会话对象（9.3「Tool 内禁止直接使用 AsyncSession」） |
| `test_notify_tools.py::test_tool_is_not_registered_as_a_public_endpoint` | 内部 Tool 没有出现在任何 HTTP 路由里 |
| `test_notify_service.py::test_dispatch_survives_ai_outage` | AI 全挂时通知仍以模板文案落库 |

### 6.4 成本护栏与幂等

| 用例 | 断言 |
| :--- | :--- |
| `test_notify_service.py::test_dispatch_writes_one_row_per_recipient` | 同一角色的多个收件人只调用一次大模型（100 个管理员不该变成 100 次 API 调用） |
| `test_notify_service.py::test_dispatch_is_idempotent_within_ttl` | 第二轮扫描既不再写库，也不再调用模型 |
| `test_notify_service.py::test_dispatch_reuses_precomputed_draft` | 接口层已生成的文案不会重复生成 |
| `test_notify_api.py::test_repeat_request_is_deduplicated` | 接口层重复请求只落库一次 |
| `test_notify_api.py::test_different_tone_is_not_deduplicated` | 提醒与致歉是两条不同语义的通知，不被同一指纹压掉 |
| `test_notify_service.py::test_dispatch_releases_the_slot_when_insert_fails` | 写库失败必须归还去重名额，否则一次瞬时故障会压掉一整天 |
| `test_dedup.py`（Redis 相关用例） | Redis 抛异常时降级到兜底后端，绝不向外抛 |

### 6.5 后台任务（主文档 12.1）

| 用例 | 断言 |
| :--- | :--- |
| `test_scheduler.py::test_stop_interrupts_a_long_sleep_within_a_second` | 间隔 300s 时 `stop()` 仍能在 1 秒内返回（用 `asyncio.sleep(interval)` 会干等 5 分钟） |
| `test_scheduler.py::test_job_exception_does_not_kill_the_loop` | 单轮抛异常后循环继续，不会让推送永久停摆 |
| `test_scheduler.py::test_stop_cancels_a_job_that_hangs` | 任务卡死时强制取消，不无限期等待 |
| `test_events.py::test_publish_does_not_wait_for_a_slow_subscriber` | `publish` 在 0.1s 内返回 —— 订单创建接口不应为通知推送的耗时买单 |
| `test_events.py::test_subscriber_exception_does_not_reach_the_publisher` | 通知推送失败不影响业务主流程 |
| `test_events.py::test_duplicate_subscription_is_ignored` | 重复注册不会导致一次事件发两条通知 |

### 6.6 环境与规范

| 用例 | 断言 |
| :--- | :--- |
| `test_config.py::test_env_example_has_no_unknown_keys` | `.env.example` 里多一个 `Settings` 不认识的键，照抄模板建 `.env` 会导致启动 `ValidationError`（`extra="forbid"`，已实测） |
| `test_config.py::test_only_the_allowlist_may_mention_the_sync_driver` | 全仓库源码不得出现 `mysql+pymysql`，唯一例外是 `app/core/config.py`（为 Alembic 保留，主文档 3.4） |
| `test_config.py::test_sync_engine_stays_inside_the_infrastructure_layer` | 业务层（`api` / `services` / `agent`）不得引用同步引擎或同步连接串 |
| `test_config.py::test_sync_engine_is_not_created_at_import_time` | AST 层面禁止在模块顶层引用 `sync_database_url`（否则 import 即需 `pymysql`） |
| `test_config.py::test_importing_database_module_leaves_the_sync_engine_unbuilt` | 导入 `app.core.database` 后模块字典中不得出现 `sync_engine`（惰性化未被改回的运行时证据） |
| `test_config.py::test_alembic_env_still_consumes_the_sync_url` | 反向护栏：`alembic/env.py` 仍在用 `settings.sync_database_url`，删掉它迁移会 `AttributeError` |
| `test_config.py::test_env_example_contains_no_real_secrets` | 模板里只有占位符，无真实密钥 |
| `test_config.py::test_env_example_port_matches_the_code_default` | 模板的 `DB_PORT` 与代码默认值一致；不一致时忘改配置的人只会看到一句「连接被拒绝」 |
| `test_config.py::test_db_port_is_the_local_tunnel_entry_port` | 代码默认值为 **3308**（本机隧道入口端口）。**刻意不钉主文档 6.1 模板里的 3307** —— 那是云服务器侧 MySQL 的监听端口，与代码实际连接的端口不是同一个数，详见 `docs/database.md` 2.1 |
| `test_templates.py` | 9 套模板全部能渲染，缺字段不抛异常，超长自动截断 |

---

## 七、用例清单（核心调度 Agent 模块）

编号规则：`AGENT-<类型>-<序号>`。全部用例须在**断网**状态下可跑通（10.2：真实 API 不进常规用例）。

### 7.1 单元与契约（AGENT-U）

| 编号 | 用例 | 输入 | 预期 | 状态 |
| --- | --- | --- | --- | --- |
| AGENT-U-01 | `query_spaces` 参数异常 | `capacity=0`、时间倒置 | 返回业务错误，不抛未捕获异常 | 待实现 |
| AGENT-U-02 | `query_devices` 过滤可用性 | 库中混入 `device_status=2`、`available_count=0` | 结果中不含这些设备 | 待实现 |
| AGENT-U-03 | `space_type` 映射 | 需求含"展厅" | 实际传给 Tool 的是 `2` | 待实现 |
| AGENT-U-04 | trace 映射 | 构造含 `tool_calls` 的 messages | `step` 从 1 递增、`result` 非空、`timestamp` 格式 `YYYY-MM-DD HH:mm:ss` | 待实现 |
| AGENT-U-05 | timestamp 单调 | 多步 trace | 各步 `timestamp` 不相同且递增 | 待实现 |

### 7.2 五个决策场景（AGENT-S）

对应主文档 4.4 模块 4 的表格，是评审与答辩直接看的证据。**断言按 6.9 种子数据的实际值写**（场地 8：会议室×3、展厅×2、多功能厅×2、户外×1；设备 15：投影仪×4、音响×4、显示屏×3、无人机×2、直播设备×2）。

| 编号 | 场景 | 断言要点 | 状态 |
| --- | --- | --- | --- |
| AGENT-S-01 | A 预算降级（800 元 / 40 人 + 双投影） | 保住场地，设备降级为单投影，`plan.reason` 说明降级原因 | 待实现 |
| AGENT-S-02 | B 场地拆分（无 40 人场地 → 拆两个小的） | 生成两个时段对齐的小场地方案 | 待实现 |
| AGENT-S-03 | C 设备替代（投影仪全占用） | 推荐替代设备（如 LED 显示屏），而非返回无方案 | 待实现 |
| AGENT-S-04 | D 需求矛盾（40 人 / 500 元） | `plan` 为 `null`，`message` 含至少 3 条修改建议，不编造方案 | 待实现 |
| AGENT-S-05 | E 活动合并（同团队连续两场） | 给出合并建议并说明节省的资源 | 待实现 |

**种子数据变更时这些用例必须同步修改**——断言与数据强耦合。

### 7.3 异常与降级（AGENT-E）

| 编号 | 用例 | 触发方式 | 预期 | 状态 |
| --- | --- | --- | --- | --- |
| AGENT-E-01 | 模型返回非 JSON | 假模型返回自然语言文本 | HTTP 200，`plan=null`，`needConfirm=true`，`message` 为模型原文 | 待实现 |
| AGENT-E-02 | 模型调用超时 | 假模型抛 `TimeoutError` | 200，友好提示，`trace` 保留中断前的步骤 | 待实现 |
| AGENT-E-03 | 无可用资源 | 工具返回空集 | `plan=null`，`backupPlan=null`，明确说明无方案 | 待实现 |
| AGENT-E-04 | 工具抛异常 | 桩函数抛错 | 不 500，降级提示 | 待实现 |

### 7.4 接口（AGENT-I）

| 编号 | 用例 | 预期 | 状态 |
| --- | --- | --- | --- |
| AGENT-I-01 | 正常调用 | 200，符合统一响应体，`data.trace` 非空且字段齐全 | 待实现 |
| AGENT-I-02 | 无 `Authorization` 头 | 401 | 待实现 |
| AGENT-I-03 | `text` 为空字符串 | 422（`min_length=1` 生效，不空跑模型） | 待实现 |
| AGENT-I-04 | 请求体夹带 `userId` | 被忽略，实际使用 JWT 中的用户 | 待实现 |
| AGENT-I-05 | 响应体不含敏感信息 | 响应中无 API Key、数据库连接串 | 待实现 |

### 7.5 并发与事务（AGENT-C）

| 编号 | 用例 | 预期 | 状态 |
| --- | --- | --- | --- |
| AGENT-C-01 | 两个协程同时锁定同一场地同一时段 | 恰好一个成功，另一个收到冲突提示 | 待实现 |
| AGENT-C-02 | 设备数量扣减 | 锁定后 `available_count` 正确递减，回滚时不减 | 待实现 |

**AGENT-C-01 是本模块唯一无法靠"看代码正确"来保证的用例。** 主文档 5.5 的顺序写对了才过，写错了在低并发下测不出来，演示当天并发上来就翻车。

> ⚠️ **前置依赖**：AGENT-C-01 依赖 `reserve_order` 上的 `idx_space_time`，而该索引**目前不在 Alembic 初始迁移脚本里**（见 `docs/database.md` 6.2）。索引缺失时该用例即便通过也不代表生产行为正确（锁范围会被放大）。补齐索引前，本用例的结论不可作为并发正确性的证据。

---

## 八、覆盖率要求

| 范围 | 目标 | 当前（2026-09-27 合并后） |
| :--- | :--- | :--- |
| `app/agent/`（主文档要求，模块 4） | ≥ 80% | **96%**（当前该目录下只有模块 7 的代码） |
| `app/services/rules/`（模块 7） | 100% | **100%**（8 个文件全部达标） |
| `app/services/`（模块 7） | ≥ 85% | **≥ 90%**（notify_service 100%、conflict_service 93%、dedup 90%、notify_events 98%） |
| `app/agent/chains/`（模块 7） | ≥ 85% | **≥ 93%**（llm 与 notify_chain 100%、extract_chain 97%、json_utils 93%） |
| 全量 `app/` | — | 94%（1784 语句 / 103 未覆盖） |

> 全量从合并前的 96% 降到 94%，唯一原因是团队新引入的 `app/schemas/agent.py`（25 语句、0%，模块 4 尚未实现用例）。**剔除该文件后仍是 96%**，模块 7 自身的覆盖率没有下降。

覆盖率是结果不是目标——为凑数字写空用例视为未完成。

```bash
cd backend
python -m pytest tests --cov=app --cov-report=term-missing
```

阈值写入 `backend/pytest.ini` 的 `--cov-fail-under`，由 CI 卡住。

**仍未被覆盖的部分及其原因**（不是遗漏，是无真实 IO 时不可达）：

| 位置 | 为什么测不到 |
| :--- | :--- |
| `app/core/database.py`（50%） | `create_async_engine` 的实际建连、`dispose`、真实会话生命周期，以及同步引擎的惰性创建分支。离线跑不连 MySQL，只能由第十节的端到端步骤验证 |
| `app/services/conflict_service.py` 271-354 | `persist_conflict_notifications` 的真实写库分支 —— 需要能真正 `flush` 的会话 |
| `app/services/dedup.py`（90%） | Redis 客户端真实收发路径（其余已由 `FakeRedis` 桩覆盖降级行为） |
| `app/schemas/agent.py`（0%） | 模块 4 的契约模型，对应用例（AGENT-\*）尚在「待实现」状态 |

> 这些位置用假会话强行「点亮」只会得到假绿：断言的是桩的行为，不是真实驱动的行为。

---

## 九、测试库规范（主文档 6.8）

- 连 `smart_scheduler_test`，不连开发库
- 用例结束后回滚，不残留数据
- 无建库权限时退回备选方案：`test_` 前缀表 + `TRUNCATE`
- **禁止测试写 `reserve_order` 正式表**

---

## 十、端到端验证步骤（模块 7）

离线测试全绿只说明逻辑正确，落库与真实模型还需按下面步骤人工验证一次：

1. 配好 `.env`（数据库、Redis、大模型），`uvicorn app.main:app --reload`
2. 打开 `/docs` 能正常展示，`GET /api/v1/health` 返回 `status: ok`
3. 造两笔**同一用户、相邻 10 分钟**的有效订单 → `GET /api/v1/conflicts/scan` 应命中 `continuous_activity`
4. `POST /api/v1/notify/generate` 传 `{"type": "延期致歉", "orderInfo": {"orderId": <真实订单ID>}}`
   → 返回 `{title, content}`，且 `SELECT * FROM notify_message ORDER BY id DESC` 能看到新行，`notify_type=2`
5. 设 `CONFLICT_SCAN_INTERVAL_SECONDS=10` 观察后台周期任务自动推送
6. **重复跑两轮，确认第二轮不再重复写库**（验证幂等）
7. 把 `AI_ENABLED` 改成 `false` 重启，重复步骤 4 —— 应返回模板文案且正常落库（13.1 应急预案）

> **前置条件**：以上步骤需要 `backend/.env` 含有效的 `DB_PASSWORD` 与已建立的 SSH 隧道（`ssh -L 3308:127.0.0.1:3307 <user>@<云服务器IP> -N`）。当前这两项均未就绪，故第十节整体处于**未执行**状态。
