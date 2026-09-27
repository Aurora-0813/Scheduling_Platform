# API 接口文档 —— 移动端预约与通知模块

> 模块责任人：蔡玉礼。统一遵守《开发流程》第五章接口规范。

## 通用规范

- 所有接口统一前缀 `/api/v1/`。
- 请求头：`Content-Type: application/json`；认证头：`Authorization: Bearer {token}`（演示阶段用 `X-User-Id: 1` 模拟）。
- 身份一律从 JWT（演示为 `X-User-Id`）解析，请求体/FormData 禁止携带 `userId` 等身份标识（§5.1）。
- 时间格式统一：`YYYY-MM-DD HH:mm:ss`。
- 布尔值统一：`true` / `false`（数据库 `is_read` 为 INT，接口层转为布尔）。
- 统一响应体：

```json
{ "code": 200, "message": "操作成功", "data": {} }
```

- 成功 `code=200`；错误 `code` 为对应 HTTP 状态码（400/404/409/422/500），`data=null`。

---

## 1. 预约订单

### 1.1 创建预约（契约）

`POST /api/v1/orders/create`

请求参数（JSON）：

| 字段         | 类型         | 必填 | 说明                     |
| ------------ | ------------ | ---- | ------------------------ |
| spaceId      | int          | 是   | 空间ID                   |
| deviceIds    | int[]        | 否   | 设备ID列表               |
| startTime    | string       | 是   | 开始时间 `YYYY-MM-DD HH:mm:ss` |
| endTime      | string       | 是   | 结束时间                 |
| agentRequest | string       | 否   | 用户原始需求（Agent 创建时填入） |
| agentTrace   | array        | 否   | AI 思考过程追踪          |

> 预约人 `userId` 从 JWT（演示 `X-User-Id`）解析，不再作为请求体字段（§5.1）。

响应 `data`：

```json
{
  "orderId": 12, "userId": 1, "spaceId": 1, "deviceIds": [1],
  "startTime": "2026-09-25 09:00:00", "endTime": "2026-09-25 10:00:00",
  "orderStatus": 1, "agentRequest": "", "agentTrace": [],
  "createTime": "2026-09-24 10:00:00", "updateTime": "2026-09-24 10:00:00"
}
```

错误：`404` 场地/设备不存在；`409` 该时段已被占用；`422` 时间格式非法或开始晚于结束。

### 1.2 我的预约列表（契约）

`GET /api/v1/orders/my?status=1`

- `status` 可选：1待确认 / 2已确认 / 3已取消 / 4已完成。
- 当前用户从 JWT（`X-User-Id`）解析；响应 `data` 为订单数组，按创建时间倒序。

> 兼容历史客户端保留 `GET /api/v1/orders/user/{userId}`，新代码请使用 `/orders/my`。
> **旧路径的身份同样只认 JWT**：路径参数与当前身份不符时返回 `404`（与详情/确认/取消同口径）。

### 1.3 订单详情（扩展）

`GET /api/v1/orders/{orderId}`

- 需身份头。错误：`404` 订单不存在**或不属于当前用户**。

### 1.4 确认预约（扩展，状态机 1→2）

`PUT /api/v1/orders/{orderId}/confirm`

- 触发「预约已确认」通知。错误：`404` 订单不存在**或不属于当前用户**；`409` 当前状态不允许确认。

### 1.5 取消预约（契约）

`PUT /api/v1/orders/{orderId}/cancel`

- 触发「预约已取消」通知；取消「已确认」单时释放占用。错误：`404` 订单不存在**或不属于当前用户**；`409` 当前状态不允许取消。

> **归属校验（§5.1）**：详情 / 确认 / 取消三条**只对本人订单生效**。认证头只证明「你是谁」，
> 证明不了「这单是不是你的」——`orderId` 是自增的，不做归属校验等于拿它当密码用。
> 越权与不存在**返回完全相同的 `404` 响应体**，不泄露订单是否存在（与 §3.3 消息越权口径一致）。
>
> `GET /api/v1/orders/user/{userId}`（历史兼容路径）**已收紧**（2026-09-27）：路径参数与
> 当前身份不符时返回 `404`，与上面三条同口径。它原先**连 `get_current_user` 都没有**，
> 是**完全匿名**的 —— 任何人 `GET /orders/user/1` 就能读到 1 号用户的全部订单（含
> `agentRequest` 原始需求文本），比「少一层归属校验」更严重：连「你是谁」都没问。
> 该路径不在 `§5.3` 契约清单里（清单只有 `/orders/my`），本模块内也没有客户端再走它
> （小程序 `api/reserve.js` 已改用 `/orders/my`），因此收紧**唯一挡掉的用法就是跨用户读取**，
> 不需要等集成组确认外部依赖。

