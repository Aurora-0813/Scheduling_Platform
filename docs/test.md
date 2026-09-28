# 测试用例文档

> 依据《项目文档.md》10.1~10.3（测试规范）、6.8（测试库）、6.9（种子数据）、11.1~11.2。
> 接口变更或种子数据变更时，本文件须同步更新。

---

## 一、环境基线

> 用途：M4 联调时他人照此复现。**本小节必须与实际执行结果一致，未核对项如实标注。**

| 项 | 值 | 状态 |
| --- | --- | --- |
| 核对日期 | 2026-09-27（2026-09-24 首核） | ✅ 已核对 |
| Python 版本 | 3.11.9 | ✅ 已核对 |
| conda 环境 | `smart_dev`（**路径因机器而异**：模块 4 为 `F:\conda_envs\envs_dirs\smart_dev`，模块 7 为 `D:\conda\envs_dirs\smart_dev`） | ✅ 已核对 |
| 依赖安装方式 | `pip install -r backend/requirements.txt`（版本全量 `==` 锁定） | ✅ 已执行 |
| 关键版本 | langchain 1.3.11 / langchain-openai 1.5.0 / langchain-classic 1.0.0 / langchain-core 1.6.4 / langgraph 1.2.12 | ✅ 已核对 |
| 测试工具版本 | pytest 9.1.1 / pytest-asyncio 1.4.0 / pytest-cov 7.1.0 | ✅ 已核对 |
| 数据库驱动 | asyncmy 0.2.10 | ✅ 已安装 |
| 认证依赖 | passlib 1.7.4 + bcrypt 4.0.1（哈希自检 `verify: True`） | ✅ 已核对 |
| 锁文件 | `backend/requirements.lock`（68 行，`pip freeze` 生成） | ✅ 已生成 |
| `.env` | 已存在（含 `DB_*` / `JWT_SECRET_KEY`）；**LLM 三项已填且实测可用**（`qwen-plus` + DashScope 兼容模式，2026-09-27 真实调用跑通） | ✅ 已核对 |
| 数据库连通 | SSH 隧道 `localhost:3308` → 远程 3307，开发库可读 | ✅ 已核对 |
| DDL 版本 | 未与 6.7 逐条对比 | ⛔ 未闭环：需集成组确认 |
| 种子数据条数 | 场地 8 / 设备 15 / 预约 10 | ✅ 已核对（开发库实测） |
| 测试库 | `smart_scheduler_test` | ⛔ 无权访问（错误码 1044） |

**仍未闭环的两项**：DDL 版本需集成组确认；测试库权限缺失（见第五节）。

`.env` 的 **LLM 三项已不再是缺口**：2026-09-27 用 `qwen-plus` 真实调用跑通了一次
场景 A（4 步 trace / 18.3 秒 / `success=true`，原始输出见 `stage-05-completion.md` §3.2）。
决策质量那一层因此有了第一条真实证据，也随之暴露了一个**标准层面**的问题：
`AGENT-S-01` 的预期结果「设备降级为单投影」在数据模型里**算不出来**
（`device_resource` 无价格字段），详见 3.2 末尾。

> **该标准已于 2026-09-27 经项目群裁定为 A + C 并落地**：A 把 `AGENT-S-01` 的预期改为
> 「保住场地 + 说明为何不需降级」；C 新增 `AGENT-S-06`（要两台直播设备、库里只有一台可借）
> 承接「真的降级」那半边，其前提由 `test_seed_supports_the_degradation_case` 对着真库验。
> 选项 B（补设备单价口径）未采纳。本节 §3.2 保留裁定前的推理原文作为留痕。

### 运行夹具的两个环境要点（**照抄，否则用例会偶发失败**）

1. **全部异步用例必须跑在同一个事件循环里**（`pytest.ini` 的
   `asyncio_default_test_loop_scope = session`）。`asyncmy` 的连接与创建它的循环绑定，
   而连接池是进程级的；每条用例换循环时，池里旧连接指向已关闭的 loop，表现为
   `asyncmy.errors.InternalError: network operation failed` 包着
   `AttributeError: 'NoneType' object has no attribute 'send'`。
   症状是**只有复用池化连接的用例偶发失败**，极易被误判成「数据库不稳定」。
