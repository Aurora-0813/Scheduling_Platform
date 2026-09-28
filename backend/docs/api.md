# API 接口文档

> 适用范围：后端全部接口（模块 1～10）。
> 本文档由**模块 10 系统集成与联调**维护，模块 9 的接口由模块 9 提供实现细节。
> 字段命名、响应结构、错误码等**跨模块约定**以本文档为准；模块内部实现细节以代码为准。
>
> 权威来源：仓库根目录 `开发流程.md` 第 5 章（接口规范）、第 9 章（安全规范）。
> 本文档与代码不一致时，以**代码**为准，并请指出以便更新本文档（约定见第 12 节）。

---

## 一、全局约定

### 1.1 接口前缀

所有业务接口以 `/api/v1/` 开头（`开发流程.md` 5.1）。文档中的路径一律省略该前缀的说明，均按完整路径书写。

### 1.2 统一响应体

**成功与失败的响应结构完全一致**（`开发流程.md` 5.2），前端只需判断 `code === 200`：

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {}
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `code` | int | 业务码，5 位。成功恒为 `200`，与 HTTP 状态码**解耦**（见 1.4） |
| `message` | string | 面向用户的提示文案，可直接展示 |
| `data` | object / array / null | 业务数据。文档 5.3 中 `→` 之后的内容指的就是 `data` |

`开发流程.md` 5.3 的接口契约一律描述 `data` 的内容。

### 1.3 字段命名

- API 传输字段一律 **camelCase**（`开发流程.md` 6.2），例如 `accessToken`、`deviceIds`、`inspectorId`；
- 数据库表名与字段名为 `snake_case`；
- 转换由 `app/core/camel.py` 的 `CamelModel` 自动完成，业务代码里写 snake_case 即可；
- **入参两种写法都接受**（`populate_by_name=True`），但请统一用 camelCase；
- **多余字段会被忽略而不是报错**（`extra="ignore"`），因此前端版本比后端新时不会整片接口不可用。

### 1.4 业务码与 HTTP 状态码

`code` 的分段规则（`app/core/error_codes.py`）：

| 区间 | 含义 |
| --- | --- |
| `200` | 成功 |
| `400xx` | 请求参数错误 |
| `401xx` | 认证失败（未登录 / 凭据无效） |
| `403xx` | 授权失败（已登录但无权限） |
| `404xx` | 资源不存在 |
| `409xx` | 冲突 |
| `429xx` | 频率限制 |
| `500xx` | 服务端内部错误 |
| `503xx` | 依赖服务不可用 |

HTTP 状态码**跟随业务码分段**，但有四个刻意的例外：

| 情形 | HTTP | code | 说明 |
| --- | --- | --- | --- |
| 请求方法不被允许 | `405` | `40000` | 框架层产生，无对应的 `405xx` 段 |
| 路由不存在 | `404` | `40400` | 与「资源不存在」共用一段 |
| Pydantic 校验失败 | `400` | `40001` | FastAPI 默认是 422，本项目的异常处理器改为 400 |
| AI 输出无法解析 | `502` | `50001` | 上游大模型的问题，用 502 与「服务内部错误」区分 |

> ⚠️ **前端请按 `data` 之外的 `code` 分支，不要按 HTTP 状态码分支。**
> 仅 HTTP 401 底下就有 7 个含义完全不同的业务码：`40103` 应去续期、`40105`/`40106` 应重新登录、
> `40107` 是密码错、`40108` 是账号被禁用（应提示联系管理员）。按 401 一律跳登录页会掩盖真实原因。

### 1.5 时间与布尔值

- **时间格式一律 `YYYY-MM-DD HH:mm:ss`**（无 `T`、无毫秒、无时区后缀），全链路使用**本地时间 naive datetime**；
- 出参由 `DateTimeStr` 统一格式化，**入参请按契约格式传本地时间**。

> ⚠️ **不要把 `new Date().toISOString()` 的结果直接传上来。**
> 它产出的是 `2026-09-27T10:30:00.000Z`（UTC 带 `Z`）。后端能解析这种写法，但**不做时区换算**，
> 会把 UTC 的墙上时间当作本地时间使用，东八区下**相差 8 小时**。
> 正确做法：`dayjs(t).format('YYYY-MM-DD HH:mm:ss')`。
> 该行为已由 `tests/unit/test_camel_and_datetime.py` 固定为断言，修法（显式拒绝带时区输入）属跨模块契约变更，
> 见 `docs/汇报文档.md` 的待确认项。

