# API 接口文档

> 各模块负责人在本文件对应小节补充，接口变更时同步更新（《项目文档.md》11.1 / 11.2）。
> 通用规范见主文档 5.1（通用约定）、5.2（统一响应体）；传输字段一律 camelCase（6.2）。

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
- 成功 `code=200`。
- **失败时 `code` 是业务错误码**（见 `app/core/error_codes.py`），**HTTP 状态码另算**：
  例如参数校验失败是 HTTP 400 + `code=40001`，账号禁用是 HTTP 403 + `code=40108`。
  `data` 为 `null` 或补充信息。前端只需判断 `code === 200`。
- **降级路径同样返回 HTTP 200 且保持本结构**，不抛 500。
- 各模块小节里写的「错误：404 / 409 / 422」指的是 **HTTP 状态码**，对应的业务错误码见该模块错误码表。

---

## 1. 预约订单（模块 3）

> 模块责任人：蔡玉礼。统一遵守《开发流程》第五章接口规范。

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

## 2. 资源查询（模块 3）

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

## 3. 消息通知（模块 3）

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

## 4. 核心调度 Agent（模块 4）

负责人：徐川　｜　状态：**已定稿（阶段 6，实现与文档一致）**

字段级契约自阶段 2 冻结后**未再变更**；本节在阶段 6 补齐的是实现侧的确定项：
503 的触发条件、401 与参数校验失败也走统一响应体、以及 mock 端点的注册条件。

> **两种失败的状态码不同（2026-09-28 裁定，非字段级）**：认证失败保留 **HTTP 401**，
> 参数校验失败是 **HTTP 400 + `code=40001`**。两者都走统一响应体结构，区别在状态行与业务码。
> 理由：401 是「这一整类请求都不该发出去」，前端拦截器靠状态行跳登录；
> 参数校验失败是「请求到了业务层、这单做不了」，前端留在当前页改输入。
> 详见 `docs/spec/done/stage-06-completion.md` 偏离 #4。
已按本契约实现并实测：`backend/app/api/v1/agent.py`、`docs/mock/agent_schedule.json`。

> **参数校验口径变更（2026-09-28 二次更正，非字段级）**：本模块原先规定 `text` 为空或超长
> 返回 HTTP 422；合并前一度改成 **HTTP 200 + `code=400`**（模块 4 自建的异常处理器）；
> **rebase 到 `origin/main`（`9f30d3a`）后，`core/response.py` 的
> `RequestValidationError` 处理器是正式版的，口径为 HTTP 400 + `code=40001`
> （`ErrorCode.PARAM_INVALID`）**，与模块 2 的 `tests/test_image_api.py` 一致。
> 文档按第三种口径改写。字段本身、约束范围、以及「不空跑模型」的行为前后均未变。
> 两次偏离都已记入 `docs/spec/done/stage-02-completion.md`。

### 4.1 提交需求（契约）

`POST /api/v1/agent/schedule`

根据自然语言需求生成场地与设备调度方案。

**认证**：必须携带 `Authorization: Bearer <JWT>`。用户身份从 JWT 解析。

**请求体**

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `text` | string | 是 | 长度 1~1024 | 用户原始自然语言需求 |
| `imageContext` | object | 否 | 默认 `{}` | 模块 2 传入的图像解析上下文 |

**注意：请求体没有 `userId` 字段。** 身份一律从 JWT 解析（主文档 5.1、9.1）；请求体若夹带 `userId` 会被忽略。若从请求体取用户 ID，任何人都能替别人预约。

`text` 为空字符串时被参数校验挡下，返回 **HTTP 400 + `code=40001`**（见下方错误码表），
不会让 Agent 空跑一次大模型。

**请求示例**

```json
{
  "text": "下周三下午两点，40 人的产品评审会，预算 800 元，需要投影",
  "imageContext": {}
}
```

**响应 data 结构**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `plan` | object \| null | 主方案；无可行方案时为 `null` |
| `backupPlan` | object \| null | 备选方案 |
| `orderId` | int \| null | 本轮成功锁定的预约单 ID，取自最后一次成功的 `lock_resources`；未落库时为 `null` |
| `trace` | array | 思考链，前端按 `timestamp` 时间轴回放 |
| `needConfirm` | boolean | 是否需要人工确认 |

