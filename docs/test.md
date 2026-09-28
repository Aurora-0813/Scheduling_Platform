# 测试用例文档 —— 移动端预约与通知模块

> 覆盖预约创建/校验/状态机、消息（含提醒扫描）、WebSocket 推送、Agent 联动、端到端闭环。
> 接口统一前缀 `/api/v1/`，响应体 `{code, message, data}`；mock 用户 `user_id=1`（`X-User-Id: 1`）。
> 联调/正式测试必须连云数据库（§10.2）。

## 1. 预约创建与校验

| 编号 | 标题 | 前置条件 | 操作步骤 | 预期结果 |
|---|---|---|---|---|
| TC-01 | 创建预约成功 | 已 seed 造数 | `POST /api/v1/orders/create`，body 含合法 spaceId/deviceIds/startTime/endTime | `code=200`，`orderStatus=1`，`deviceIds` 正确 |
| TC-02 | 开始时间晚于结束时间 | 同上 | body 中 startTime >= endTime | `code=422`，提示「开始时间必须早于结束时间」 |
| TC-03 | 时间格式非法 | 同上 | startTime 用 `T` 分隔 | `code=422`，提示「时间格式应为 YYYY-MM-DD HH:mm:ss」 |
| TC-04 | 场地不存在 | 同上 | `spaceId=999` | `code=404`「场地不存在」 |
| TC-05 | 设备不存在 | 同上 | `deviceIds=[999]` | `code=404`「设备 999 不存在」 |
| TC-06 | 时段冲突 | 该场地同时段已有 1/2 状态单 | 相同场地同时段再创建 | `code=409`「该时段已被占用」 |
| TC-07 | 多设备创建 | 设备 1、2 存在 | `deviceIds=[1,2]` | `code=200`，`deviceIds=[1,2]` |

## 2. 预约状态机流转

| 编号 | 标题 | 前置条件 | 操作步骤 | 预期结果 |
|---|---|---|---|---|
| TC-08 | 确认待确认预约 | 存在 orderStatus=1 的单 | `PUT /api/v1/orders/{orderId}/confirm` | `orderStatus=2`，生成「预约已确认」消息 |
| TC-09 | 重复确认被拦截 | 单已 2 | 再次 confirm | `code=409`「当前状态不允许确认」 |
| TC-10 | 取消待确认预约 | 存在 1 的单 | `PUT /api/v1/orders/{orderId}/cancel` | `orderStatus=3` |
| TC-11 | 取消已确认预约触发释放占用 | 单已 2 | cancel | `orderStatus=3`，执行 `release_occupancy` hook |
| TC-12 | 终态不可再操作 | 单已 3 | confirm / cancel | 均 `code=409` |

## 3. 消息通知

| 编号 | 标题 | 前置条件 | 操作步骤 | 预期结果 |
|---|---|---|---|---|
| TC-13 | 消息列表（分页） | 有消息 | `GET /api/v1/messages?skip=0&limit=20` | 返回当前用户消息，按 createTime 倒序 |
| TC-14 | 未读数 | 有未读消息 | `GET /api/v1/messages/unread` | `data.count` 等于未读数 |
| TC-15 | 单条已读 | 有未读消息 | `PUT /api/v1/messages/{messageId}/read` | `isRead=true`，未读数 -1 |
| TC-16 | 全部已读 | 有未读消息 | `PUT /api/v1/messages/read-all` | 未读数归零 |
| TC-17 | 越权读他人消息 | 消息 receiverId ≠ 1 | 用 user_id=1 读该消息 | `code=404` |

## 4. 扫描（日程提醒 / 冲突预警）

