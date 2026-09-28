# API 接口文档

> 各模块负责人在本文件对应小节补充，接口变更时同步更新（《项目文档.md》11.1 / 11.2）。
> 通用规范见主文档 5.1（通用约定）、5.2（统一响应体）；传输字段一律 camelCase（6.2）。

## 统一响应体

所有接口返回：

```json
{ "code": 200, "message": "操作成功", "data": { } }
```

失败时 `code` 为业务错误码，`message` 为可读原因，`data` 为 `null` 或补充信息。
**降级路径同样返回 HTTP 200 且保持本结构**，不抛 500。

| 字段 | 说明 |
| --- | --- |
| `code` | 业务码。业务失败一律 **HTTP 200 + 非 200 的 `code`**，前端统一读 `code` 判断成败 |
| `message` | 提示信息，可直接展示给用户 |
| `data` | 业务数据，失败时为 `null` |

> **HTTP 状态码的少数例外**：鉴权失败返回真实 `401`，参数校验失败返回真实 `422`（FastAPI 默认行为）。除此之外一切业务结果都是 HTTP 200，由 `code` 表达。

### 通用约定

所有接口统一前缀 `/api/v1`。

鉴权：除 `/api/v1/health` 外，全部接口均需在请求头携带 JWT。

```
Authorization: Bearer <token>
```

身份（用户ID、角色）一律由后端从 JWT 解析。**请求体中出现的 `userId` / `receiverId` / `handlerId` 等身份字段一律被忽略**（主文档 5.1，防止身份伪造）。

---

## 模块 4：核心调度 Agent

负责人：徐川　｜　状态：契约已冻结（阶段 2）

### POST /api/v1/agent/schedule

根据自然语言需求生成场地与设备调度方案。

**认证**：必须携带 `Authorization: Bearer <JWT>`。用户身份从 JWT 解析。

**请求体**

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `text` | string | 是 | 长度 1~1024 | 用户原始自然语言需求 |
| `imageContext` | object | 否 | 默认 `{}` | 模块 2 传入的图像解析上下文 |

**注意：请求体没有 `userId` 字段。** 身份一律从 JWT 解析（主文档 5.1、9.1）；请求体若夹带 `userId` 会被忽略。若从请求体取用户 ID，任何人都能替别人预约。

`text` 为空字符串时返回 422，不会让 Agent 空跑一次大模型。

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
| `trace` | array | 思考链，前端按 `timestamp` 时间轴回放 |
| `needConfirm` | boolean | 是否需要人工确认 |

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

三种情形 `plan` 均为 `null`、`needConfirm` 均为 `true`，区别只在 `message`：

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
| — | 401 | 缺少或无效的 `Authorization` |
| — | 422 | `text` 为空或超长 |

**禁止事项**

- 不存在 `/api/v1/tools/*` 路由：Tool 是给模型调用的内部函数，不对外暴露（主文档 5.3、9.3）
- 请求体不接受 `userId`

### 相关接口

模块 7 的 `POST /api/v1/notify/generate` 以**内部 Tool** 形式提供 `generate_notification`，供本模块的 `create_agent` 注册调用（用户说「提前通知参会人员」时触发）。该 Tool **不注册为公开 HTTP 端点**，详见「模块 7」小节的末尾说明。

---

## 模块 7：AI 冲突预警与智能通知

负责人：黄嵩　｜　状态：契约已实现（追加式变更，见下）

### GET /api/v1/conflicts/scan

扫描当前所有软冲突，供看板轮询展示。

**本接口是只读的**：不落库、不推送消息，可重复调用、幂等，前端可放心轮询。消息推送由后台周期任务与事件总线负责。

**请求参数**：无。

**响应示例**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": [
    {
      "conflictType": "软冲突",
      "orderIds": [1001, 1002],
      "suggestion": "建议将后一场活动延后至少 15 分钟，或改到同一场地连排，为预约人留出转场与休息时间。",
      "ruleCode": "continuous_activity"
    }
  ]
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `conflictType` | string | 固定为 `软冲突`。硬冲突（时间重叠）由 `reserve_order` 的事务与唯一索引拦截，不属于本接口范围 |
| `orderIds` | int[] | 关联订单ID。长期闲置类冲突没有关联订单，返回 `[]` 而非 `null` |
| `suggestion` | string | 处置建议 |
| `ruleCode` | string | 规则编码，见下表 |

**规则编码**

| `ruleCode` | 含义 | 通知对象 |
| --- | --- | --- |
| `continuous_activity` | 同一用户相邻两场预约间隔不足 15 分钟 | 预约人 + 管理员 |
| `capacity_overflow` | 场地容量远超实际参会人数 | 预约人 + 管理员 |
| `high_value_device_low_priority` | 高价值设备被普通使用者占用 | 预约人 + 管理员 |
| `space_overuse` | 同一场地单日累计占用超 8 小时 | 管理员 |
| `space_idle` | 场地连续 14 天无有效预约 | 管理员 |

> **契约变更说明（主文档 2.5）**
> 原始契约只有 `conflictType` / `orderIds` / `suggestion` 三个字段。本模块**追加**了 `ruleCode`，属向后兼容的追加式变更：前端可忽略该字段，已有渲染逻辑不受影响；若前端需要按规则图标或筛选，可直接使用。

**错误码**