- **布尔值一律 `true` / `false`**，禁止用 `0` / `1`（`开发流程.md` 5.1）。
- 不在契约内的 0/1 整型枚举（如 `orderStatus`、`deviceStatus`、`spaceType`）保持整数，取值见 `docs/database.md`。

### 1.6 身份来源

**身份一律从 JWT 解析，禁止从请求体、Query 或 FormData 传入**（`开发流程.md` 5.1 / 9.1）。

契约里出现的 `userId` / `inspectorId` / `handlerId` 都是后端从令牌里取的值，**前端传了也会被忽略**。
这是防身份伪造的核心约定：任何「谁在操作」的信息都不该由调用方声明。

### 1.7 鉴权方式

```
Authorization: Bearer <accessToken>
```

- `accessToken` 有效期 **30 分钟**（`JWT_EXPIRE_MINUTES`），用于访问业务接口；
- `refreshToken` 有效期 **7 天**（`JWT_REFRESH_EXPIRE_DAYS`），**只能**用于 `POST /api/v1/auth/refresh`；
- 用 `refreshToken` 调业务接口会被拒（`40104`），这是刻意设计的类型校验。

### 1.8 响应头

| 头 | 说明 |
| --- | --- |
| `X-Request-Id` | 每个请求的追踪 ID，已通过 CORS `expose_headers` 暴露给前端。**报错时请把这个值贴给后端**，可直接定位到访问日志与堆栈 |

> ⚠️ **已知边界**：未预料的异常（HTTP 500 / `50000`）响应里**没有 `X-Request-Id`，也没有 CORS 头**。
> 原因是兜底的 `Exception` 处理器由 Starlette 的 `ServerErrorMiddleware` 调用，它位于全部业务中间件之外，
> 生成的响应不会再回穿 CORS 与 RequestContext。这是框架结构决定的，已由 `tests/api/test_cors.py` 固化为断言。
> 排查这类故障请按 `method + path` 关联服务端那条 **ERROR 级访问日志**（它带 requestId）与紧跟其后的堆栈日志。

### 1.9 CORS

后端在 API 网关层统一配置 CORS（`开发流程.md` 5.4），允许来源由 `.env` 的 `CORS_ORIGINS` 白名单控制（默认 `http://localhost:5173,http://127.0.0.1:5173`）。
预检结果缓存 600 秒。前端与小程序域名加入白名单需联系模块 10。

---

## 二、模块 9：用户认证与权限

契约来源：`开发流程.md` 5.3 模块 9（`login` / `info`）。`refresh` 与 `logout` 文档未约定，由本模块按实施方案补齐，已在下方标注。

### 2.1 POST /api/v1/auth/login — 登录

**请求**

```json
{
  "username": "admin",
  "password": "<占位口令，见 docs/seed.sql 说明>"
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `username` | string | 是 | 1～64 字符，首尾空格会被去掉 |
| `password` | string | 是 | 1～72 字符，**不做 strip**（密码里的空格是有效字符） |

**响应（成功）** — `code=200`

```json
{
  "code": 200,
  "message": "登录成功",
  "data": {
    "accessToken": "eyJhbGciOiJIUzI1NiIs...",
    "refreshToken": "eyJhbGciOiJIUzI1NiIs...",
    "role": "admin"
  }
}
```

`role` 取值：`admin` / `resource_admin` / `user`（见 `docs/数据库设计说明` 的角色表）。

> 契约刻意**只有这三个字段**。没有 `expiresIn` / `tokenType`：前端若需提前刷新，
> 可在本地解析 `accessToken` 的 `exp`（JWT 标准字段），无需额外接口。

**失败分支** — 都在密码校验**通过之后**才可能返回，因此「密码是对的但被拦住」是正常语义：

| 情形 | HTTP | code |
| --- | --- | --- |
| 用户名或密码错误 | 401 | `40107` |
| 账号已禁用（`sys_user.status=0`） | 401 | `40108` |
| 账号未分配角色（`sys_user.role_id IS NULL`） | 403 | `40302` |
| 连续失败导致临时锁定（仅在 `AI_RISK_ENABLED=true` 时） | 401 | `40109` |
| 参数校验失败 | 400 | `40001` |
| Redis 不可用 | — | **不影响登录**，见 2.6 |

> 安全说明：账号不存在与密码错误**返回同一个 `40107`**，不区分，避免用户名枚举。
> 校验失败路径还会执行一次等价的 bcrypt 计算（`fake_verify_password`），使「账号不存在」与「密码错误」的响应耗时接近，防止时序侧信道。

### 2.2 GET /api/v1/auth/info — 当前用户信息

需要 `Authorization` 头。

**响应（成功）**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "id": 1,
    "username": "admin",
    "role": "admin",
    "avatar": null,
    "permissions": ["agent:schedule", "conflict:resolve", "dashboard:view", "..."]
  }
}
```