2. **跑测试请用 conda 环境 `smart_dev` 的解释器**。裸 `python` 是 miniconda base（3.13），
   缺 `asyncmy` 与整个 langchain 栈：

```bash
cd backend && PYTHONIOENCODING=utf-8 "F:/conda_envs/envs_dirs/smart_dev/python.exe" -m pytest -q
```

> 架构对齐后说明（§3.4 / §10.2）：
> - 后端已切换为异步架构：`asyncmy` 驱动 + `AsyncSession` + `async def` 端点，`get_db` 为 `async def`；本地自测如用 SQLite 需额外安装 `aiosqlite` 并将连接串改为 `sqlite+aiosqlite://`（仅自测，联调/正式一律云库）。
> - 身份一律从 JWT（演示 `X-User-Id`）解析，请求体不再传 `userId`（§5.1）。
> - `main.py` CORS `allow_credentials` 置 False（用 `X-User-Id` 头鉴权，规避 `*`+凭证冲突）。
> - 小程序端：`getOrders` 改用契约接口 `GET /api/v1/orders/my`。

**未核对项的阻塞原因**：`backend/.env` 不存在，无数据库连接凭据；且 6.7 的 DDL 与 6.9 的种子数据尚未由集成组执行。补齐后须重跑基线核对并更新本表。

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

### 后续用例的夹具方案

`tests/conftest.py` 里的实际夹具叫 **`ScriptedChatModel`**（工厂夹具名 `scripted`）。
它就是上文 `StubChatModel` 的定稿版，三处与冒烟脚本里的最小版不同：

| 差异 | 为什么 |
| --- | --- |
| 多了 `delay: float`，`_agenerate` 里 `await asyncio.sleep(delay)` | `AGENT-E-02`（超时）要有一个「调用开始后不返回」的模型，不 sleep 就测不出 `wait_for` 分支 |
| 同时实现 `_generate` 与 `_agenerate` | `create_agent` 走异步路径；只实现同步版会拿到 `NotImplementedError` |
| 响应耗尽后**重复最后一条**（`min(cursor, len-1)`） | 用例少写一条响应时不该拿到 `IndexError`；同时使「末尾必须是纯文本 AIMessage」成为一条**显式约定**（见 `test_agent_schedule.py` 模块 docstring） |

```python
class ScriptedChatModel(BaseChatModel):
    responses: list[AIMessage] = Field(default_factory=list)
    delay: float = 0.0
    _cursor: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "scripted-chat-model"

    def bind_tools(self, tools, **kwargs):
        """create_agent 必需。基类默认实现直接抛 NotImplementedError。"""
        return self

    def _next(self) -> ChatResult:
        idx = min(self._cursor, len(self.responses) - 1)
        self._cursor += 1
        return ChatResult(generations=[ChatGeneration(message=self.responses[idx])])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._next()

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.delay:
            await asyncio.sleep(self.delay)
        return self._next()
```

说明：

- `bind_tools` 返回 `self` —— 夹具不需要真正绑定工具，只要不抛异常即可
- `_cursor` 用 `PrivateAttr` 而非普通字段，否则会被 pydantic 当成模型字段参与校验
- 响应列表按调用顺序消费：中间几条返回带 `tool_calls` 的 `AIMessage`，**最后一条必须是纯文本**

### 三个 autouse 护栏夹具（`conftest.py`）

| 夹具 | 挡什么 | 怎么被验 |
| --- | --- | --- |
| `_offline_guard` | 到非回环地址的任何 socket 连接 | `test_guard_offline_is_actually_armed` 主动触发一次 |
| `_db_readonly_guard` | `INSERT/UPDATE/DELETE/DDL` 等全部写语句 | `test_guard_db_writes_are_actually_blocked` 主动触发一次 |
| `reset_metrics` | 埋点计数跨用例污染 | 每个用例前后各清零一次 |

