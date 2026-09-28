# 阶段 06 完成文档：API 层

| 项 | 内容 |
| --- | --- |
| 阶段 | 阶段 06 · API 层 |
| 对应文档 | `docs/spec/stage-06-api.md` |
| 负责人 | 徐川 |
| 开始日期 | 2026-09-27 |
| 完成日期 | 2026-09-27 |
| 计划工时 | 1.5 人日 |
| **实际工时** | 1.2 人日 |
| 验收测试 | `AGENT-STAGE-06` |
| **验收结论** | **有条件通过** —— 六步验收全部执行且结果符合通过标准；条件是①埋点为进程内计数（入口条件欠账）②正常路径的实测是在注入假模型下完成的（`.env` 无 LLM 凭据） |

## 1. 本阶段目标与达成情况

目标：端点、超时降级、埋点三件事一次做齐。

三件全部达成：

- **端点**：`POST /api/v1/agent/schedule` 落地，全异步、身份从 JWT 解析
- **超时与降级**：`AGENT_TIMEOUT` 生效，超时后**保留已收集的 trace** 并返回 200
- **埋点**：`GET /api/v1/monitor/agent` 返回 `{totalCalls, successRate, avgLatency}`，
  实测非零（`{'totalCalls': 1, 'successRate': 100.0, 'avgLatency': 978}`）

额外补齐（不在计划内，但不补则本阶段无法验收）：`app/main.py`（应用入口）、
`app/core/response.py`（统一响应体与异常处理器）、`app/core/security.py`（JWT 依赖）。

## 2. 完成判定逐项核对

- [x] 端点全部路径 `async`，无同步 `invoke()` —— 证据：
      `app/api/v1/agent.py` 三个端点均 `async def`；
      `grep -rn "\.invoke(\|\.stream(" app/` 在 Agent 链路上无匹配，
      内部走 `astream()`（`chains/trace.py::collect_stamped_messages`）
- [x] `user_id` 从 JWT 解析；请求体夹带 `userId` 时被忽略 —— 证据：第 3 节 `[④]`，
      请求体传 `userId=999`，`create_order` 实际收到 `user_id=1`（token 里的值）
- [x] 401 与降级路径**仍返回统一响应体** —— 证据：第 3 节 `[③]`，
      `401` 且 `set(body) == {"code","message","data"}`
- [x] 超时路径返回已收集的 `trace` —— 证据：`builder.py::run_schedule` 的
      `except asyncio.TimeoutError` 分支把 `stamped`（sink，边收边填）转成 trace 一并返回；
      结构由 `build_trace()` 产出，与预置 trace（`docs/mock/agent_schedule.json`）
      **同一个 `TraceStep` 契约**，13.1 应急预案可直接切换
- [x] 埋点有真实数据，`monitor` 端点能取到 —— 证据：第 3 节 `[⑤]`
- [x] **`/api/v1/tools/*` 不存在（返回 404）** —— 证据：第 3 节 `[⑥]`
- [x] `docs/api.md` 模块 4 定稿 —— 证据：`docs/api.md`，状态已改为
      「已定稿（阶段 6，实现与文档一致）」，并补齐 503、mock 端点、模块 10 的认证要求

未通过项说明：无未通过项。两条**入口条件欠账**见第 8 节。

## 3. 验收测试执行记录

| 项 | 内容 |
| --- | --- |
| 测试编号 | `AGENT-STAGE-06` |
| 执行环境 | Windows 11；conda 环境 `smart_dev`（Python 3.11.9）；SSH 隧道 3308 通；开发库 `smart_scheduler_dev`；进程内 ASGI 客户端（`httpx.ASGITransport`） |
| 执行命令 | `PYTHONIOENCODING=utf-8 PYTHONPATH=. python <六步自检脚本>` |
| 执行时间 | 2026-09-27 18:58 |

**原始输出**（未改写；`[②]` 一栏为正路径，模型经 `build_model` 注入假模型；
`[②-noLLM]` 为 `.env` 未配 LLM 时的真实表现）：

```text
[②-noLLM] status: 503 | unified: True
    message: 大模型未配置：请在 backend/.env 中填好 LLM_MODEL_NAME / LLM_API_KEY / LLM_BASE_URL
[②] status: 200 | keys: ['code', 'data', 'message']
    plan: A栋3楼展厅 | trace steps: 6 | needConfirm: True
[④] create_order 收到的 user_id: 1 | agent_request: 40 人展厅 | agent_trace: None | order_status: 1
[I-05] 响应体无敏感串 ✓
[③] status: 401 | unified: True
[⑤] monitor: 200 {'totalCalls': 1, 'successRate': 100.0, 'avgLatency': 978}
[⑥] tools/*: 404 {'code': 404, 'message': 'Not Found', 'data': None}
[mock]  200 | steps: 7 | plan: A栋3楼展厅
[I-03] empty text: 422 422
```