| 字段 | 说明 |
| --- | --- |
| `permissions` | 权限码数组，**已排序**（集合迭代顺序不稳定，排序后前端缓存与测试对比才稳定）。前端据此渲染菜单 |
| `role` | 为 `null` 表示账号未分配角色。该状态在登录时已被拒（`40302`），正常流程不会出现 |
| `avatar` | 头像地址，可为 `null` |

> 权限码格式为 `模块:动作`（如 `order:create`）。完整清单见 `app/core/permissions.py` 的 `Permission` 类与 `docs/数据库设计说明` 的角色权限表。
> `permissions` 中出现 `["*"]` 表示**拥有全部权限**（通配符）。演示种子数据刻意不使用通配符，以便「管理员拥有全部权限」这件事直观可查。

**失败分支**

| 情形 | HTTP | code |
| --- | --- | --- |
| 没有 `Authorization` 头 / 头里没有令牌 | 401 | `40101` |
| 签名错、结构损坏、缺字段 | 401 | `40102` |
| 已过期 | 401 | `40103` |
| 拿 `refreshToken` 调本接口 | 401 | `40104` |
| 令牌有效但用户已被删除 | 401 | `40100` |
| 账号被禁用 | 401 | `40108` |
| 账号未分配角色 | 403 | `40302` |

前四种由令牌解析阶段抛出，是**所有需要鉴权的接口共有的**失败形态（见 `app/api/deps.py`）：

```
没有 Authorization 头  → 40101
签名/结构问题          → 40102
已过期                 → 40103   ← 应触发续期
类型不对（用了 refresh）→ 40104
用户已删除             → 40100
账号被禁用             → 40108
未分配角色             → 40302
```

### 2.3 POST /api/v1/auth/refresh — 续期（轮换令牌）

> 本接口 `开发流程.md` 5.3 未约定，属模块 9 补充契约。**不需要** `Authorization` 头 —— 触发时机正是 `accessToken` 已过期。

**请求**

```json
{ "refreshToken": "eyJhbGciOiJIUzI1NiIs..." }
```

**响应（成功）** — 返回**新的令牌对**，旧的 `refreshToken` 随即失效

```json
{
  "code": 200,
  "message": "续期成功",
  "data": {
    "accessToken": "eyJ...",
    "refreshToken": "eyJ..."
  }
}
```

**轮换语义（前端必须实现，否则会踩到「莫名被登出」）**

1. 旧 `refreshToken` 换取成功后**立即失效**；
2. 旧令牌在 **60 秒宽限期**内仍可**再换一次**（`GETDEL` 语义，消费即失效，**不可无限重放**）；
3. 因此并发的重复刷新最多只有一个能拿到新令牌，其余请求会失败。

> ✅ **前端必须用「单例 Promise」去重刷新**：同一时刻只发一个刷新请求，其余请求等这个 Promise 的结果。
> 不做去重的话，页面上并发的 5 个请求同时 401、同时发起刷新，只有一个会成功、其余 4 个带着旧令牌失败，
> 用户看到的现象就是「用着用着突然要重新登录」。后端宽限期只能缓解，不能替代前端的去重。

**失败分支**

| 情形 | HTTP | code | 前端动作 |
| --- | --- | --- | --- |
| `refreshToken` 不在白名单（已登出 / 已轮换 / 重放 / 已过期清理） | 401 | `40106` | 跳登录页 |
| 令牌版本不符（账号已被强制下线） | 401 | `40105` | 跳登录页 |
| `refreshToken` 已过期 / 签名无效 / 传的是 `accessToken` | 401 | `40103` / `40102` / `40104` | 跳登录页 |
| 账号已不存在 / 已禁用 / 未分配角色 | 401 / 401 / 403 | `40100` / `40108` / `40302` | 提示对应原因 |
| **Redis 不可用** | 503 | `50301` | 见 2.6（本接口刻意**不做降级**） |