前两个是**否定性结论的护栏**（「断网跑通」「没写正式表」），只报「没报错」证明不了
——没报错也可能是拦截根本没生效。所以各配一条主动触发它们的用例，把结论变成可执行证据。

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
| AGENT-U-01 | `query_spaces` 参数异常 | `capacity=0`、时间倒置、时间不可解析、`space_type` 越界 | 返回业务错误，不抛未捕获异常 | ✅ 5 例通过 |
| AGENT-U-02 | `query_devices` 过滤可用性 | 库中混入 `device_status=2`（id=13）、`available_count=0`（id=15） | 结果中不含这些设备 | ✅ 6 例通过 |
| AGENT-U-03 | `space_type` 映射 | 需求含"展厅" | 实际传给 Tool 的是 `2` | ✅ 4 例通过 |
| AGENT-U-04 | trace 映射 | 构造含 `tool_calls` 的 messages | `step` 从 1 递增、`result` 非空、`timestamp` 格式 `YYYY-MM-DD HH:mm:ss` | ✅ 11 例通过 |
| AGENT-U-05 | timestamp 单调 | 多步 trace，含**同一秒**与**乱序**两种输入 | 各步 `timestamp` 不相同且递增 | ✅ 4 例通过 |

`AGENT-U-02` 的两条关键用例是**见证者式**的：先断言 service 桩**确实返回**坏设备（id=13 / 15），
再断言 Tool 把它们滤掉了。少了前半条，后半条在「数据里本来就没有坏设备」时也会过——
分不清是 Tool 真在滤还是运气。

### 3.2 六个决策场景（AGENT-S）

对应主文档 4.4 模块 4 的表格，是评审与答辩直接看的证据。**断言按 6.9 种子数据的实际值写**（场地 8：会议室×3、展厅×2、多功能厅×2、户外×1；设备 15：投影仪×4、音响×4、显示屏×3、无人机×2、直播设备×2）。

| 编号 | 场景 | 断言要点 | 状态 |
| --- | --- | --- | --- |
| AGENT-S-01 | A 预算与设备（800 元 / 40 人 + 双投影） | **保住场地 + `reason` 非空且说明「无需降级」**（原标准为「设备降级为单投影」，前提算不出已裁定作废，见文末） | ✅ 通过（透传口径；标准已按 A 改写） |
| AGENT-S-02 | B 场地拆分（无 40 人场地 → 拆两个小的） | 生成两个时段对齐的小场地方案 | ✅ 通过（口径见下） |
| AGENT-S-03 | C 设备替代（投影仪全占用） | 推荐替代设备（如 LED 显示屏），而非返回无方案 | ✅ 通过（口径见下） |
| AGENT-S-04 | D 需求矛盾（40 人 / 500 元） | `plan` 为 `null`，`message` 含至少 3 条修改建议，不编造方案 | ✅ 通过（口径见下） |
| AGENT-S-05 | E 活动合并（同团队连续两场） | 给出合并建议并说明节省的资源 | ✅ 通过（口径见下） |
| AGENT-S-06 | 设备数量不足（要两台直播设备，库里只有 1 台可借） | **降级为可借数**：`deviceIds` 只有可借的那一台、`reason` 原样透传、`trace` 留有查询这一步 | ✅ 通过（透传口径；前提真成立，见下） |

`AGENT-S-06` 是 2026-09-27 按裁定 C 新增的。它的前提**不依赖时段参数、也不依赖尚未定论的扣减口径**：种子 `直播设备×2` 里 id=15 是 `status=1` 但 `available_count=0`，被 `query_devices` 的可用性过滤滤掉，于是这个类型只剩 id=14 一台。这比「投影仪在某时段被占满」更适合当降级用例——后者受 `query_devices` 签名无时段参数所限，**进不了主链路**。

#### ⚠️ 六条 S 用例**验的不是模型的判断**

假模型把「该怎么决策」当作**输入**喂进来（它按脚本调 `query_spaces` → `query_devices` →
`submit_plan`），系统侧全是真的：真的 `create_agent`、真的工具查开发库、真的 trace 提取、
真的统一响应体。所以这六条验的是**透传与形状**：

- 模型写在 `reason` 里的降级/替代理由、备选方案（含 `backup_plan` snake_case 入参）、
  矛盾场景下的多条修改建议，是否**一字不少**地到达用户（这是主文档 10.2 与契约的要求）
- 两次锁定的 trace 是否各自成步、替代路径是否留痕、`deviceIds` 是否被系统擅自改写

**它们证明不了「800 元该不该降级」「40 人该不该拆场地」——那是模型的判断质量。**
决策质量需要真实 LLM。`2026-09-27 19:58` 起这一层有了第一条真实证据（`qwen-plus`
跑场景 A，原始输出见 `stage-05-completion.md` §3.2），结论如下：