---

## 2. 资源查询

### 2.1 场地列表（契约）

`GET /api/v1/resources/spaces`

```json
{ "code": 200, "message": "操作成功", "data": [
  { "spaceId": 1, "spaceName": "会议室A", "spaceType": 1, "capacity": 10, "location": "3F",
    "budget": 0.0, "openStartTime": "08:00:00", "openEndTime": "22:00:00", "status": 1 }
] }
```

### 2.2 设备列表（契约）

`GET /api/v1/resources/devices`

```json
{ "code": 200, "message": "操作成功", "data": [
  { "deviceId": 1, "deviceName": "投影仪", "deviceType": "投影", "deviceStatus": 1,
    "totalCount": 1, "availableCount": 1 }
] }
```

---

## 3. 消息通知

### 3.1 未读数（契约）

`GET /api/v1/messages/unread`

```json
{ "code": 200, "message": "操作成功", "data": { "count": 2 } }
```

### 3.2 消息列表（扩展）

`GET /api/v1/messages?skip=0&limit=20`

```json
{ "code": 200, "message": "操作成功", "data": [
  { "messageId": 5, "receiverId": 1, "notifyType": 1, "orderId": 12,
    "title": "预约已确认", "content": "您的预约 #12 已确认", "isRead": false,
    "createTime": "2026-09-24 10:05:00" }
] }
```

### 3.3 单条已读（扩展）

`PUT /api/v1/messages/{messageId}/read`

### 3.4 全部已读（扩展）

`PUT /api/v1/messages/read-all`

### 3.5 日程提醒扫描（扩展）

`POST /api/v1/messages/remind?remind_hours=1`

- 扫描 1 小时内即将开始的「已确认」预约，生成日程提醒并推送。响应 `data: { "reminders": n }`。

---

## 4. 核心调度 Agent

### 4.1 提交需求（契约）

`POST /api/v1/agent/schedule`

请求参数：`{ "text": "帮我预约明天上午的会议室", "imageContext": {} }`（`userId` 从 JWT 解析）

响应 `data`：

```json
{
  "plan": { "spaceId": 1, "deviceIds": [1], "startTime": "2026-09-25 09:00:00",
            "endTime": "2026-09-25 10:00:00", "title": "主方案 · 会议室A", "reason": "场地空闲，满足需求" },
  "backupPlan": { "...": "备方案" },
  "trace": ["解析需求：...", "查询可用场地与设备资源", "检测时段冲突，进行方案权衡", "生成主方案与备方案"],
  "needConfirm": true
}
```

- 确认方案 = 前端取 `plan` 直接调 `POST /api/v1/orders/create`，并携带 `agentRequest` + `agentTrace` 落库。
- 未配置 `AGENT_URL` 时走内置 mock 调度器（占用感知，自动避让已占用时段）。

### 4.2 语音转写（占位）

`POST /api/v1/agent/transcribe`（FormData `file`）→ `data: { "text": "..." }`

### 4.3 图像识别（占位）

`POST /api/v1/agent/recognize`（FormData `file`）→ `data: { "text": "..." }`

---

## 5. AI 冲突预警（联调对接）

### 5.1 冲突扫描（契约，模块7）

`GET /api/v1/conflicts/scan`

```json
{ "code": 200, "message": "操作成功", "data": [
  { "conflictType": "时段重叠", "orderIds": [1, 2], "suggestion": "建议将预约 #2 调整至其他时段或更换场地" }
] }
```

---

## 6. WebSocket 实时推送

`ws://host/ws/notify?user_id=1`

- 服务端在确认/取消/日程提醒等动作后，向目标用户推送消息 JSON：

```json
{ "messageId": 5, "receiverId": 1, "notifyType": 1, "orderId": 12,
  "title": "预约已确认", "content": "...", "isRead": false, "createTime": "..." }
```