### 2.4 POST /api/v1/auth/logout — 登出

> 本接口 `开发流程.md` 5.3 未约定，属模块 9 补充契约。需要 `Authorization` 头。**请求体整体可选。**

**请求**（两种调用方式都支持）

无请求体 —— 吊销该用户的**全部**会话：

```
POST /api/v1/auth/logout
Authorization: Bearer <accessToken>
```

带请求体 —— 只吊销**这一个**会话（其它设备不受影响）：

```json
{ "refreshToken": "eyJhbGciOiJIUzI1NiIs..." }
```

**响应**

```json
{ "code": 200, "message": "已登出", "data": null }
```

**行为规则（一句话：能确定具体会话就只吊销它，否则吊销全部）**

| `refreshToken` 的情况 | 行为 |
| --- | --- |
| 缺失 / 解析失败 / 已过期 / 类型不对 | 吊销该用户**全部**会话 |
| 有效，但属于**别的用户** | `40300`，拒绝（防跨用户踢人） |
| 有效且属于本人 | 只吊销该会话 |

「无法精确定位会话时吊销全部」是刻意的 **fail-safe 而非 fail-open**：登出的语义就是「让我失去访问能力」，
多踢几个自己的会话可接受，而返回成功却什么都没吊销不可接受（那等于假登出，`refreshToken` 还能继续换出新令牌）。

**失败分支**

| 情形 | HTTP | code |
| --- | --- | --- |
| 传了别人的 `refreshToken` | 403 | `40300` |
| 未登录（无 `Authorization` 头） | 401 | `40101` |
| Redis 不可用 | 503 | `50301`（本接口刻意**不做降级**） |

> ⚠️ **已知限制：登出后 `accessToken` 仍能用到自然过期（≤ `JWT_EXPIRE_MINUTES`）。**
> `accessToken` 是无状态校验的（只验签名与过期，不查 Redis）。默认 30 分钟，本仓库 `.env` 当前设为 1440 分钟，
> 因此该窗口在联调环境实际可达 **24 小时** —— 这与文档里「最多 30 分钟」的口径不符，是 `.env` 配置问题而非代码问题，
> 详见 `docs/汇报文档.md` 的待确认项与 `docs/deploy.md` 的加固建议。
> 需要「立即踢出」只能改为每个请求都查 Redis 版本号，代价是每个请求多一次 Redis 往返且 Redis 故障会扩大为全站不可用，当前不做。

> ⚠️ **已知限制（宽限期与登出的交互）：** 登出只清除**本次会话**的白名单条目，而**已被轮换掉的上一代令牌**的 60 秒宽限期标记不受影响。
> 因此「先续期、再登出（只登出本会话）」之后，**上一代的 `refreshToken` 仍可能在宽限期内把会话复活**。
> 该行为已由 `tests/integration/test_auth_flow_db.py` 固定为断言。真正的修法是在令牌里增加 `sid` 声明（会话 ID），
> 属跨模块的 JWT/Redis 契约变更，已列入 `docs/汇报文档.md` 的待确认项，需组内确认后再改。

### 2.5 完整调用流程

```
① POST /auth/login                    → { accessToken, refreshToken, role }
② GET  /auth/info                     → 用户信息 + permissions（渲染菜单）
③ 业务接口（带 Authorization 头）
④ accessToken 过期 → POST /auth/refresh（单例 Promise 去重）
                     → 新的 { accessToken, refreshToken }
⑤ POST /auth/logout                   → 吊销会话
```

### 2.6 Redis 不可用时的降级策略（**前端必须知道**）

| 接口 | Redis 不可用时 | 理由 |
| --- | --- | --- |
| `POST /auth/login` | **照常成功**，只记 warning | 登录时 Redis 只用于登记白名单，登记失败的最坏后果是「这次会话无法续期」，不该因此挡住登录 |
| `POST /auth/refresh` | **严格失败**，返回 `50301` | 读不到白名单就没有任何依据证明令牌仍然有效，此时凭空签发新令牌等于让登出与强制下线彻底失效 |
| `POST /auth/logout` | **严格失败**，返回 `50301` | 同上：读不到就不知道要吊销什么，返回成功等于假登出 |