逐步对照验收步骤：

| 步骤 | 要求 | 实测 |
| --- | --- | --- |
| ① 起服务 | 服务可起 | `from app.main import app` 成功；路由表 8 条（含 `/docs` 等框架自带） |
| ② 带 JWT 调 POST | 200 + 统一响应体 | `200`，`{code, message, data}`，`data.plan.spaceName=A栋3楼展厅`，`trace` 6 步 |
| ③ 不带 JWT | 401 + 统一响应体 | `401`，`unified: True` |
| ④ 请求体夹带 `userId` | 被忽略，用 JWT 用户 | token 里是 `1`，请求体传 `999`，`create_order` 收到 `user_id=1` |
| ⑤ 查 `monitor` | 真实数据（非 0 非空壳） | `{'totalCalls': 1, 'successRate': 100.0, 'avgLatency': 978}` |
| ⑥ 请求 `/api/v1/tools/query_spaces` | **404** | `404`，`{'code': 404, 'message': 'Not Found', 'data': None}` |

**结论**：通过。两条说明：

- 步骤 ② 的正路径在**注入假模型**下完成。`.env` 未配 LLM 时该步骤的真实返回是
  `503`（同样是统一响应体）——**结构**已经验证，**内容**（真实模型产出的方案）
  尚未验证，属阶段 5 的欠账，不是本阶段的问题。
- `[④]` 的 `agent_trace: None` 是**预期值**：按 2026-09-27 与蔡玉礼对齐的时序方案 (a)，
  `lock_resources` 落库那一刻本次 Agent 运行尚未结束，trace 注定残缺，故落 `None`，
  由路由在跑完后调 `update_agent_trace` 补写。桩期 `orderId` 恒为 `None`，
  补写分支被正确跳过（不会去 UPDATE 一个不存在的订单）。

## 4. 交付物清单

| 交付物 | 计划路径 | 实际路径 | 状态 |
| --- | --- | --- | --- |
| 端点 | `app/api/v1/agent.py` | 同左 | 已交付 |
| 监控端点 | —— | `app/api/v1/monitor.py` | 已交付 |
| 路由装配 | —— | `app/api/v1/router.py` | 已交付 |
| 埋点 | `app/services/agent_service.py` | 同左 | 已交付 |
| 统一响应体与异常处理 | —— | `app/core/response.py` | 已交付（`TODO(申云飞)`） |
| JWT 依赖 | —— | `app/core/security.py` | 已交付（`TODO(申云飞)`） |
| 应用入口 | —— | `app/main.py` | 已交付（主文档 8.5 划归集成组，本模块补最小可运行版本） |
| 接口文档 | `docs/api.md` 模块 4 | 同左（已定稿） | 已交付 |

## 5. 偏离计划之处

| # | 计划 | 实际 | 原因 | 影响 | 是否需要同步团队 |
| --- | --- | --- | --- | --- | --- |
| 1 | 埋点存储方式**先与集成组确认**（入口条件） | 未确认即实现，当前为**进程内计数** | 该确认未到位，而阶段 6 的完成判定要求「埋点有真实数据」且「事后补埋要重跑联调」，拖延代价更高 | 两个已知边界：①进程重启即清零 ②`uvicorn --workers 4` 时四个进程各报一份。两者都只影响**上线形态**，不影响单进程演示。替换点收敛在 `agent_service.py` 一个文件（`record_call` / `snapshot` / `reset` 三个函数） | 是 |
| 2 | 本模块只依赖集成组的 `core/` | 自行补出 `core/response.py` 与 `core/security.py` | `backend/app/core/` 当时只有 `config.py` 与 `database.py`；没有统一响应体就写不出「异常不穿透」，没有 `get_current_user` 就写不出 `AGENT-I-02` | 两份文件均标 `TODO(申云飞)`，接口收窄到 3 个名字（`ok` / `ApiError` / `register_exception_handlers`）与 2 个名字（`CurrentUser` / `get_current_user`），集成组正式版落地后**直接替换文件**，模块 4 代码不动。**（2026-09-28 补记：`security.py` 那 2 个名字已删**——全应用身份依赖统一到 `api/deps.py`，含 agent/mock/monitor 三处迁移，见 `cfb75f0` / `dcc89e7` 与 `core/security.py` 文件头。**替换清单相应缩小为 1 个名字（`get_current_user`，在 `api/deps.py`）。**） | 是 |
| 3 | 本模块只依赖集成组的应用入口 | 自行补出 `app/main.py` | 没有入口就起不了服务，「六次请求」这条验收无从执行 | 已在模块 docstring 写明「其余模块接入时在 `router.py` 加一行 `include_router`，**不要各自新建 FastAPI 实例**」 | 是 |
| 4 | 认证失败的 HTTP 状态码未规定（本阶段只笼统写了「401 与参数校验失败也走统一响应体」） | **2026-09-28 裁定：认证失败保留 HTTP 401**；`AuthError` 单列处理器（`core/exceptions.py::_handle_auth_error`），不再走 `BusinessError` 的 200 | 两条认证实现分歧：`core/security.py` 抛 `ApiError`（HTTP 401）、`api/deps.py` 抛 `AuthError`（原为 200 + `code=401`）。分歧不消掉，第 3 项那条「收窄到 2 个名字、集成组替换文件」就做不到——同一个 401 在两条路径上表现不同 | ①`docs/api.md` 模块 4 的错误码表**本来就写 401**，本次改完反而与它一致；②模块 2 的 `tests/test_image_api.py::test_missing_token_returns_401` 原断言 `status_code == 200`，随裁定改为 401；③「参数校验失败 → 200 + `code=400`」**不受影响**，两者性质不同（前者前端跳登录，后者留在原页改输入） | 是（模块 2 已同步） |

