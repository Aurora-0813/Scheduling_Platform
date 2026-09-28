# 阶段 02 完成文档：契约冻结

| 项 | 内容 |
| --- | --- |
| 阶段 | 阶段 2 · 契约冻结 |
| 对应文档 | `docs/spec/stage-02-contract.md` |
| 负责人 | 徐川 |
| 开始日期 | 2026-09-24 |
| 完成日期 | 2026-09-24 |
| 计划工时 | 1 人日 |
| **实际工时** | 0.6 人日 |
| 验收测试 | `AGENT-STAGE-02` |
| **验收结论** | **有条件通过**（技术项全过，前端书面回执未取得） |

## 1. 本阶段目标与达成情况

目标是把接口契约钉死，让前端、小程序、集成组照此对接口，不再改。

**技术交付已完成**：`backend/app/schemas/agent.py` 已提交（`1cd5ce7`），`docs/api.md` 已同步模块 4 的请求/响应/字段表。**唯一未闭环的是"前端书面回执"**——这不是技术动作，是流程动作，且**必须有真实回执才算数，不能由我代签**。

## 2. 完成判定逐项核对

- [x] `ScheduleRequest` 已定义，**无 `userId` 字段** —— 证据：`schemas/agent.py`
- [x] `TraceStep` 六个字段（`step`/`result`/`timestamp`/`thought`/`action`/`actionInput`/`observation`）与主文档 4.4 表格逐字对齐
- [x] `ScheduleData` 含 `plan`/`backupPlan`/`trace`/`needConfirm` 四字段
- [x] 字段名为 camelCase 且**不依赖 `alias_generator`** —— 见第 5 节偏离说明
- [x] `docs/api.md` 已写入模块 4 章节（正常示例 + 三条降级路径 + 错误码 + 禁止事项）
- [ ] **前端书面回执** —— ⏳ 未取得，见第 6 节
- [x] 本阶段未写入任何业务逻辑

## 3. 验收测试执行记录

| 项 | 内容 |
| --- | --- |
| 测试编号 | `AGENT-STAGE-02` |
| 执行环境 | `F:/conda_envs/envs_dirs/smart_dev/python.exe` |
| 执行时间 | 2026-09-24 |

**原始输出**

```
$ python -c "from app.schemas.agent import ScheduleRequest, ScheduleData, TraceStep, Plan; print('schemas import OK'); print(list(ScheduleRequest.model_fields)); print(list(TraceStep.model_fields))"
schemas import OK
['text', 'imageContext']
['step', 'result', 'timestamp', 'thought', 'action', 'actionInput', 'observation']
```

**结论**：**技术项通过**。`ScheduleRequest` 只有 `text` 与 `imageContext` 两个字段，**确认无 `userId`**——这是主文档 5.1、9.1 的红线（身份必须从 JWT 解析，不得从请求体取）。

整体验收结论为**有条件通过**：出参形状已冻结并落档，但按阶段 2 的门槛要求，缺少前端书面回执不能判"通过"。

## 4. 交付物清单

| 交付物 | 计划路径 | 实际路径 | 状态 |
| --- | --- | --- | --- |
| 契约定义 | `backend/app/schemas/agent.py` | 同 | 已交付（`1cd5ce7`） |
| 接口文档 | `docs/api.md` 模块 4 章节 | 同 | 已交付 |
| 前端回执 | 项目群 / `docs/api.md` 附注 | 无 | ⏳ 未取得 |

## 5. 偏离计划之处