前端处理建议：`50301` 属于**服务端依赖故障**，应提示「服务暂不可用，请稍后重试」，
**不要**跳登录页（会把「后端 Redis 挂了」误导成「你的登录过期了」）。

`REDIS_ENABLED=false` 时后端自动退化为进程内内存实现，功能完整，
但**服务重启后已登录用户需要重新登录**（`开发流程.md` 13.1 演示应急预案）。

---

## 三、模块 10：系统集成与联调

### 3.1 GET /api/v1/monitor/agent — 大模型调用统计

契约来源：`开发流程.md` 5.3 模块 10。

统计范围：`/api/v1/agent/*` 的全部 HTTP 请求，由中间件自动收集，**业务代码无需埋点**。

**请求**

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `detail` | bool | `false` | 是否返回详细字段（成功/失败/降级明细与数据来源） |

**响应（`detail=false`，即契约形态）**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "totalCalls": 128,
    "successRate": 96.1,
    "avgLatency": 3.2
  }
}
```

| 字段 | 单位 / 取值域 | 说明 |
| --- | --- | --- |
| `totalCalls` | 次 | `agent` 路径的 **HTTP 请求数**，不是 token 数 |
| `successRate` | **百分比** 0～100，1 位小数 | 仅按 HTTP 状态码判定：`< 400` 记为成功 |
| `avgLatency` | **秒**，1 位小数 | `3.2` 表示 3.2 秒 |

> ⚠️ **单位务必与前端面板文案一致**：`successRate` 是 `96.1` 而不是 `0.961`；`avgLatency` 是**秒**而不是毫秒。
> `开发流程.md` 5.3 的示例值即为此口径。若模块 8 的面板文案与之一致，无需改动。

**响应（`detail=true` 时额外字段）**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "totalCalls": 128,
    "successRate": 96.1,
    "avgLatency": 3.2,
    "successCalls": 123,
    "errorCalls": 5,
    "degradedCalls": 9,
    "degradedRate": 7.0,
    "source": "redis"
  }
}
```

| 字段 | 说明 |
| --- | --- |
| `degradedCalls` / `degradedRate` | 大模型降级次数与占比。降级通常仍返回 HTTP 200，因此**单列、不并入 `successRate`** —— 否则模块 4 大量降级时主指标会掉到 80% 以下，看起来像系统故障，实际是设计好的降级路径在生效 |
| `source` | `redis` = 跨重启累计；`memory` = Redis 不可用，数据仅为本进程启动至今 |

**鉴权**：本接口**不鉴权**。理由：它是给监控面板与答辩演示用的只读统计，内容不敏感（调用次数、成功率、耗时），
且面板常在登录态之外加载（如登录页的健康指示），加鉴权反而会让未登录时整块报错。

> 边界与代价：它暴露了「本服务调用大模型的频率」。若将来指标里加入业务维度（按用户/按接口的细分统计），
> **必须**改成 `Depends(require_permission(Permission.MONITOR_VIEW))` —— 那时的数据已能反推出业务量。
> 当前实现刻意不接受任何筛选参数，就是为了不给这条演进留隐性口子。

**埋点的故障隔离**：埋点绝不影响业务 —— 异常全吞、超时复用 `REDIS_SOCKET_TIMEOUT=0.5` 秒、内存实现永不失败。
即使埋点整体失效，`/agent/*` 接口仍正常返回（已由回归测试覆盖）。

### 3.2 GET /api/v1/health — 存活探针

**不检查任何外部依赖**，恒返回 HTTP 200。用于回答「进程还活着吗」。
刻意不检查 DB：一旦检查，「数据库慢」会被误判为「进程已死」并触发重启，反而把可恢复的故障放大成全量不可用。

```json
{
  "code": 200,
  "message": "操作成功",
  "data": { "status": "ok", "service": "SmartScheduler", "env": "dev" }
}
```

### 3.3 GET /api/v1/ready — 就绪探针 / 依赖诊断

**M1 验收工具**（`开发流程.md` 2.4：`本地能跑通 /api/v1/auth/login 空实现，库能连上`）就靠它。
**恒返回 HTTP 200**，依赖状态放在响应体的 `status` 字段里。