`orderId` 是**确认流程的入口**：`needConfirm=true` 时前端拿它调
`PUT /api/v1/orders/{orderId}/confirm` 完成 `status` 1→2 的流转。
⚠️ **它的取值与 `plan` 是否为空无关**——模型可能已锁单再在交方案前超时降级，
此时 `plan` 为 `null` 但 `orderId` 仍有值。判断「有没有方案」看 `plan`，
判断「有没有建单」看 `orderId`，不要用其中一个去推另一个。
为 `null` 的含义是**确实没建单**，不是「没有方案」。

**`plan` / `backupPlan` 结构**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `spaceId` | int | 场地 ID |
| `spaceName` | string | 场地名称 |
| `deviceIds` | int[] | 设备 ID 列表 |
| `startTime` | string | 开始时间 |
| `endTime` | string | 结束时间 |
| `reason` | string | 方案说明，含降级/替代理由 |

**`trace` 元素结构**（前端按此逐字段渲染，字段不可中途变更）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `step` | int | 是 | 步骤序号，从 1 递增 |
| `result` | string | 是 | 本步骤的中文结论 |
| `timestamp` | string | 是 | 该步骤发生时刻，`YYYY-MM-DD HH:mm:ss` |
| `thought` | string \| null | 否 | Thought：模型本步的推理文本 |
| `action` | string \| null | 否 | Action：被调用的 Tool 名 |
| `actionInput` | object \| null | 否 | Action 的入参 |
| `observation` | object \| null | 否 | Observation：Tool 的返回 |

各步 `timestamp` **互不相同且递增**，可直接用于时间轴回放。

