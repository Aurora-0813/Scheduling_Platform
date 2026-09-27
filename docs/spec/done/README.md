# 阶段完成文档归档

> ✅ **本目录已入库**（2026-09-27 起）。`.gitignore` 以 `docs/spec/*` + `!docs/spec/done/`
> 放行本目录下的完成文档；计划书、阶段任务书与模板**仍仅本地保留**。
>
> 该放行是 `done/stage-10-completion.md` 第 5 节**方案 B 的提前落地，项目群裁定尚未追认**——
> 若裁定推翻，回滚 `.gitignore` 那两行即可。
>
> 注意 `docs/spec/*` 的写法不能写成 `docs/spec/`：父目录被排除后 git 不会进入该目录，
> `!` 白名单会失效。原因已写在 `.gitignore` 原位注释里。

每个阶段验收测试通过后，把 `docs/spec/templates/stage-completion-template.md`
复制到本目录，命名为 `stage-NN-completion.md`（NN 与阶段号一致，如 `stage-00-completion.md`），**当天填完**。

- 补写的完成文档没有证据价值——证据要趁热留
- 阶段 7 的完成文档**必须附覆盖率报告的完整原始输出**，不接受"已通过"三个字
- 偏离计划之处必须如实写：工时超了、范围砍了、验收标准被迫放宽，都要记

完成后回到 `docs/spec/README.md` 第 5 节更新阶段状态表，**并把下表同步一遍**（见下方说明）。

---

## 当前状态（团队可见副本）

> 本表是 `docs/spec/README.md` 第 5 节的**副本**。那份文件随整个 `docs/spec/`
> 一起被 `.gitignore` 排除（本地保留），团队在仓库里看不到，所以在这里放一份。
> **改一处必须改两处**：阶段状态变动时，先改本地那份（它是工作稿），再同步到本表。

| 阶段 | 状态 | 完成文档 | 备注 |
| --- | --- | --- | --- |
| 0 前置条件核对 | **部分解除** | [stage-00](stage-00-completion.md) | 原阻塞三条：种子数据**已导入**（场地 8 / 设备 15 / 预约 10，与 6.9 一致）；`backend/.env` **已建、LLM 三项已填且实测可用**（`qwen-plus` + DashScope 兼容模式，2026-09-27 真实调用跑通）；DDL 未执行（表已存在，疑由 M1 建表脚本带入，**待集成组确认**） |
| 1 环境与骨架 | **通过** | [stage-01](stage-01-completion.md) | 依赖装齐、锁文件生成（此前为空文件） |
| 2 契约冻结 | **有条件通过** | [stage-02](stage-02-completion.md) | schema 与 `docs/api.md` 已交付；**缺前端书面回执** |
| 3 依赖就绪度 | **通过** | [stage-03](stage-03-completion.md) | M1 的 `config.py` + `database.py` 已就位，据此产出 service 桩。注：集成组正式版就位前，模块 4 在阶段 6 自行补出了 `core/response.py`、`core/security.py`，见阶段 6 偏离 #2 |
| 4 Tool 层 | **有条件通过** | [stage-04](stage-04-completion.md) | 5 个 Tool 全部落地、三条禁令未破；验收步骤 ①⑤ 依赖阶段 7 用例，改以等价手段取证 |
| 5 Prompt 与组装 | **不通过** | [stage-05](stage-05-completion.md) | 真实 API 冒烟**已跑通**（`qwen-plus`，4 步 trace / 18.3 秒 / `success=true`），四条通过标准达成 3 条。**差的一条「设备降级为单投影」前提不成立**——`device_resource` 无价格字段，「预算与设备冲突」算不出来，模型交出双投影并说明「无需降级」，判断自洽。两次冒烟原始输出见 stage-05 §3.1 / §3.2。另暴露：「下周三」被算成 10-04（应 09-30）；真实路径未调 `lock_resources` |
| 6 API 层 | **有条件通过** | [stage-06](stage-06-completion.md) | 六步验收全部执行且符合标准；埋点为进程内计数、正常路径实测在注入假模型下完成 |
| 7 测试 | **有条件通过** | [stage-07](stage-07-completion.md) | 82 例通过 + 2 例 `xfail(strict)`；`app/agent` 覆盖率 **92.29%**（阈值 80% 已入 `pytest.ini`）。**`AGENT-C-01/02` 未通过**——模块 3 的 `create_order` 仍是只读桩，标 `xfail(strict)` 并登记在案，不当作通过。另两条限制：`AGENT-S-01~05` 只验了透传与形状（决策质量需真实 LLM，`.env` 三项为空）；`db_session` 连的是只读开发库而非测试库 |
| 8 联调准备 | **不通过** | [stage-08](stage-08-completion.md) | mock 数据与路由已交付且实测；**交接清单五项回执一项都没有**（需真实沟通，非代码可替代） |
| 9 提交与合并 | 未开始 | — | 入口条件未满足（阶段 8 不通过），但验收内容（`.env` 不入库、CI 绿灯、tag）与之互不阻塞，可并行 |
| 10 交接与后续 | 未开始 | — | |