> **`AGENT-S-01` 的断言「设备降级为单投影」在现有数据模型下无法达成。**
> 模型交出的是 `deviceIds=[1, 2]`（双投影），并在 `reason` 里写明「预算 800 元正好匹配，
> 有 4 台可用投影仪，无需任何降级」。这个判断与数据是自洽的：`device_resource` 表
> **没有价格字段**（`docs/seed.sql:83-84`），设备不计费；唯一与预算有关的 `space_resource.budget`
> 恰好等于预算上限，没有超支；`capacity>=40 AND space_type=2` 也只命中这一个场地。
> 也就是说「预算与设备冲突」这个前提**没有任何可计算依据**，而 Prompt 又明文禁止
> 模型编造价格——任何模型都算不出「双投影超支」。**需裁定的是标准措辞，不是模型的输出。**
> 详见 `stage-05-completion.md` §3.2 与 §6 #1（含三个候选选项）。
>
> ✅ **已裁定并落地（2026-09-27）**：采纳 **A + C**。A —— `AGENT-S-01` 的断言改为
> 「`plan` 非空、`spaceId` 命中、`reason` 非空且说明无需降级」；C —— 新增 `AGENT-S-06`
> 与前提护栏 `test_seed_supports_the_degradation_case`。「真的降级」这半边从此有真用例。
> 选项 B（补设备单价口径）未采纳，仍留在集成组的账上。上面这段推理**原文保留**，
> 作为「标准为什么改」的留痕。

同一轮真实调用还暴露两条（都只可能由真实调用暴露）：模型把「下周三」算成
**2026-10-04**（当天是星期日，正确应为 **09-30**）；模型未调 `lock_resources`，
改为先问用户，因此 `create_order` 与 `agent_trace` 补写在真实路径下**尚未被走到**。

六条场景各自的**前提**（种子数据里确实存在「预算恰好卡在场地价上」「没有 40 人的会议室」
「显示屏可借」「直播设备只剩一台可借」这些约束）单独由 `test_seed_supports_the_five_scenarios`
与 `test_seed_supports_the_degradation_case` 对着**真库**验——那部分不依赖模型，是真实结论。

⚠️ 但要注意：`AGENT-S-01` 的那条前提（「预算恰好卡在场地价上」）**只能证到「场地没有超支」，
证不到「设备会超支」**——两者之间隔着「设备是否计费」这个数据模型问题。用例通过不代表
预期结果可达，这是本次真实调用揭出来的教训。**A + C 裁定正是对这条教训的处置**：
A 把标准改成前提确实可达的那件事，C 用一条前提能算出来的用例承接「降级」语义，
于是「用例通过」与「预期可达」在两条上重新对齐。

**种子数据变更时这些用例必须同步修改**——断言与数据强耦合。

### 7.3 异常与降级（AGENT-E）

