# 测试用例文档 —— 移动端预约与通知模块

> 覆盖预约创建/校验/状态机、消息（含提醒扫描）、WebSocket 推送、Agent 联动、端到端闭环。
> 接口统一前缀 `/api/v1/`，响应体 `{code, message, data}`；演示账号为 seed 里的 `user_id=1`，
> 用例先登录换取 token 再带 `Authorization: Bearer <token>`（身份一律从 JWT 解析，§5.1）。
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
| TC-11 | 取消已确认预约即可释放占用 | 单已 2，且该时段该设备名额已用满 | cancel，再下一单同时段同设备 | `orderStatus=3`；**新单创建成功**（名额是按「用时推导」算出来的，单离开 1/2 即自动释放，无回补代码） |
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
| TC-20 | 实时收到确认消息 | 客户端已连 `/ws/notify?token=<accessToken>` | 调 confirm 接口 | 连接实时收到「预约已确认」推送 |
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

> 架构对齐后说明（§3.4 / §10.2）：
> - 后端已切换为异步架构：`asyncmy` 驱动 + `AsyncSession` + `async def` 端点，`get_db` 为 `async def`；本地自测如用 SQLite 需额外安装 `aiosqlite` 并将连接串改为 `sqlite+aiosqlite://`（仅自测，联调/正式一律云库）。
> - 身份一律从 JWT 解析，请求体不再传 `userId`（§5.1）。
> - `main.py` CORS `allow_credentials` 置 False（认证走 `Authorization` 头，不依赖 Cookie，无需凭证模式）。
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

> 2026-09-27 复核：写入路径已按 `§4.3` / `§5.5` 重构，`_create_order` 迁到
> `app/services/order_service.py::create_order`（:246），路由只剩薄壳
> （`app/api/orders.py::create_order`，:57）。同一份 `.coveragerc` 配置下重跑：
> `app/api/orders.py` 100%、`app/services/order_service.py` 100% —— 结论不变。

> 影响范围不止本模块：**任何**基于 `sqlalchemy.ext.asyncio` 的模块在 CI 里都会覆盖率虚低。
> 集成组若给公用 `backend/` 设了覆盖率门槛，需一并加这行配置。