```json
{
  "code": 200,
  "message": "操作成功",
  "data": { "status": "ok", "db": "ok", "redis": "ok", "appEnv": "dev" }
}
```

| 字段 | 取值 | 说明 |
| --- | --- | --- |
| `db` | `ok` / `error` | `ok` 表示 `SELECT 1` 成功 |
| `redis` | `ok` / `degraded` / `disabled` | `disabled` 表示 `REDIS_ENABLED=false`，**属正常配置**，此时 refreshToken 走进程内存储 |
| `status` | `ok` / `degraded` | 数据库正常且 Redis 为 `ok` 或 `disabled` 时为 `ok`，否则为 `degraded` |

> **为什么恒 200 而不是「依赖挂了就 503」**：它是给人看的**诊断接口**。
> 若依赖挂掉就返回 503，浏览器与前端只会看到一个错误页，看不到「到底哪一项不通」，排查时必须去看服务器日志。
> 编排层探针需要的「非 200 即摘除」语义请**另建**路径，不要为迎合探针牺牲本接口的诊断能力（本项目当前不部署 K8s）。
>
> 响应体里绝不出现连接串与密码（`开发流程.md` 9.4），失败原因只写服务端日志。

### 3.4 Mock 路由 `/api/v1/mock/*` — 仅 `DEBUG=true` 时注册

供前端与小程序**并行开发**（`开发流程.md` 8.8），返回静态示例数据。
`DEBUG=false` 时这些路由**不存在**（返回 404），因此**生产环境不会暴露**。

| 方法 | 路径 | 对应真实模块 |
| --- | --- | --- |
| POST | `/mock/voice/asr` | 模块 1 语音转文字（FormData：`file`） |
| POST | `/mock/voice/format` | 模块 1 语音文本纠错 |
| POST | `/mock/image/analyze` | 模块 2 空间识别（FormData：`file`） |
| POST | `/mock/image/sketch` | 模块 2 草图分析（FormData：`file`） |
| POST | `/mock/orders/create` | 模块 3 创建预约 |
| GET | `/mock/orders/my` | 模块 3 我的预约 |
| PUT | `/mock/orders/{orderId}/cancel` | 模块 3 取消预约 |
| GET | `/mock/messages/unread` | 模块 3 未读消息 |
| POST | `/mock/agent/schedule` | 模块 4 智能调度 |
| GET | `/mock/resources/spaces` | 模块 5 场地列表 |
| POST | `/mock/resources/spaces` | 模块 5 新增场地 |
| GET | `/mock/resources/devices` | 模块 5 设备列表 |
| PUT | `/mock/resources/devices/{deviceId}` | 模块 5 修改设备 |
| POST | `/mock/inspect/submit` | 模块 6 提交巡检（FormData） |
| GET | `/mock/tickets/list` | 模块 6 工单列表 |
| PUT | `/mock/tickets/{ticketId}/status` | 模块 6 处理工单 |
| GET | `/mock/conflicts/scan` | 模块 7 冲突扫描 |
| POST | `/mock/notify/generate` | 模块 7 生成通知文案 |
| GET | `/mock/dashboard/stats` | 模块 8 面板统计 |
| GET | `/mock/dashboard/report` | 模块 8 洞察报告 |
| POST | `/mock/monitor/simulate` | 模块 10 模拟 Agent 调用（用于演示 `/monitor/agent` 的指标变化） |

> Mock 路由**不鉴权**，便于前端在没有后端登录态时也能拿到数据。
> 它们的出参同样包在统一响应体里，因此前端从 Mock 切到真实接口时**只需改 baseURL / 路径，不需要改解析逻辑**。

---

## 四、错误码总表

完整定义见 `app/core/error_codes.py`（`ErrorCode` 与 `DEFAULT_MESSAGES`）。

### 400xx 请求参数错误

| code | message | 典型触发 |
| --- | --- | --- |
| `40000` | 请求参数有误 | HTTP 405 方法不允许 |
| `40001` | 参数校验未通过 | Pydantic 校验失败，`data.errors` 里是 `[{field, message}]` |
| `40002` | 上传文件超过大小限制 | 见 `app/utils/upload.py` |
| `40003` | 上传文件类型不支持 | 同上 |
| `40004` | 时间范围不合法 | `endTime <= startTime` 等 |

`40001` 的 `data` 结构：