---

## 7. 服务层契约（核心调度 Agent 直接调用 · **已冻结 2026-09-27**）

> 交付对象：核心调度 Agent 模块（模块 4）的 `lock_resources` Tool。
> 冻结含义：下面五项**均不得更改**——函数名与模块路径、参数名与顺序、keyword-only
> 限定、"签名里没有 `db`"、返回结构。改动属于破坏性变更，必须先通知本模块。
> 另有 `update_agent_trace`（§7.6）：那是**补缺**，不是对这五项的改动。

`§4.3` / `§7.4` / `§9.3` 三条规范要求 Agent 只能通过 Tool 调用 `services/` 层异步函数、
Tool 内禁止使用 `AsyncSession`，因此本模块提供两个不依赖 HTTP、不依赖调用方会话的入口：

```python
from app.services.order_service import create_order         # 权威路径
from app.services import create_order                       # 等价别名，同一个函数对象
from app.services.order_service import update_agent_trace    # 补写链路，见 §7.6
```

```python
async def create_order(
    *,
    user_id: int,                 # 由调用方从 JWT 解出后传入（§5.1），不得从请求体取
    space_id: int,
    start_time: str,              # "YYYY-MM-DD HH:mm:ss"
    end_time: str,
    device_ids: list[int] | None = None,
    agent_request: str | None = None,   # 超 1024 按 §6.3 表6 列宽截断
    agent_trace: list | None = None,
    order_status: int = 1,        # 1待确认（默认）/ 2已确认，其余取值一律拒绝
) -> dict:                        # {ok, orderId, reason, conflictType, conflictDetail}
```

### 7.1 为什么签名里没有 `db`

Tool 拿不到 `AsyncSession`（`§7.4` 禁止），让它传 `db` 就等于逼它直连数据库。
会话与**事务边界**都由 `create_order` 自管 —— 这正是 `§5.5` 六步原子性的落点：
调用方**无法**在六步之间插入一次 commit，也就无法把 `FOR UPDATE` 的锁提前放掉。
所以「校验」与「落单」在物理上不可能被拆成两次调用。

