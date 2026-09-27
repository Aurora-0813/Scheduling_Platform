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

负责人：徐川　｜　状态：**已定稿（阶段 6，实现与文档一致）**

字段级契约自阶段 2 冻结后**未再变更**；本节在阶段 6 补齐的是实现侧的确定项：
503 的触发条件、401 与参数校验失败也走统一响应体、以及 mock 端点的注册条件。
已按本契约实现并实测：`backend/app/api/v1/agent.py`、`docs/mock/agent_schedule.json`。

> **参数校验口径变更（2026-09-27，非字段级）**：本模块原先规定 `text` 为空或超长返回
> HTTP 422，后在合并全局异常处理器时让给了模块 1/2 的口径 —— **HTTP 200 + `code=400`**。
> 理由是 `core/exceptions.py` 的 `RequestValidationError` 处理器全应用只有一份，
> 而模块 1/2 的用例断言 `body["code"] == 400`。字段本身、约束范围、以及
> 「不空跑模型」的行为均未变。偏离已记入 `docs/spec/done/stage-02-completion.md`。

### POST /api/v1/agent/schedule

根据自然语言需求生成场地与设备调度方案。

**认证**：必须携带 `Authorization: Bearer <JWT>`。用户身份从 JWT 解析。

**请求体**

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `text` | string | 是 | 长度 1~1024 | 用户原始自然语言需求 |
| `imageContext` | object | 否 | 默认 `{}` | 模块 2 传入的图像解析上下文 |

**注意：请求体没有 `userId` 字段。** 身份一律从 JWT 解析（主文档 5.1、9.1）；请求体若夹带 `userId` 会被忽略。若从请求体取用户 ID，任何人都能替别人预约。

`text` 为空字符串时被参数校验挡下，返回 **HTTP 200 + `code=400`**（见下方错误码表），
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
| — | 401 | 缺少或无效的 `Authorization` |
| 400 | 200 | `text` 为空或超长（参数校验的统一口径，见本节开头说明） |
| 503 | 503 | **服务端**未配置大模型（`.env` 缺 `LLM_MODEL_NAME`/`LLM_API_KEY`/`LLM_BASE_URL`） |

**以上非 200 的响应体与成功路径结构完全相同**（同为 `{code, message, data}`），
前端只需要一套解析逻辑。这是阶段 6 的完成判定之一：
异常不得穿透到 FastAPI 的默认错误处理（那会返回 `{"detail": ...}`）。

503 与三条降级路径的**区别要留意**：降级是「模型跑了但没给出方案」，HTTP 200；
503 是「模型根本没跑起来」，属服务端配置问题，**必须显式暴露**——
伪装成 200 + `plan=null` 会让运维以为是模型不行，实际是 key 没配。

**禁止事项**

- 不存在 `/api/v1/tools/*` 路由：Tool 是给模型调用的内部函数，不对外暴露（主文档 5.3、9.3）
- 请求体不接受 `userId`

### GET /api/v1/mock/agent/schedule

**仅 `DEBUG=true` 时注册**；演示/生产环境（`DEBUG=false`）下该路径不存在，返回 404。

固定响应体，字段与上面的 `data` 结构逐一相同，供前端在联调前渲染屏 3 的思考链、
以及作为演示当天 Agent 超时时的预置回放素材。

数据源文件：`docs/mock/agent_schedule.json`（7 步、时间戳跨 39 秒、间隔不均）。
完整样例可直接取该文件——它同时是前端渲染、40 秒回放、13.1 应急预案三处共用的那一份。

---

## 模块 10：监控

### GET /api/v1/monitor/agent

负责人：徐川　｜　状态：**已定稿（阶段 6）**

Agent 调用埋点（主线二与模块 10 展示用）。

**认证**：必须携带 `Authorization: Bearer <JWT>`（主文档 9.1：除登录外所有端点需认证）。

**响应 data 结构**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `totalCalls` | int | 累计调用次数 |
| `successRate` | number | 成功率（百分数，保留一位小数） |
| `avgLatency` | number | 平均耗时（**毫秒**） |

> 成功率口径：`plan` 非空且未触发降级才计入成功。若把降级也计入，展示数据会虚高。
> 无调用时三个字段返回 `0` / `0.0` / `0`，**不返回 `null`**——前端对 `successRate`
> 做 `toFixed(1)`，拿到 `null` 会直接抛错。

**存储**：当前为**进程内计数**，服务重启清零、多 worker 各自计数。
`TODO(申云飞)`：埋点存储方式（Redis 或库表）与集成组确认后替换，
替换点只在 `backend/app/services/agent_service.py` 一个文件内。

**错误码**

| code | HTTP | 场景 |
| --- | --- | --- |
| 200 | 200 | 正常（含无调用时的零值） |
| — | 401 | 缺少或无效的 `Authorization` |

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