```json
{
  "code": 40001,
  "message": "参数校验未通过：password 该字段为必填项",
  "data": {
    "errors": [ { "field": "password", "message": "该字段为必填项" } ]
  }
}
```

> `field` **一律是 camelCase**，无论前端传的是 `user_name` 还是 `userName`，
> 前端可直接用它定位要高亮哪个输入框。嵌套结构用 `.` 连接、数组下标保持数字，如 `items.0.spaceId`。

### 401xx 认证失败

| code | message |
| --- | --- |
| `40100` | 未登录或登录状态已失效 |
| `40101` | 缺少认证令牌 |
| `40102` | 认证令牌无效 |
| `40103` | 认证令牌已过期 |
| `40104` | 认证令牌类型不正确 |
| `40105` | 认证令牌已失效，请重新登录 |
| `40106` | 刷新令牌无效或已被使用 |
| `40107` | 用户名或密码错误 |
| `40108` | 账号已被禁用，请联系管理员 |
| `40109` | 账号因异常登录被临时锁定，请稍后重试 |

### 403xx 授权失败

| code | message |
| --- | --- |
| `40300` | 没有访问权限 |
| `40301` | 当前角色缺少所需权限 |
| `40302` | 账号未分配角色，请联系管理员 |

`40301` 的 message 里**带所需权限码**（如 `当前角色缺少所需权限：order:create`），便于联调时直接定位。
权限码不是机密，可安全返回。

### 404xx / 409xx / 429xx

| code | message |
| --- | --- |
| `40400` | 请求的资源不存在 |
| `40401` | 用户不存在 |
| `40402` | 空间资源不存在 |
| `40403` | 设备资源不存在 |
| `40404` | 预约订单不存在 |
| `40405` | 维修工单不存在 |
| `40406` | 巡检记录不存在 |
| `40407` | 消息不存在 |
| `40900` | 操作与当前数据状态冲突 |
| `40901` | 目标时段资源已被占用 |
| `40902` | 用户名已存在 |
| `40903` | 订单当前状态不允许该操作 |
| `42900` | 操作过于频繁，请稍后重试 |

### 500xx / 503xx

| code | message |
| --- | --- |
| `50000` | 服务内部错误，请稍后重试 |
| `50001` | AI 返回内容无法解析 |
| `50300` | 依赖服务暂不可用，请稍后重试 |
| `50301` | 缓存服务暂不可用，请稍后重试 |
| `50302` | 数据库暂不可用，请稍后重试 |
| `50303` | 外部接口调用失败，请稍后重试 |

> `503xx` 是**依赖故障**，前端应提示「稍后重试」而**不是**跳登录页。

---

## 五、分页约定

列表类接口统一使用下列 Query 参数与出参结构（`app/utils/pagination.py`），具体接口是否分页由各模块决定。

**入参**

| 参数 | 类型 | 默认 | 约束 |
| --- | --- | --- | --- |
| `page` | int | 1 | ≥ 1 |
| `pageSize` | int | 10 | 1～100，超过上限会被夹到 100（不是报错） |