**响应示例（正常）**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "plan": {
      "spaceId": 3,
      "spaceName": "A栋3楼展厅",
      "deviceIds": [1],
      "startTime": "2026-09-30 14:00:00",
      "endTime": "2026-09-30 16:00:00",
      "reason": "预算内保留场地，投影由双台降级为单台"
    },
    "backupPlan": null,
    "orderId": 101,
    "trace": [
      {
        "step": 1,
        "result": "解析需求：40 人、预算 800 元、需要投影",
        "timestamp": "2026-09-30 13:59:12",
        "thought": "先确认人数与预算约束",
        "action": null,
        "actionInput": null,
        "observation": null
      },
      {
        "step": 2,
        "result": "查询可用场地",
        "timestamp": "2026-09-30 13:59:19",
        "thought": "按 40 人容量与展厅类型检索",
        "action": "query_spaces",
        "actionInput": { "capacity": 40, "space_type": 2, "start_time": "2026-09-30 14:00:00", "end_time": "2026-09-30 16:00:00" },
        "observation": { "spaces": [] }
      }
    ],
    "needConfirm": true
  }
}
```

**降级响应（契约内，HTTP 仍为 200）**

三种情形 `plan` 均为 `null`、`needConfirm` 均为 `true`，区别只在 `message`。
**`orderId` 不参与这三条判定**——若模型已锁单再降级，它仍是非空值（见上方 `orderId` 说明）：

| 情形 | `message` 内容 |
| --- | --- |
| 无可行方案 | 人工可读的原因 + 修改建议（建议不少于 3 条） |
| 需求自相矛盾 | 指出矛盾点 + 修改建议，不编造方案 |
| 大模型输出格式错乱 | 模型返回的自然语言原文 |

**超时降级**：模型调用超时时，已收集到的 `trace` 一并返回，前端可展示"思考到哪一步中断了"。超时时间由服务端 `.env` 的 `AGENT_TIMEOUT` 配置。

**错误码**

| code | HTTP | 场景 |
| --- | --- | --- |
| 200 | 200 | 正常，或上述任一降级路径 |
| 40101 | 401 | 缺少 `Authorization` 头 |
| 40102 / 40103 | 401 | 令牌签名无效 / 已过期 |
| 40104 | 401 | 拿 refreshToken 调业务接口 |
| 40001 | 400 | `text` 为空或超长（参数校验的统一口径，见本节开头说明） |
| 41003 | 503 | **服务端**未配置大模型（`.env` 缺 `LLM_MODEL_NAME`/`LLM_API_KEY`/`LLM_BASE_URL`） |

**以上非 200 的响应体与成功路径结构完全相同**（同为 `{code, message, data}`），
前端只需要一套解析逻辑。这是阶段 6 的完成判定之一：
异常不得穿透到 FastAPI 的默认错误处理（那会返回 `{"detail": ...}`）。

503 与三条降级路径的**区别要留意**：降级是「模型跑了但没给出方案」，HTTP 200；
503 是「模型根本没跑起来」，属服务端配置问题，**必须显式暴露**——
伪装成 200 + `plan=null` 会让运维以为是模型不行，实际是 key 没配。

**禁止事项**

- 不存在 `/api/v1/tools/*` 路由：Tool 是给模型调用的内部函数，不对外暴露（主文档 5.3、9.3）
- 请求体不接受 `userId`

### 4.2 Mock：`POST /api/v1/mock/agent/schedule`

**仅 `DEBUG=true` 时注册**；演示/生产环境（`DEBUG=false`）下该路径不存在，返回 404。

> ✅ **2026-09-28 合并后更正（含当日闭环）**：本节原写 `GET`。rebase 到 `origin/main`
> （`9f30d3a`）时 `api/v1/mock.py` / `mock_data.py` 取的是**集成组扩展过的正式版**
> （该文件同时承载模块 5/6/7/8/10 的 mock 路由，分支版本只有模块 4 一段，不能覆盖），
> 端点为 **`POST`**，且当时的数据是代码里另写的一份 **4 步 / 跨 2 秒**常量，
> 与 `docs/mock/agent_schedule.json`（7 步 / 39 秒）**各说各话**。
> **同日 `25b3ee3` 已闭环**：`mock_data.AGENT_SCHEDULE` 改为**读该 json 的 `data` 段**，
> json 成为唯一真源，响应体随之回到 **7 步**。

**数据源：`docs/mock/agent_schedule.json`（唯一真源）。**
响应体的 `data` 段**逐字段取自该文件的 `data` 段**——改思考链数据只改这个 json，代码侧不用动。
路径解析兼容两种检出布局，取先命中的：仓库布局 `<repo>/docs/mock/…`（常态，优先）→
后端独立布局 `<backend>/docs/mock/…`。**两处都读不到时打 ERROR 日志并返回空 `data`**
（不抛异常：演示数据文件缺失不该把应用启动带崩），由
`tests/api/test_agent_schedule_mock.py` 在测试阶段暴露。

**请求参数**：Query `degraded=true` → 响应加 `X-Agent-Degraded: 1` 头
（模块 10 的埋点据此统计降级数，见 `app/middlewares/agent_metrics.py`）。

该 json 同时是前端屏 3 渲染、40 秒回放、13.1 应急预案三处共用的那一份；
数据变更由 `tests/api/test_agent_schedule_mock.py`（7 例）与
`tests/api/test_mock_routes.py`（响应体 camelCase 检查）双重把关。

### 4.3 语音转写（占位，**当前未注册**）

`POST /api/v1/agent/transcribe`（FormData `file`）→ `data: { "text": "..." }`

> ⚠️ 该端点在模块 3 的 `app/api/agent.py` 里，**本次合并未注册该 router**（它的
> `/agent/schedule` 与模块 4 的实现路径重复）。真实能力由 `/api/v1/voice/asr` 提供，
> 请使用后者。

### 4.4 图像识别（占位，**当前未注册**）

`POST /api/v1/agent/recognize`（FormData `file`）→ `data: { "text": "..." }`

> ⚠️ 同上。真实能力由 `/api/v1/image/analyze` 提供。

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

---

## 8. 监控（模块 10）

### 8.1 Agent 调用监控（契约）

`GET /api/v1/monitor/agent`

负责人：徐川（模块 4 视角）／集成组（实现）　｜　状态：**已随 `origin/main` 落地（2026-09-28）**

Agent 调用埋点（主线二与模块 10 展示用）。

> ⚠️ **2026-09-28 合并后整节改写**：本节原先记的是模块 4 阶段 6 的自建实现（进程内计数、
> 必须鉴权、`avgLatency` 单位为毫秒、成功率按 `plan` 非空判定）。rebase 到
> `origin/main`（`9f30d3a`）时监控整条链路取的是**集成组正式版**，四处口径都不同，**以本节为准**。
> 原文不再保留——它描述的实现已不存在，留着只会误导前端。
> 实现位置：`app/middlewares/agent_metrics.py`（自动收集）+ `app/core/metrics.py`（存储）
> + `app/services/monitor_service.py`（单位换算）+ `app/schemas/monitor.py`（契约）。

**认证：不需要。** 本端点**不鉴权**（`app/api/v1/monitor.py` 的模块 docstring 有完整理由）：
它是给前端监控面板与答辩演示用的只读统计，内容不敏感，且面板常在登录态之外加载
（例如登录页的健康指示），加鉴权会让面板在未登录时整块报错。
⚠️ **代价与边界**：若将来指标加入业务维度（按用户/按接口细分），必须改为
`Depends(require_permission(...))` —— 那时的数据已能反推业务量。当前实现刻意不接受任何筛选参数。

**响应 data 结构**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `totalCalls` | int | `/api/v1/agent/*` 的 **HTTP 请求数**（按请求计，**不是** token 数） |
| `successRate` | number | 成功**百分比**，0~100，1 位小数（`96.1` 表示 96.1%） |
| `avgLatency` | number | 平均耗时，单位**秒**，1 位小数（`3.2` 表示 3.2 秒） |

> **单位务必与前端面板文案一致**：`successRate` 是 `96.1` 不是 `0.961`，
> `avgLatency` 是**秒**不是毫秒。换算只在 `monitor_service` 一层做，router 与 schema 都不二次换算。
> 无调用时返回 `0` / `0.0` / `0`，**不返回 `null`**——前端对 `successRate` 做 `toFixed(1)`，
> 拿到 `null` 会直接抛错。

> **成功率口径（与模块 4 原设计不同）**：正式版**仅按 HTTP 状态码判定**——`< 400` 记为成功。
> 大模型降级通常**仍返回 200**，因此降级**单列**为 `degradedCalls` / `degradedRate`，
> **不并入** `successRate`。模块 4 原设计是「`plan` 非空且未降级才计入成功」，
> 两者数字会不同：**以正式版为准**。

**`?detail=true`** 时额外返回 `successCalls` / `errorCalls` / `degradedCalls` /
`degradedRate` / `source`。`source` 为 `redis` 表示跨重启累计，`memory` 表示
Redis 不可用、数据仅为本进程启动至今。**这两个值不是错误码，是数据来源说明。**

**存储**：`app/core/metrics.py` 的 `MetricStore`，优先 Redis（跨重启累计、多 worker 共享），
Redis 不可用时退化为进程内计数。**模块 4 自建的 `agent_service.record_call` / `snapshot` /
`reset` 进程内计数已被本实现取代，目前无任何读端**（`record_call` 仍在 `agent.py` 里被调用，
属待清理项，见 `stage-06-completion.md` §5.1）。

**Mock 灌数**：`POST /api/v1/mock/monitor/simulate`（`DEBUG=true` 时注册）可批量写入模拟数据，
供模块 4 未完成或演示前预热面板使用。Mock 流量**不会**计入真实 Agent 调用。

**错误码**

| code | HTTP | 场景 |
| --- | --- | --- |
| 200 | 200 | 正常（含无调用时的零值）。**无 401**——本端点不鉴权 |

---

## 待补充模块

以下模块的接口由各自负责人在本文件补充：

| 模块 | 负责人 |
| --- | --- |
| 模块 1 用户认证 | |
| 模块 2 图像识别 | |
| 模块 3 预约订单 | 蔡玉礼 |
| 模块 5 资源管理 | 杨睿坤 |
| 模块 6 数据看板 | |
| 模块 7 消息通知 | 黄嵩 |
| 模块 8 小程序端 | |
| 模块 9 PC 管理端 | |