| 编号 | 用例 | 触发方式 | 预期 | 状态 |
| --- | --- | --- | --- | --- |
| AGENT-E-01 | 模型返回非 JSON | 假模型返回自然语言文本；另有一条**正文里带 ```json 围栏**的可救回样例 | HTTP 200，`plan=null`，`needConfirm=true`，`message` 为模型原文 | ✅ 2 例通过 |
| AGENT-E-02 | 模型调用超时 | 假模型 `delay` 超过（被改小的）`AGENT_TIMEOUT` | 200，友好提示，`trace` 保留中断前的步骤 | ✅ 2 例通过 |
| AGENT-E-03 | 无可用资源 | 工具返回空集（10000 人户外场地） | `plan=null`，`backupPlan=null`，明确说明无方案 | ✅ 1 例通过 |
| AGENT-E-04 | 工具抛异常 | 工具依赖的 service 抛 `RuntimeError`；另有一条整条流抛错 | 不 500，降级提示 | ✅ 2 例通过 |

`AGENT-E-02` 记两处实证：

1. 阈值被 `monkeypatch` 改成 0.05 秒——**不改的话这条用例要跑满 30 秒**。
2. 第二条用例替换的是 `collect_stamped_messages` 而不是用慢模型。原因具体：慢模型在
   **第一次模型调用**就卡住，一步都不会被打点，验不出「保留」这件事。这正是
   `run_schedule` 把 `stamped` 提在 `wait_for` **外面**、以 sink 传进去的全部理由
   ——`wait_for` 取消协程后返回值根本拿不到，只剩这个列表。

### 7.4 接口（AGENT-I）

| 编号 | 用例 | 预期 | 状态 |
| --- | --- | --- | --- |
| AGENT-I-01 | 正常调用 | 200，符合统一响应体，`data.trace` 非空且字段齐全 | ✅ 1 例通过 |
| AGENT-I-02 | 无 `Authorization` 头 | 401（响应体仍是统一结构） | ✅ 1 例通过 |
| AGENT-I-03 | `text` 为空字符串 | **400 + `code=40001`**（`min_length=1` 生效，不空跑模型） | ✅ 1 例通过 |
| AGENT-I-04 | 请求体夹带 `userId` / `user_id` / `role` | 被忽略，实际使用 JWT 中的用户 | ✅ 3 参数化例通过 |
| AGENT-I-05 | 响应体不含敏感信息 | 响应中无 API Key、数据库连接串、JWT 密钥 | ✅ 4 例通过 |

`AGENT-I-04` 的**观察点不是「返回了 200」**——那证明不了用的是谁。用例截住
`run_schedule` 的实参逐项核对：`user_id` 必须等于 token 里的 `1`，且请求体的身份字段
不许混进需求原文。`AGENT-I-05` 另外覆盖了「缺 LLM 配置 → 503，只报字段名不回显值」，
以及 `build_model()` 显式传 `api_key`（堵死 `ChatOpenAI` 隐式读 `OPENAI_API_KEY` 的路径）。

### 7.5 并发与事务（AGENT-C）

**判据已于 2026-09-28 按蔡玉礼的「7 条断言」整条替换**，落在
`backend/tests/test_agent_concurrency.py`（10 例：8 例 `xfail(strict)` + 2 例**能过**）。
设 `available_count = 2`（取开发库实测容量为 2 的**设备 id=8「音响04」**）：

| 编号 | 用例（测试函数） | 预期 | 状态 |
| --- | --- | --- | --- |
| AGENT-C-01 · 断言1 | `test_assert_1_first_order_on_free_slot_succeeds_and_is_persisted` | 无重叠订单，建第 1 单占用该设备 → 成功，`order_status=1` | ⛔ **xfail(strict)** |
| AGENT-C-01 · 断言2 | `test_assert_2_second_order_same_device_same_slot_succeeds_at_capacity` | 已有 1 单占用 T，建第 2 单**同设备**同 T → 成功（`2 ≤ cap`） | ⛔ **xfail(strict)** |
| AGENT-C-01 · 断言3 | `test_assert_3_third_order_same_device_same_slot_is_rejected` | 已有 2 单占用 T，建第 3 单同设备同 T → **拒绝，409 + `code=40901`** | ⛔ **xfail(strict)** |
| AGENT-C-01 · 断言3b | `test_assert_3b_three_concurrent_orders_on_a_cap_two_device_exactly_two_win` | **并发版**（保留原 C-01 的行锁语义）：并发 3 单 → 恰好 2 单成功、1 单被拒 | ⛔ **xfail(strict)** |
| AGENT-C-02 · 断言4 | `test_assert_4_cancel_one_of_two_frees_the_device_slot` | 已有 2 单占用 T，把其中一单 cancel（→3）→ 成功 | ⛔ **xfail(strict)** |
| AGENT-C-02 · 断言5 | `test_assert_5_after_cancel_third_order_succeeds_capacity_is_derived` | 承上，再建第 3 单同设备同 T → 成功（回落到 `1 < 2`） | ⛔ **xfail(strict)** |
| AGENT-C-01 · 断言6 | `test_assert_6_adjacent_non_overlapping_slot_succeeds_half_open` | 已有 2 单占用 T，与 T **相邻但不重叠**的 T' → 成功（**半开区间**） | ⛔ **xfail(strict)** |
| AGENT-C-01 · 断言7 | `test_assert_7_other_device_same_slot_succeeds_capacity_is_per_device` | 已有 2 单占用 T，第 3 单用**不同设备**同一 T → 成功（容量按设备各算） | ⛔ **xfail(strict)** |
| AGENT-C-01 · 契约 | `test_resource_conflict_maps_to_40901_with_http_409` | `ResourceConflictError.code == 40901` 且 `http_status == 409` | ✅ **通过**（契约事实，非待实现项） |
| 桩期实录 | `test_stub_state_is_recorded_not_glossed_over` | 桩不落库（`stub=True`、`orderId is None`），且 `available_count` 前后不变 | ✅ **通过**（桩期临时，见下） |

**「并发」这条是本模块唯一无法靠"看代码正确"来保证的用例。** 5.5 的顺序写对了才过，写错了在低并发下测不出来，演示当天并发上来就翻车。容量改为 2 之后，它的不变量从「恰好 1 单成功」升级为「**恰好 2 单成功**」（断言 3b）。

> 📌 **2026-09-28：`available_count` 口径已定「用时推导，不扣减」。**
> ① `available_count` 是**静态上限**，不是实时剩余；② 剩余量 = `available_count` −
> **该时段重叠订单数**（算出来的）；③ **不扣减、不回补、不加 §5.5 第 7 步**；
> ④ 取消后名额**自动回来**，无需回补代码。
> 理由：占用已能从 `reserve_order` 按「状态 + 时间窗口」派生，再维护计数器就是同一件事
> 存两遍，一旦不一致无法判断谁对。
> **因此 C-02 的原判据（断言 `available_count` 递减）是错的**，已整条作废——
> 按新口径该字段本就不该变。C-01/02 的现行判据 = 蔡玉礼的 **7 条断言**，已于当日晚些时候
> 逐条落地（见上表；其中第 3 条要用 **409 + `code=40901`**，已核实正式版
> `core/error_codes.py:72` 与 `core/exceptions.py:181-183` 都有，无需新造，
> 且该映射另有一例**不挂 xfail 的契约用例**单独把关）。
> **判据写完了，真实现还没到**——四条卡点见下，全部到位才能摘 `xfail`。
> 完整口径见 `docs/spec/done/README.md` 的**附录：`available_count` 口径**。

这 8 条断言的**断言是真的、被测实现还不存在**：模块 3（蔡玉礼）的 `create_order` 目前是
**只读桩**（不 `FOR UPDATE`、不 INSERT、不计数，`orderId` 恒为 `None`），桩自己的 docstring
写着「`AGENT-C-01` 的并发语义无法在桩上验，**假装能验就是假绿**」。所以标记为
`xfail(strict=True)` 而不是删掉或改成能过的形状——`strict` 保证真实现落地后会**变红
（XPASS）**，强制摘掉标记。

已用 `--runxfail` 复核过：8 条**都因桩不落库而失败**（`ok=True` 但 `orderId=None`），
不是用例自身写错；其中断言 3b 的输出正好显示桩让 3 单**全成**——这正是这段代码要抓的假绿。

**四道锁挡在前面**，缺一条都过不了：

1. 蔡玉礼按「时段重叠」改 `order_service._device_conflicts`（计数比较），
   并替换 `create_order` / `update_agent_trace` 的只读桩
2. **测试库权限**（集成组）——并发用例必须能真写、真回滚
3. `_db_readonly_guard` 对这两个文件**放开**（否则第 1、2 步到位也会被拦成
   `WriteForbiddenError`）
4. **仅断言 4/5**：模块 3 的取消入口 `PUT /api/v1/orders/{orderId}/cancel` 未交付
   （`docs/开发流程.md:381` 的冻结路径）。**不得为让它通过而改成直接 `UPDATE reserve_order`**
   ——测试禁写正式表（主文档 6.8），改成改库验的就不是实现了

另有 1 例 `test_stub_state_is_recorded_not_glossed_over` **刻意断言桩的当前行为**
（`orderId` 为 `None`、`stub=True`。库里 `available_count` 不变这句**不是桩期特征**，
按新口径它是**长期期望**，真实现落地后要保留）。前两句随 `stub` 键一起删——
它是**桩期临时用例**，真实现落地后会失败，那时应当**删除**，而不是放宽断言。
存在意义是让「C 未通过」这件事在测试输出里看得见。

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

阈值与范围都在 `pytest.ini` 的 `addopts` 里，直接 `pytest -q` 即可：

```bash
cd backend && PYTHONIOENCODING=utf-8 \
  "F:/conda_envs/envs_dirs/smart_dev/python.exe" -m pytest -q