**出参**

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "page": 1,
    "pageSize": 10,
    "total": 57,
    "list": []
  }
}
```

> `pageSize` 超限**夹取而不报错**：前端传 `pageSize=1000` 时返回 100 条即可，
> 让它报 400 只会让「想多拉一点数据」的调用方多一次失败重试。

---

## 六、接口实现进度

| 模块 | 接口 | 状态 |
| --- | --- | --- |
| 9 | `POST /auth/login`、`GET /auth/info`、`POST /auth/refresh`、`POST /auth/logout` | ✅ 已实现 |
| 10 | `GET /monitor/agent`、`GET /health`、`GET /ready` | ✅ 已实现 |
| 10 | `/mock/*`（21 条） | ✅ 已实现（仅 `DEBUG=true`） |
| 1～8 | `开发流程.md` 5.3 列出的业务接口 | ⏳ 由各模块负责人实现；当前可用 `/mock/*` 联调 |

**模块 1～8 的接口接入方式**（不需要改 `app/main.py`）：

1. 在 `app/api/v1/` 下新建路由文件，定义 `router = APIRouter(prefix="/xxx", tags=[...])`；
2. 把它加进 `app/api/v1/__init__.py` 的 `api_router`；
3. 出参模型继承 `app/core/camel.py` 的 `CamelModel`，时间字段用 `DateTimeStr`，金额用 `MoneyStr`；
4. 身份从 `Depends(get_current_user)` 取，权限用 `Depends(require_permission(Permission.XXX))`；
5. 写库后**必须显式 `await db.commit()`**（见第 7 节）。

`app/main.py` 是**全组唯一的集成点**，只 include 那一个汇总 router —— 这样能避免 5 个人反复改同一个文件造成冲突。

---

## 七、事务边界（写接口必读）

**`get_db` 只负责「异常回滚 + 关闭会话」，不负责提交。**

提交必须由 `services/` 层在业务结尾显式调用：

```python
async def create_order(db: AsyncSession, ...) -> ...:
    order = ReserveOrder(...)
    db.add(order)
    await db.commit()          # ← 这一行不能忘
    return order
```

忘记 commit 的后果是：**接口返回 200、日志里没有任何异常、数据没落库**，
表现为「刚创建的预约刷新一下就不见了」。这类缺陷排查成本极高，因此：

- 已由 `tests/integration/test_db_session_contract.py`（`@pytest.mark.db`）用「未提交的写入在**另一个连接**里查不到」钉死；
- `app/services/auth_service.py` 整条链路**不写库**（登录只读、续期只读、登出只动 Redis），
  因此认证测试覆盖不到事务边界 —— 将来在认证链路上加写入（如「更新最后登录时间」）时**必须显式提交**。

---

## 八、给前端 / 小程序的联调清单

1. **baseURL** 指到后端（默认 `http://127.0.0.1:8000`），所有路径带 `/api/v1/` 前缀；
2. **响应解析**：先判 `code === 200` 再取 `data`，不要把 `data` 当响应体整体用；
3. **错误分支按 `code` 判断**，不要按 HTTP 状态码；
4. **401 的处理**：`40103` → 续期；`40102`/`40104`/`40105`/`40106` → 跳登录页；`40107` → 提示密码错误；`40108` → 提示账号禁用；
5. **`50301` 不要跳登录页**，提示「服务暂不可用」；
6. **续期用单例 Promise 去重**（见 2.3）；
7. **时间一律 `YYYY-MM-DD HH:mm:ss` 本地时间**，不要传 `toISOString()` 的结果（见 1.5）；
8. **不要传 `userId` / `inspectorId` / `handlerId`**，后端从令牌解析（见 1.6）；
9. **报错时把 `X-Request-Id` 贴给后端**（500 除外，那种情况没有该头，见 1.8）；
10. 后端未实现的接口先用 `/mock/*`（需要后端 `DEBUG=true`）。

---

## 九、文档维护约定

| 变更类型 | 需要做的事 |
| --- | --- |
| 新增/修改接口 | 更新本文档对应的章节；若涉及 `开发流程.md` 5.3 的契约，**必须先与模块 10 确认** |
| 新增错误码 | 在 `app/core/error_codes.py` 注册并补 `DEFAULT_MESSAGES`，同步本文档第四节 |
| 修改全局约定（前缀/响应体/命名/时间格式） | 属**跨模块契约变更**，需组内公告并同步 `开发流程.md` 与前端 |
| 模块 1～8 接入路由 | 只需改 `app/api/v1/__init__.py`，不需要改 `app/main.py` |

> **禁止在本文档（及任何仓库内文件）写入真实密码、令牌、API Key 或连接串**（`开发流程.md` 9.4 / 11.2），
> 一律使用占位符。`docs/seed.sql` 里的口令是**演示占位口令**，首次部署后必须立即修改，说明见该文件头部注释。

---

## 十、交互式接口文档

服务启动后可访问自动生成的 OpenAPI 文档，用于在线试调：

| 地址 | 说明 |
| --- | --- |
| `http://127.0.0.1:8000/docs` | Swagger UI，**可直接发请求**（推荐联调时用） |
| `http://127.0.0.1:8000/redoc` | ReDoc，阅读体验更好 |
| `http://127.0.0.1:8000/openapi.json` | OpenAPI 3.1 原始描述，可导入 Postman / Apifox |

> 接口文档当前**始终开放**。本项目是内网部署的课设系统，接口文档对前端/小程序联调是刚需；
> 若将来对外发布，请在非 dev 环境关闭（做法见 `docs/deploy.md`）。