### 5.1 补记：rebase 到 `origin/main`（`9f30d3a`，2026-09-28）后的三处落空

本表记的是阶段 6 当时的判断。合并时正式版落地，其中三条的前提不再成立——**不改写上面的记录，在此补记**：

1. **偏离 #4 的 `ApiError` 在正式版里不存在。** 正式版的异常体系收敛在 `core/exceptions.py`：
   只有 `BizError` / `BusinessError` 层级 + `ErrorCode` 码表，`ApiError` 与 `AuthError`
   两个名字在 `origin/main` 上都是 0 命中。认证路径的 401 由 `_BUSINESS_ERROR_HTTP_STATUS`
   里 401xx → 401 的映射统一承担，裁定要的「401 落 HTTP 401 + 统一响应体」**照旧成立**，
   只是实现载体不是本表写的那两个类名。模块 4 的调用点已就地改掉：
   `api/v1/agent.py` 的 503 路径用 `BusinessError(code=ErrorCode.AI_MODEL_UNAVAILABLE(41003))`
   （正式版码表里 41003 已映射到 503），不再自建异常类。
2. **偏离 #2 的「替换清单」已执行完毕，`core/security.py` 与 `core/response.py` 均取正式版。**
   模块 4 自建的 `core/response.py::ApiError` / `CODE_OK`、
   `core/security.py::create_access_token` / `create_refresh_token` 在正式版里**都不存在**，
   调用点全部迁移完成（用例改用 `create_token` / `ErrorCode`）。身份依赖全应用只剩
   `api/deps.py` 一份 `get_current_user`，`CurrentUser` 的字段名是 `id`（不是 `user_id`），
   agent / mock / monitor 三处均已改指。详见硬卡点表第 7 行。
3. **偏离 #1 与遗留 #2 的埋点实现已被正式版超越，本模块那套现在是死代码。** 正式版的埋点走
   `app/middlewares/agent_metrics.py` + `services/monitor_service.py` + Redis，
   `GET /api/v1/monitor/agent` 读的是它。模块 4 的进程内计数
   （`agent_service.record_call` / `snapshot` / `reset`）**仍被 `agent.py` 调用**，
   但**已无任何读端**——`reset` 还被 `tests/conftest.py` 的 autouse 夹具用着。
   **这是一处待裁决的取舍**：留着会让 `record_call` 每次请求白跑一遍、
   并给读代码的人「埋点在这」的错觉；删掉则要同步动 `agent.py`、`agent_service.py`
   与 `conftest.py` 三处。已登记，未自作主张删除。
   3b（mock.py / monitor.py 的 add/add 冲突）同批裁定为**取正式版**：合并当时正式版的
   `mock.py` 响应只有 4 步 trace、跨度约 2 秒、无 `observation`、`orderId` 缺失，
   **不含**模块 4 那份 7 步 / 39 秒的冻结样例。
   ✅ **2026-09-28 当日已闭环**：集成组 `25b3ee3`「模块 4 思考链以
   `docs/mock/agent_schedule.json` 为唯一真源」把 `mock_data.AGENT_SCHEDULE`
   改为**读该 json 的 `data` 段**，响应体回到 **7 步**，json 成为唯一真源。
   本阶段记录的「mock 响应体与冻结样例不一致」不再是问题，见 `stage-08` 开头补记与硬卡点 #9。


## 6. 遗留问题与阻塞