```

范围刻意**限定 `app.agent`**，不放宽到整个 `app`：分母里混进模块 3 的桩、模块 1 的认证等
他人代码，阈值会变得没有意义。单独跑某个文件时会因达不到阈值而失败，属预期——
要临时绕过用 `--no-cov`。

### 实测结果（2026-09-27，核心调度 Agent 模块）

```
82 passed, 2 xfailed in 20.77s
Required test coverage of 80% reached. Total coverage: 92.29%

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
```

`2 xfailed` 就是 `AGENT-C-01/02`（见 3.5），不是通过。未覆盖的 38 行主要是
降级路径里的容错分支（`extract_plan_from_text` 的各类畸形输入、`_last_ai_text` 的
list 形态 content 等），已在阶段 7 完成文档里列为后续补测项。

> 📌 **2026-09-27 后续更新（A + C 落地后）**：新增 `AGENT-S-06` 与
> `test_seed_supports_the_degradation_case` 两条，当前实测为 **84 passed, 2 xfailed**，
> `app/agent` 覆盖率 **92.37%**。上面的原始输出**保留不改写**——它是 82 例那一刻的快照，
> 和 `stage-07-completion.md` 里那份一样属于证据，不是需要跟着刷新的摘要。
> （同一批还把 `lock_resources` 的时间格式接缝修了，见 `stage-05-completion.md` 遗留 #7。）

> 📌 **2026-09-28 合并后基线（最新，以此为准）：`520 tests · 518 passed · 2 skipped
> (= 2 xfail(strict)) · 0 failed · 0 errors`，退出码 0。** 本次为 rebase 到
> `origin/main`（`25b3ee3`）后的实测，**含 `tests/integration/test_migrations.py`（8 例）
> 与 `tests/api/test_agent_schedule_mock.py`（7 例），无需 `--ignore`**。
> `app/agent` 覆盖率 **92.37%**（阈值 80% 已入 `pytest.ini`）。
> 沿革：`9f30d3a` 那次是 503 passed / 505（不含 migrations，用 `--ignore` 排除），
> 更早那份「84 例」是模块 4 单分支的数字——**都是不同规模套件的快照，不要混用**。
> 五点变化必须知道：
>
> 1. **夹具改名**：合并后 `conftest.py` 是**两套**夹具并存，名字不能混用。
>    正式版的 `db_session` / `client` 走 SQLite 空库、全离线；模块 4 走开发真库的那两个
>    改名为 **`dev_db_session` / `dev_client`**。`tests/test_agent_schedule.py`（24 处）、
>    `tests/test_agent_concurrency.py`（7 处）已随之改完。理由写在 `tests/conftest.py`
>    的模块 4 段开头。
> 2. **`AGENT-I-03` 的口径第三次变更**：`text` 为空现在断言 **HTTP 400 + `code=40001`**
>    （正式版 `core/response.py` 的 `RequestValidationError` 处理器），表格行已改。
>    沿革与理由见 `stage-02-completion.md` 偏离 #3 与 `docs/api.md` 模块 4 节开头。
> 3. **三条 token/deps 用例按正式版 API 重写**：令牌改由 `create_token` 签发（旧的手写
>    `{userId, username, role, exp}` 载荷在本项目里等同伪造令牌），断言改用 `ErrorCode`；
>    其中「无 `type` 声明」那条**口径反转**——原为「容忍」，现按正式版严格拒绝
>    （`TokenInvalidError`）。
> 4. ✅ **`tests/integration/test_migrations.py` 现在能跑，8 例全过，已无需 `--ignore`。**
>    此前记的「`backend/alembic/` 遮蔽同名包、报 `No module named 'alembic.autogenerate'`」
>    **是错的**，2026-09-28 经申云飞复现反驳、复核后确认：`backend/alembic/` 无
>    `__init__.py`，只是**命名空间包**，在整条 `sys.path` 扫完前仅作候选，命中
>    site-packages 的**常规包**即让位——**不构成遮蔽**。实测 `import alembic` 解析到
>    `site-packages\alembic\__init__.py`，`python -m alembic --version` 在仓库根与
>    `backend/` 下**都是 1.20.0、退出码 0**。当时的真实原因就是 **`alembic` 没装**。
> 5. **mock 思考链的数据源已统一**（`25b3ee3`）：`mock_data.AGENT_SCHEDULE` 不再写死，
>    改为读 `docs/mock/agent_schedule.json` 的 `data` 段，响应体 **7 步 / 跨 39 秒**。
>    该 json 是唯一真源（前端屏 3 渲染、40 秒回放、13.1 应急预案三处共用）。新增
>    `tests/api/test_agent_schedule_mock.py`（7 例）守着它。
>
> 📌 **2026-09-28 晚些更新（`available_count` 判据落地后）：`526 tests · 518 passed ·
> 8 xfailed(strict) · 4 deselected · 0 failed · 0 errors`**，覆盖率仍为 **92.37%**。
> 变化只有一处：`tests/test_agent_concurrency.py` 由 4 例改为 10 例（C-01/C-02 的判据
> 按蔡玉礼的 7 条断言重写，见 §3.5），**通过数 518 不变、`xfail` 由 2 变 8**
> （多出的 6 条正是新增待实现断言）。**这 8 条不是通过**——摘 `xfail` 的四个前提见 §3.5。

> 另：本机 conda 环境 `smart_dev` 原先缺 `requirements.txt` 已声明的 `aiosqlite==0.22.1`
> 与 `alembic==1.20.0`，缺失时整个套件在**收集阶段**就 ERROR（此前误记为「image/voice
> 用例继承红」的根因即此）。已在本机补装，未改动其他依赖。
> **其他开发机同样需要补装这两项**，否则套件跑不起来——这一条仍成立。

### 断网与写库两条否定性结论的证据

- **断网**：`_offline_guard` 是 autouse 的 socket 拦截，非回环地址一律打回。
  它**不是**「拔网线」——本机关不掉网卡（要管理员权限，且会连 SSH 隧道一起断）。
  拦截比拔线更强：拔线只断外部网络，拦截能证明**每条用例**都没往外连。
  证据用例：`test_guard_offline_is_actually_armed`。
- **没写 `reserve_order`**：`_db_readonly_guard` 在 `before_cursor_execute` 里拒绝
  一切写语句（`SELECT ... FOR UPDATE` 是读，放行）。证据用例：
  `test_guard_db_writes_are_actually_blocked`。

---

## 九、测试库规范（主文档 6.8）

- 连 `smart_scheduler_test`，不连开发库
- 用例结束后回滚，不残留数据
- 无建库权限时退回备选方案：`test_` 前缀表 + `TRUNCATE`
- **禁止测试写 `reserve_order` 正式表**

### ⚠️ 当前偏差（核心调度 Agent 模块，2026-09-27）

| 要求 | 实际 | 原因 |
| --- | --- | --- |
| 连 `smart_scheduler_test` | 连的是 `smart_scheduler_dev` | 测试库报 **1044 无权访问**，属集成组 |
| 用例后回滚 | **无需回滚** | 写入被 `_db_readonly_guard` 前置拒绝，不存在需要回滚的数据 |

**未取得测试库权限前，不得声称本模块已符合 6.8。**

「回滚」这一步在连开发库的前提下本来就是错的安全手段：它保护的是「用例自己的写」，
而用例压根不许写。真正的保护是**拦截**——回滚方案在用例中途崩掉时可能留下半截数据，
拦截是每次都生效的前置拒绝。安全性更高，但**不等于合规**，偏差照记。

第三节末尾所列的 `AGENT-C-01/02` 需要真写、真回滚，**必须等测试库权限到位**后才能验。

> 2026-09-27 复核：写入路径已按 `§4.3` / `§5.5` 重构，`_create_order` 迁到
> `app/services/order_service.py::create_order`，路由只剩薄壳
> （`app/api/orders.py::create_order`）。同一份 `.coveragerc` 配置下重跑：
> `app/api/orders.py` 100%、`app/services/order_service.py` 100% —— 结论不变。

> 影响范围不止本模块：**任何**基于 `sqlalchemy.ext.asyncio` 的模块在 CI 里都会覆盖率虚低。
> 集成组若给公用 `backend/` 设了覆盖率门槛，需一并加这行配置。

---

# 附三：模块 7（AI 冲突预警与智能通知）的测试说明（并入）

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


---

## 端到端验证步骤（模块 7）


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
