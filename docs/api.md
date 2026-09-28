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
| 模块 7 消息通知 | 黄嵩 |
| 模块 8 小程序端 | |
| 模块 9 PC 管理端 | |