### 7.2 返回值

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ok` | bool | 是否创建成功 |
| `orderId` | int \| null | 成功时为新订单 ID |
| `reason` | string | 面向用户的中文原因，可直接写入 trace / 前端提示 |
| `conflictType` | string \| null | `invalid_param` / `not_found` / `time_conflict` / `device_conflict` |
| `conflictDetail` | object \| null | 结构化冲突详情，供屏 3 展示 |

`conflictDetail` 形状：

```jsonc
{ "target": "space" | "user" | "device", ...对应 ID }                       // not_found
{ "conflicts": [ { "orderId": 3, "startTime": "...", "endTime": "..." } ] }  // time_conflict
{ "conflicts": [ { "orderId": 3, "deviceIds": [1], "startTime": "...", "endTime": "..." } ] }
{ "conflicts": [ { "deviceId": 1, "reason": "status" | "exhausted" } ] }      // device_conflict
```

入参容忍模型输出：`"space_id": "101"` 这类数字字符串会被转成整数（`§9.3` 要求对模型输出做
业务边界校验，能转就转、转不了才报 `invalid_param`）。但 `device_ids` 必须是数组——
传字符串 `"1"` 会被当作逐字符迭代，静默变成 `[1]` 这种事必须挡住。

**业务性失败一律不抛异常**（`§5.5`「ROLLBACK 并返回友好提示」）：`ok=false` + 结构化原因。
只有基础设施故障（连不上库等）才抛出，由统一异常处理器兜成 500 —— 那是故障、不是
「方案不可行」，伪装成 `ok=false` 会让 Agent 把连不上库讲成业务建议。

### 7.3 Tool 与服务的参数对应

| Tool（`§5.3` 模块4） | 服务层 |
| --- | --- |
| `lock_resources(space_id, device_ids, start_time, end_time)` | `create_order(user_id=…, space_id=…, device_ids=…, start_time=…, end_time=…)` |

差一个 `user_id`：身份一律从 JWT 解析（`§5.1`），由 Agent 运行上下文补入。
Agent 侧若漏传，服务层会明确返回 `invalid_param`「缺少 user_id」而不是落 NULL 或抛异常。

### 7.4 两条已知边界（**不要在冻结口径之外依赖**）

1. **`available_count` 只读不写。** `§5.5` 六步里既没有扣减、也没有取消时回补，
   `§6.3` 表5 却有该字段。单方面扣会造出第二份真值。当前只做 `available_count > 0`
   的校验；"扣减还是派生"的口径已作为文档缺口上报集成组。
2. **设备时段冲突是尽力而为。** `§6.3` 没有「设备占用」表，设备的时间维度占用只存在
   `reserve_order.device_ids`（JSON 列），只能捞重叠时段订单后按 Python 求交集，
   且 `§6.6` 的 `idx_*` 云库尚未建 —— 正确性可用，**不做性能承诺**。正式口径待集成组给出。

### 7.5 自动化护栏

`backend/tests/module3/test_order_service.py` 把这套契约钉住了，改签名会直接红：

- 参数名、顺序、keyword-only 限定、`db` 不得进签名 —— 逐项断言
- 成功与失败返回**字段集完全相同**
- `time_conflict` / `device_conflict` / `not_found` / `invalid_param` 四条分支各有用例
- §5.5 第 2 步的 `FOR UPDATE` 在 MySQL 方言下必须出现（SQLite 方言会编译掉它，
  单测跑在 SQLite 上，所以只能靠编译比对来防止锁被静默删掉）
- `update_agent_trace`（§7.6）的签名同规格锁死，另有「越权与不存在同为 `not_found`」、
  「重复补写同一份 trace 仍返回 `ok`」两条行为护栏

### 7.6 `update_agent_trace` —— 补缺，不是改冻结口径

Agent 的思考链路是**跑完之后**才有的，落单那一刻还拿不到。所以链路只能分两步写：
`create_order` 先落 `agent_trace=None`（语义是「尚未生成」，**不是**「生成了一半」——
残缺 trace 在库里与完整 trace 无法区分，前端会当成完整链路渲染，而 TC-26 / TC-30
验收的恰恰是「溯源完整」），Agent 跑完再补一次 UPDATE。

```python
from app.services.order_service import update_agent_trace

async def update_agent_trace(
    *,
    order_id: int,          # 要补写的订单
    user_id: int,           # 归属校验；由调用方从 JWT 解出后传入（§5.1）
    agent_trace: list,      # TraceStep 对象数组，**整体覆盖**该列
) -> dict:                  # {ok, orderId, reason, conflictType, conflictDetail}
```

与 `create_order` 同规格：keyword-only、签名不含 `db`、业务失败返回 `ok=false` 不抛异常，
且**返回字段集完全相同** —— 调用方一处取值逻辑两处通用。

三条口径，改桩时别绕开：

| 情形 | 返回 |
| --- | --- |
| 订单不存在，**或**不属于传入的 `user_id` | `ok=false` / `not_found` / `reason="预约不存在"` |
| `agent_trace` 为空数组，或不是数组 | `ok=false` / `invalid_param` |
| 同一份 `agent_trace` 重复补写 | `ok=true`（可重复调用） |

前两条的理由：

1. **越权与不存在必须同一个说法。** 区分了就等于承认「这单存在，只是不是你的」，
   可据此枚举全库订单。与 `GET /orders/{orderId}`、`PUT /orders/{orderId}/cancel`
   的 `_get_owned_order`、以及 `messages.py::read_message` 是同一口径。
2. **空数组拒绝是刻意的。** 空链路在库里与 `NULL`（尚未生成）区分不开，写进去只会让
   前端把「没跑出东西」渲染成一条空链路。没有内容可补写时**不要调用本函数**。
   注意 `create_order` 允许传空 list（那里 `None` 才是常态），两处宽严不同是有意为之。

**`user_id` 必须进签名**，不是可选参数：只凭 `order_id` 就能改任意订单的 `agent_trace`，
等于把它变成可写公共字段。

实现上刻意用「先 `SELECT … FOR UPDATE` 再赋值」，而不是一条 `UPDATE`：MySQL 的
`affected_rows` 默认只数**真正发生变化**的行，同一份 trace 补写两次时第二条会返回 0 行，
被误判成 `not_found`。分成两步才能把「不存在 / 非本人」与「值没变」分开。