| 编号 | 标题 | 前置条件 | 操作步骤 | 预期结果 |
|---|---|---|---|---|
| TC-18 | 日程提醒扫描 | 有已确认单且 1h 内开始 | `POST /api/v1/messages/remind?remind_hours=1` | `data.reminders≥1`，生成「日程提醒」消息 |
| TC-19 | 冲突预警扫描 | 库中存在同时段重叠未完成单 | `GET /api/v1/conflicts/scan` | 返回 `[{conflictType, orderIds, suggestion}]` |

## 5. WebSocket 推送

| 编号 | 标题 | 前置条件 | 操作步骤 | 预期结果 |
|---|---|---|---|---|
| TC-20 | 实时收到确认消息 | 客户端已连 `/ws/notify?user_id=1` | 调 confirm 接口 | 连接实时收到「预约已确认」推送 |
| TC-21 | 用户离线不丢消息 | 用户未连 WS | 触发消息 | 推送跳过，消息仍落库，列表可查 |
| TC-22 | 断线重连 | 客户端断网后恢复 | 观察 `ws.js` | 自动重连，未读不丢 |

## 6. Agent 联动

| 编号 | 标题 | 前置条件 | 操作步骤 | 预期结果 |
|---|---|---|---|---|
| TC-23 | 文本调度返回方案 | 后端已启动 | `POST /api/v1/agent/schedule`，body `{text}` | 返回 `plan/backupPlan/trace/needConfirm=true` |
| TC-24 | 空需求拦截 | 同上 | `text=""` | `code=422` |
| TC-25 | 方案确认落库 | 已 schedule 拿到 plan | 前端调 `POST /api/v1/orders/create`（带 plan 字段） | `code=200`，`orderStatus=1` |
| TC-26 | agentRequest/agentTrace 落库 | 同上 | 查订单详情 | `agentRequest` 为原始需求，`agentTrace` 为 JSON 数组 |
| TC-27 | 语音转写占位 | 上传音频 | `POST /api/v1/agent/transcribe` | 返回占位 `data.text` |
| TC-28 | 图像识别占位 | 上传图片 | `POST /api/v1/agent/recognize` | 返回占位 `data.text` |

## 7. 端到端闭环

| 编号 | 标题 | 操作步骤 | 预期结果 |
|---|---|---|---|
| TC-29 | 手动闭环 | ① 选场地/设备/时段提交 → ② 列表出现新单（待确认）→ ③ 确认 → ④ 取消 → ⑤ 收到消息+未读角标 | 全链路无报错，状态与消息正确 |
| TC-30 | Agent 闭环 | ① 提交需求 → ② 看思考过程 → ③ 确认方案 → ④ 预约列表出现新单 → ⑤ 详情页看思考链路 | 全链路无报错，溯源完整 |

---

## 附加：本地冒烟结果

后端冒烟断言覆盖：创建/冲突(409)/时间格式(422)/场地不存在(404)/确认/重复确认(409)/取消/终态拦截(409)/列表/资源(camelCase)/未读数/消息列表/Agent 调度(plan+backupPlan+trace)/Agent 落库 trace/冲突扫描/提醒扫描/空需求拦截，全部通过。

| 项 | 值 | 状态 |
| --- | --- | --- |
| 核对日期 | 2026-09-27（2026-09-24 首核） | ✅ 已核对 |
| Python 版本 | 3.11.9 | ✅ 已核对 |
| conda 环境 | `smart_dev`（`F:\conda_envs\envs_dirs\smart_dev`） | ✅ 已核对 |
| 依赖安装方式 | `pip install -r requirements.txt`（版本全量 `==` 锁定） | ✅ 已执行 |
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

---

## 附二：自动化用例与覆盖率口径（§8.7 / §10.2）

### 运行

```bash
cd weix/backend
python -m pytest -q                                    # 121 个用例
python -m pytest --cov=app --cov-report=term-missing   # 覆盖率
```

> **用项目 venv（Python 3.11）跑**：`asyncmy` 无 cp313 轮子，在 3.13 上装不上。
> 见 `weix/README.md` 的环境说明。