状态取值：未开始 / 进行中 / 通过 / 有条件通过 / 阻塞（阻塞须注明 blockers 与责任人）。

### 当前硬卡点（按紧急度）

| # | 卡点 | 影响 | 责任人 |
| --- | --- | --- | --- |
| 1 | **场景 A 的验收标准「设备降级为单投影」前提不成立**（`device_resource` 无价格字段，设备不计费，「预算与设备冲突」没有可计算依据） | 阶段 5 与阶段 7 的 `AGENT-S-01` 挂在一个**不可达**的标准上。若为让它变绿而改 Prompt「教」模型降级，等于凭空造价格规则，违反 Prompt 自己写的「绝不编造价格」。需裁定：A 改标准措辞（保住场地+说明为何不需降级）／B 补设备单价口径（集成组数据模型）／C 换一条前提成立的降级用例。本模块倾向 A + C | 集成组（数据模型 / 总预算口径）+ 徐川（标准措辞） |
| 2 | 阶段 8 五项交接回执全空 | 联调当天才会暴露口径不一致，而这正是阶段 8 存在的意义 | 徐川（发起）+ 蔡玉礼 / 杨睿坤 / 黄嵩 / 前端 / 申云飞（回执） |
| 3 | 模块 3 的 `create_order` 仍是只读桩（`orderId` 恒为 `None`） | 并发与库存扣减（`AGENT-C-01/02`）无法验证——**阶段 7 因此未完全达标**；`agent_trace` 补写链路只能走到「跳过」分支 | 蔡玉礼 |
| 4 | `smart_scheduler_test` 访问被拒 | `db_session` 只能连只读开发库（强制手段已实现：`_db_readonly_guard` 前置拒绝全部写语句）。**但它同时会把并发用例要验的真实写入一起打死**——测试库权限到位后须对本用例收窄拦截，否则 `AGENT-C-01/02` 仍过不了 | 申云飞 |

原「阶段 3 唯一硬卡点」（`backend/app/core/` 为空）**已解除**：`config.py` 与 `database.py` 已就位，阶段 3 据此通过。

### LLM 配置 baseline（模块 4 公布 · 2026-09-27）

模块 8 索要的 baseline，可直接照抄。**Key 各人各把，只放本地 `backend/.env`，不入库。**

| 项 | 取值 | 说明 |
| --- | --- | --- |
| `LLM_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | DashScope 的 OpenAI 兼容端点，公开 URL，不含凭据 |
| `LLM_MODEL_NAME` | `qwen-plus` | 全组统一取值。**模型必须支持 Function Calling** |
| `LLM_API_KEY` | 各自申请（DashScope） | 真实值只在本地 `.env`；仓库与文档一律占位 |
| `LLM_TEMPERATURE` | `0.0`（`settings` 默认） | 调度决策要可复现；调高会让同一需求两次给出不同方案 |
| `LLM_MAX_RETRIES` | `1`（`settings` 默认） | 外层已有 `AGENT_TIMEOUT` 兜底，重试不宜多 |

变量名三项已与模块 8 对齐。注意 `backend/.env` 由 `pydantic-settings` 读入，
**不是**导出到进程环境变量——直接用 `os.getenv("LLM_MODEL_NAME")` 会拿到 `None`。

**反例（已实测）：`qwen-math-turbo` 不可用。** 它是数学专用模型，无 Function Calling
能力，且输入上限 3072 token；本模块的 Prompt + 工具 schema 约 6968 字符，
实测直接 `400 InternalError.Algo.InvalidParameter`。换 `qwen-plus` 后跑通。
（2026-09-27，证据见 [stage-05](stage-05-completion.md) §3.1 / §3.2：4 步 trace、
18.3 秒、`success=true`。）

**未经实测、待模块 8 验证**：`with_structured_output` 在 langchain-openai 1.5.0 的
`method` 默认值是 `json_schema`（签名已确认），DashScope 是否接受该格式我方没有走过
这条路——本模块用的是 `create_agent` + Tool，不经过 `with_structured_output`。