| # | 问题 | 类型 | 影响 | 责任人 | 期望闭环时间 |
| --- | --- | --- | --- | --- | --- |
| 1 | `backend/.env` 无 LLM 凭据 | 阻塞 | 端点正常路径实测返回 503，屏 3 演示跑不起来 | Agent 组 + 徐川 | 立即 |
| 2 | 埋点存储方式未与集成组确认 | 技术债 | 重启清零 / 多 worker 各报一份 | 申云飞 | M3 末 |
| 3 | `core/response.py`、`core/security.py` 是模块 4 的临时实现 | 技术债 | 与集成组正式版可能语义不一致 | 申云飞 | M1 交付后替换 |
| 4 | `monitor` 端点**要求 JWT** | 待确认 | 若前端/评委不带 token 直接访问会得到 401。本模块按主文档 9.1「除登录外所有端点需认证」处理，已在 `docs/api.md` 模块 10 写明；若集成组希望它匿名可读，改一行 `Depends` 即可 | 集成组 + 前端 | M4 前 |

## 7. 未决事项进展

| # | 事项 | 本阶段是否已闭环 | 结论 / 当前卡点 |
| --- | --- | --- | --- |
| 1 | `lock_resources` 的 `user_id` 传递方式 | 是 | 已按阶段 4 的落点实现：JWT → 调用上下文 → Tool。本阶段实测 `user_id=1` 正确到达 `create_order` |
| — | `update_agent_trace(order_id, user_id, agent_trace)` | 是（接口已对齐） | 2026-09-27 与蔡玉礼对齐：仅关键字参数、无 `db` 参数、用 `user_id` 做归属校验、时序方案 (a)。**实现仍是桩**（`orderId` 恒为 None，走不到调用） |

## 8. 下一阶段入口条件确认

- [ ] 下一阶段（阶段 7）入口条件 ①「`AGENT-STAGE-06` 通过」—— 满足（有条件通过）
- [x] 「阶段 0 的种子数据已导入且构成符合 6.9」—— 满足。
      实测：场地 8 条、设备 15 条、预约 10 条；`space_resource` 8 行与 6.9 一致
- [ ] 「`smart_scheduler_test` 测试库可连（或备选方案已就位）」—— **未满足**。
      测试库访问被拒，退回 6.8 的备选方案（连开发库 + 只读），
      该方案的**强制手段**（拦截写库语句）尚未实现，属阶段 7 任务 7-2。
      **这是阶段 7 开工前必须先解决的一条**

**结论**：阶段 7 的入口条件有一条未满足，须先落地「只读开发库」的强制方案，
否则用例有污染种子数据的风险——而被污染的数据正是 `AGENT-S-01~05` 的断言基准。

## 9. 经验与可复用产出

1. **降级必须是 200，配置缺失才配 503，两者不能混。**
   三条降级路径（超时 / 未交方案 / 运行期异常）是**契约内的正常返回**，
   当成 500 会让前端不知道该渲染什么；而 `.env` 缺 LLM 凭据是**服务端配置问题**，
   伪装成 `200 + plan=null` 会让运维以为「模型不行」，实际是 key 没配。
   两者的分界线写进了 `docs/api.md` 的错误码表。

2. **`User` 身份的越权防线只有一个点：`get_current_user`。**
   请求体的 `extra="ignore"` 是**显式**写出来的（`schemas/agent.py`），
   虽然它就是 Pydantic v2 的默认值——因为它离「被改成 `extra="forbid"`」只有一步之遥，
   而那会让「忽略 `userId`」变成「422 拒绝」，用例红得莫名其妙。

3. **`register_exception_handlers` 要覆盖六类：`BusinessError`、`AuthError`（单列，
   HTTP 401）、`ApiError`、`RequestValidationError`、`StarletteHTTPException`，
   外加一个 `Exception` 兜底。**
   少了 `RequestValidationError` 那一层，422 会返回 FastAPI 自己的 `{"detail": [...]}`，
   前端就得写两套解析逻辑；少了 `Exception` 兜底，工具里的意外异常就是 500；
   少了 `AuthError` 那一层，它会落到父类 `BusinessError` 上、被接成 HTTP 200，
   前端拦截器不再跳登录（2026-09-28 裁定，见 §5 偏离 #4）。
   **（2026-09-28 更正**：本行原写「三类：`ApiError` / `RequestValidationError` /
   `StarletteHTTPException`」——那是当时的实际集合，漏了 `BusinessError`，也没有
   `AuthError`。现状见 `core/exceptions.py` 的六行处理器表。**）**

4. **埋点「成功」的口径要写进文档：`plan` 非空且未降级。**
   不取「HTTP 200 就算成功」——三条降级路径全是 200，算进去成功率接近 100%，
   而这个数字恰恰是给评委看「AI 在真实运行」的证据，虚高等于自己拆自己的台。

## 10. 确认

| 角色 | 姓名 | 确认日期 | 备注 |
| --- | --- | --- | --- |
| 负责人 | 徐川 | 2026-09-27 | |
| 集成组（`core/` 与入口的归属） | 申云飞 | | 见第 5 节偏离 #2 #3、第 6 节 #2 #3 |