用例全程**不触碰云库**：`tests/conftest.py` 在导入 `app` 之前把 `DATABASE_URL` 覆盖为
临时 SQLite（环境变量优先于 `.env`），由
`tests/test_config_alignment.py::test_tests_run_on_isolated_database` 守住这条约束。

用例 ↔ 矩阵对应：TC-01~TC-12 → `test_orders.py`，TC-13~TC-19 → `test_messages.py`，
TC-20~TC-22 → `test_websocket.py`（连接管理器）+ `test_ws_lifespan.py`（真实 ASGI 连接），
TC-23~TC-28 → `test_agent.py` + `test_agent_client.py`；
另有 `test_edge_cases.py`（旧兼容路径 / 归属校验 / 状态机不变量 / 异常兜底 / 身份兜底）与
`test_config_alignment.py`（与公用 backend 的参数对齐回归）。
TC-29 / TC-30 为 §7.2 的手工验收项。

**归属校验（越权）用例**：`test_edge_cases.py` 的「归属校验：他人订单一律 404」一节，
覆盖订单详情 / 确认 / 取消三条。这批用例已按"摘掉校验必须变红"验证过——
把 `_get_owned_order` 的 `order.user_id != user_id` 去掉后，其中 4 条立即失败。

当前**全项目 99%**（714 语句，1 未覆盖）。唯一未覆盖行是
`app/core/database.py:87`（`patch_asyncmy_ping()` 调用点）：它只在
`DATABASE_URL` 以 `mysql+asyncmy` 开头时执行，而用例全程跑临时 SQLite，该分支
必然进不去。补丁函数体本身由 `test_asyncmy_ping_compat.py` 直调覆盖，不是漏测。

### `concurrency = thread,greenlet` 不能删

`backend/.coveragerc` 里的这行是**必需项，不是可选优化**。两个词缺一不可：

**`greenlet`** —— SQLAlchemy 的异步引擎通过 greenlet 切执行栈在同步 ORM 与 asyncio 之间
桥接，而覆盖率的追踪状态不跨 greenlet 存活。后果是：**每个协程恰好从第一个 `await db.*`
开始丢行**，该行之前的记得到，之后的全丢。

| 配置 | `app/api/orders.py` | 说明 |
|---|---|---|
| 默认 | 44% | 假的。缺的正是 `await` 之后的行 |
| `concurrency = greenlet` | 100% | 真实值 |

**`thread`** —— 只写 `greenlet` 会丢掉线程追踪。`TestClient` 与 uvicorn 都在自己的线程里
跑事件循环，漏掉 `thread` 会让 `main.py` 的 lifespan 与 `/ws/notify` 假性未覆盖
（实测 69% vs 100%）。

判定依据（不是推测）：用裸 `sys.settrace` 单独跑一次请求，确认 `create_order` 的
48/50/54…86、`_order_out` 的 30–41 全部真实触发追踪事件（当时的行号，函数名为路由层
私有函数 `_create_order`）——行**确实执行了**，只是没被 coverage 记录。无 `await` 的函数
（`get_current_user`、`_order_out`）在任何配置下都是 100%，也印证了是 greenlet 切栈
而非测试缺失。

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

## 三、用例清单（核心调度 Agent 模块）

编号规则：`AGENT-<类型>-<序号>`。全部用例须在**断网**状态下可跑通（10.2：真实 API 不进常规用例）。

### 3.1 单元与契约（AGENT-U）

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

### 3.3 异常与降级（AGENT-E）

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

### 3.4 接口（AGENT-I）

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

### 3.5 并发与事务（AGENT-C）

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

## 四、覆盖率要求

- `app/agent/` 覆盖率不低于 **80%**
- 阈值写入 `pytest.ini` 的 `--cov-fail-under`，由 CI 卡住
- 覆盖率是结果不是目标——为凑数字写空用例视为未完成

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

## 五、测试库规范（主文档 6.8）

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