| # | 计划 | 实际 | 原因 | 影响 | 是否需要同步团队 |
| --- | --- | --- | --- | --- | --- |
| 1 | 用 `alias_generator=to_camel` + `populate_by_name` 实现 camelCase | 直接以 camelCase 命名 Python 字段（`spaceId`、`imageContext`） | `alias_generator` 方案要求**每一处序列化都必须记得传 `by_alias=True`**；漏一处就静默回退成 snake_case，前端拿到 `space_id` 而报错信息里看不出原因。这是典型的"能跑但对不上"的坑 | 代码不符合 PEP 8 命名习惯；换来的是**不可能漏** | 是（需在前端联调前说明该命名是刻意为之，不是笔误） |
| 2 | 计划工时 1 人日 | 实际约 0.6 人日 | 契约本身不复杂，复杂的是"哪些字段不该有" | 无 | 否 |
| 3 | `text` 为空或超长返回 HTTP 422 | 改为 **HTTP 200 + `code=400`**，rebase 到 `origin/main`（`9f30d3a`，2026-09-28）后又改为 **HTTP 400 + `code=40001`** | **契约冻结后因跨模块统一响应体改口径，共改了两次**。第一次：`RequestValidationError` 的全局处理器全应用只能有一份（FastAPI 的 `add_exception_handler` 后注册者覆盖先注册者），模块 4 自建处理器把状态码压成 200 + `code=400`。**第二次（当前口径）**：合并时该处理器取正式版 `core/response.py`，正式版口径是 **HTTP 400 + `code=40001`**（`ErrorCode.PARAM_INVALID`），与模块 2 的 `tests/test_image_api.py::test_missing_file_returns_friendly_error`（断言 `body["code"] == 40001`）一致。因此「模块 1/2 的用例断言 `code == 400`」这句在合并后**不再成立**——原始表述保留在此仅作口径沿革记录 | **仅状态码与业务码的表述变化**：字段本身、约束范围（`min_length=1` / `max_length=1024`）、以及「不空跑模型」的行为三次均未变。`data.errors` 仍承载校验明细。已同步 `docs/api.md` 错误码表与本节开头说明 | 是（前端若已按 422 **或** 200+`code=400` 写过分支判断需改；**属实现侧口径，非字段级变更**） |

第 1 条属于**主动选择的技术债**：用可读性换序列化安全。在团队协作且前端不熟悉 pydantic 的前提下，这个取舍值得。**若评审认为 Python 字段名必须 snake_case，则改回 `alias_generator` 方案，但必须在 `docs/api.md` 中明确标注所有序列化点须 `by_alias=True`。**

第 3 条的定性：**不是契约内容变更，是错误码表述与全局处理器归属的冲突**。字段级契约（有哪些字段、必填与否、约束范围）自冻结后确实未再变更，`docs/api.md` 章首那句话仍然成立。这里让出的只有「用哪个状态码表达参数校验失败」。

## 6. 遗留问题与阻塞

| # | 问题 | 类型 | 影响 | 责任人 | 期望闭环时间 |
| --- | --- | --- | --- | --- | --- |
| 1 | **前端书面回执未取得** | 流程阻塞 | 语义歧义会在联调期暴露，届时改动成本是现在的数倍；模块 10 监控页也无法定稿 | 前端负责人 | 阶段 6 接口实现前 |
| 2 | `needConfirm` 恒为 `true` 的语义未与前端确认 | 契约歧义 | 前端不知何时展示确认弹窗 | 前端负责人 | 同上 |
| 3 | `trace` 是否对前端全量展示未定 | 契约歧义 | 监控页数据量可能过大 | 前端负责人 | 阶段 6 前 |

**第 1 条是本阶段唯一的门槛项缺口。** 契约冻结的价值全在"不再改"上，没有回执就等于没冻。

## 7. 未决事项进展

| # | 事项 | 本阶段是否已闭环 | 结论 / 当前卡点 |
| --- | --- | --- | --- |
| 1 | `trace` 字段是否对前端开放 | 部分 | 已在 `docs/api.md` 定义全量返回；是否裁剪待前端反馈 |
| 2 | 降级路径的 HTTP 状态码 | 是 | 定为 200 + `plan=null`，不用 4xx/5xx（前端按业务码分支更简单） |

## 8. 下一阶段入口条件确认

- [x] `AGENT-STAGE-01` 通过
- [ ] `AGENT-STAGE-02` 通过 —— ⏳ 有条件通过，待前端回执
- [ ] 桩函数可调用 —— ⛔ **未满足**：`backend/app/core/`（config、AsyncSession 工厂）为空，`app/models`、`app/api` 亦为空，M1/M2 未交付

**阶段 3 无法启动**，原因不在本模块。详见 `docs/spec/stage-03-*.md` 的入口条件。

## 9. 经验与可复用产出

- **契约阶段最该问的不是"要哪些字段"，而是"哪些字段绝不能有"。** `userId` 不出现，比 `spaceId` 出现更有价值——前者是安全红线，后者只是便利性。
- 序列化 alias 是隐性契约：**它不在类型里，只在调用点**。凡是"必须记得每次都传某个参数"的设计，都该默认会被漏掉。
- 阶段 2 交付的是**文档 + schema**，这类产物没有测试能自动验证"前端已认可"，只能靠回执。**流程门槛不能靠代码测试代替。**

## 10. 确认

| 角色 | 姓名 | 确认日期 | 备注 |
| --- | --- | --- | --- |
| 负责人 | 徐川 | 2026-09-24 | |
| 前端 | 待定 | **待签** | 本阶段门槛项 |
| 集成组 | 申云飞 | 待确认 | 模块 10 接口 |