| code | HTTP | 场景 |
| --- | --- | --- |
| — | 401 | 未携带 token / token 格式错误 / 签名无效 / 已过期 |

---

### POST /api/v1/notify/generate

按指定语气生成一条通知文案，**并推送给预约人与全体管理员**（写入 `notify_message`）。

**请求体**

```json
{
  "type": "延期致歉",
  "orderInfo": {
    "orderId": 1001,
    "reason": "场地临时被占用"
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `type` | string \| int | 是 | 通知语气。可传中文名：`提醒` / `延期致歉` / `故障告警`；也可传 `notify_type` 整数：`1` / `2` / `3` |
| `orderInfo` | object | 否 | 订单事实载荷，缺省为 `{}`。详见下方说明 |

**`orderInfo` 说明**

- `orderId`：关联的预约订单ID。**提供时**，后端会从数据库读取该订单的场地名、预约人、时间等事实并据此生成文案，同时把通知写入 `notify_message`；**不提供或订单不存在时**，只生成文案、不落库、不推送。
- 其余键会作为**补充事实**参与文案生成（如 `reason` 原因、`ruleLabel` 规则名、`deviceName` 设备名）。
- **数据库里已有的事实以数据库为准**，载荷不能覆盖。例如载荷传 `spaceName` 而库中该订单场地为「A栋3楼展厅」，则一律使用库中的场地名 —— 防止错误的场地名被 AI 写进正式通知。
- 载荷中的 `userId` / `receiverId` / `notifyType` 等字段被忽略。

**响应示例**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "title": "【预约变更致歉】A栋3楼展厅 14:00",
    "content": "张三 您好，非常抱歉，您在 A栋3楼展厅 的预约（订单号 1001，2026-09-25 14:00 至 2026-09-25 16:00）发生变更。原因：场地临时被占用。建议方案：建议改约至 B栋多功能厅……"
  }
}
```

`data` **严格只有 `title` 与 `content` 两个字段**。降级来源（AI 生成 / 模板兜底）属于内部信息，不对外暴露。

**错误码**

| code | HTTP | 场景 |
| --- | --- | --- |
| 400 | 200 | `type` 不是受支持的语气 |
| — | 401 | 未携带 token / token 无效或过期 |
| — | 422 | 缺 `type` 等参数校验失败 |

**行为说明**

- **多语气**：同一次调用会按收件人角色分别生成文案（预约人 / 资源管理员 / 系统管理员），同一角色只调用一次大模型。响应中返回的是**调用方自身角色**视角的那一份。
- **幂等**：同一订单 + 同一语气 + 同一收件人在 24 小时内只落库一次（去重窗口由 `CONFLICT_DEDUP_TTL_SECONDS` 配置）。重复调用仍会正常返回文案，只是不再重复写入。
- **降级**：大模型超时、报错、返回非 JSON 时自动降级为多语气模板文案，接口始终返回可用结果，不会因 AI 故障失败（主文档 13.1）。

---

### GET /api/v1/health

健康检查，无需鉴权。

```json
{ "code": 200, "message": "操作成功", "data": { "status": "ok" } }
```

---

### 本模块的内部 Tool 不对外暴露

`agent/tools/notify_tools.py` 中的 `generate_notification` 是供主调度 Agent 调用的**内部工具**，按主文档 9.3 不注册为公开 HTTP 端点。

#### 供给模块 4 的工具签名（★ 已冻结，不得再改）

模块 4（核心调度 Agent）的注册入口：

```python
from app.agent.tools.notify_tools import NOTIFY_TOOLS   # = (generate_notification,)
```

```python
async def generate_notification(
    order_id: int,
    notify_type: str = "提醒",
    reason: str = "",
) -> str: ...
```

| 项 | 值 |
| --- | --- |
| 工具名 | `generate_notification`（LangChain 侧与 Python 侧一致） |
| 调用方式 | 异步，`await tool.ainvoke({...})` |
| `order_id` | `integer`，**必填**，须为正整数；否则返回 `code=400` |
| `notify_type` | `string`，默认 `"提醒"`；取值「提醒」「延期致歉」「故障告警」 |
| `reason` | `string`，默认 `""`（空串按无原因处理） |
| 返回 | JSON 字符串。成功 `{code:200, title, content, receivers}`；失败 `{code, message}`；**不抛异常**（抛栈会打断对话） |

⚠️ **该签名已对模块 4 冻结。** 改动参数名、顺序、默认值或必填项，都会让模块 4 的工具注册与提示词失效，属跨模块接口变更。确需变更时必须三处同步：① 知会模块 4；② 更新本节；③ 更新 `tests/unit/test_notify_tools.py::test_tool_signature_is_frozen`——该用例会在签名被改动时直接失败。

---

## 模块 10：监控

### GET /api/v1/monitor/agent

Agent 调用埋点（主线二与模块 10 展示用）。

**响应 data 结构**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `totalCalls` | int | 累计调用次数 |
| `successRate` | number | 成功率 |
| `avgLatency` | number | 平均耗时（毫秒） |

> 成功率口径：`plan` 非空且未触发降级才计入成功。若把降级也计入，展示数据会虚高。

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
| 模块 8 小程序端 | |
| 模块 9 PC 管理端 | |

> 模块 4（核心调度 Agent）见上「模块 4」小节；**模块 7（AI 冲突预警与智能通知）已完成，见上「模块 7」小节**，故不再列于本表。
