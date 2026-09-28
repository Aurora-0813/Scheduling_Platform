# 阶段 04 完成文档：Tool 层实现

| 项 | 内容 |
| --- | --- |
| 阶段 | 阶段 04 · Tool 层实现 |
| 对应文档 | `docs/spec/stage-04-tools.md` |
| 负责人 | 徐川 |
| 开始日期 | 2026-09-27 |
| 完成日期 | 2026-09-27 |
| 计划工时 | 2.0 人日 |
| **实际工时** | 1.5 人日 |
| 验收测试 | `AGENT-STAGE-04` |
| **验收结论** | **通过** —— `AGENT-STAGE-04` 步骤 ①②③④⑤ 已于 2026-09-28 全部执行完毕，原始输出见第 3 节；曾挂账的 ②⑤ 与 `AGENT-U-01/02` 由阶段 7 用例补齐后一并过（31 passed），详见 §3.6 |

## 1. 本阶段目标与达成情况

目标：把主文档 5.3 冻结的 4 个 Tool 实现出来，外加 1 个增补的 `submit_plan`，
并守住三条禁令（全异步、不碰库、不注册路由）。

已达成：5 个 Tool 全部落地、全部 `async def`、**无一引用 `AsyncSession`**、
**无一注册为 FastAPI 路由**；`query_devices` 的可用性过滤在 Tool 层实现，
真机上用种子数据里的两个「坏样本」验证了它确实在滤。

未达成：`AGENT-STAGE-04` 的验收步骤 ①（`pytest tests/test_agent_tools.py -q`）
与 ⑤（注入坏设备验过滤）依赖阶段 7 的用例文件，而本阶段按「先把代码生成完毕」
的顺序调整，测试用例**尚未编写**。为不让验收悬空，本阶段用**等价的直接调用**取得证据，
记录在第 3 节——**这不能替代阶段 7 的用例**，阶段 7 仍须补写 `AGENT-U-01/02/03`。

## 2. 完成判定逐项核对

> 阶段文档第 4 节「完成判定」逐条核对。

- [x] 5 个 Tool 全部实现且签名与冻结版一致 —— 证据：`app/agent/tools/*.py`；
      `query_spaces` / `query_devices` / `lock_resources` 三个签名与主文档 5.3 逐字相同；
      `generate_notification` 有一处**有意收紧**（`order_info: dict` → `OrderInfo` Pydantic 模型），
      理由写在 `generate_notification.py` 模块 docstring，函数内部立即 `model_dump()` 还原，
      **service 层看到的仍是冻结签名**
- [x] 工具参数校验失败返回业务错误而非抛异常 —— 证据：第 3 节 ① 的直接调用输出
- [x] `query_devices` 过滤 `device_status != 1` 与 `available_count <= 0` —— 证据：第 3 节 ②
- [x] `AGENT-U-01` / `AGENT-U-02` 通过 —— 证据：§3.6 的 `pytest tests/test_agent_tools.py`
      （31 passed）；用例文件属阶段 7 任务 7-3，已于阶段 7 补齐
- [x] 全部 Tool 为 `async def` —— 证据：第 3 节 ③ 的 `grep`
- [x] 无一直接使用 `AsyncSession` —— 证据：第 3 节 ③ 的 `grep`（`app/agent/` 下仅注释提及）
- [x] 未注册任何路由 —— 证据：第 3 节 ③ 的 `grep`；`APIRouter` 只出现在 `app/api/` 下

未通过项说明：

| 条目 | 状态 | 原因 | 处置计划 | 责任人 |
| --- | --- | --- | --- | --- |
| 验收步骤 ①⑤（跑 `test_agent_tools.py`） | **已闭环（2026-09-28）** | 阶段 7 用例尚未编写 | 阶段 7 任务 7-3 已补写 `AGENT-U-01/02/03`，断言口径沿用第 3 节；步骤 ⑤ 的注入检查见 §3.6 | 徐川 |

## 3. 验收测试执行记录

| 项 | 内容 |
| --- | --- |
| 测试编号 | `AGENT-STAGE-04`（步骤 ①⑤ 以等价手段执行） |
| 执行环境 | Windows 11；conda 环境 `smart_dev`（Python 3.11.9）；SSH 隧道 3308 通；开发库 `smart_scheduler_dev` |
| 执行命令 | 见下方各小节的命令 |
| 执行时间 | 2026-09-27 18:5x |

### ① `query_spaces` 参数异常 → 业务错误而非异常

```python
from app.agent.tools import query_spaces
await query_spaces.coroutine(capacity=0,  space_type=2, start_time="2026-11-06 16:00:00", end_time="2026-11-06 14:00:00")
await query_spaces.coroutine(capacity=40, space_type=2, start_time="2026-11-06 16:00:00", end_time="2026-11-06 14:00:00")
```

```text
capacity=0   → {'ok': False, 'reason': 'capacity 必须为正整数，收到 0。请按用户口述的实际人数重传。', 'count': 0, 'spaces': []}
时段倒置     → {'ok': False, 'reason': '结束时间(2026-11-06 14:00:00)不晚于开始时间(2026-11-06 16:00:00)，时段倒置。请修正后重试。', 'count': 0, 'spaces': []}
```

两例均**返回 dict、未抛异常**。另：`QuerySpacesArgs` 的 `capacity: int = Field(..., gt=0)`
在 Pydantic 层还会先拦一道，构成两层防护。

### ② `query_devices` 过滤可用性（含种子数据里的两个坏样本）

```python
await query_devices.coroutine(device_type="无人机")
await query_devices.coroutine(device_type="直播设备")
```

```text
无人机   → ids [12]，共 1 台。种子数据里 id=13 无人机02 的 deviceStatus=2（损坏）→ 未出现
直播设备 → ids [14]，共 1 台。种子数据里 id=15 直播设备02 的 availableCount=0      → 未出现
```

**过滤确在生效，而不是「数据本来就没有」**：`device_service.query_devices` 桩返回该类型
**全部**设备（id 12、13 都在结果里），过滤只发生在 Tool 层。
这也是阶段 4 §3.2 把过滤有意放在 Tool 而非 service 的原因。

### ③ 三条禁令的 `grep` 检查

```bash
grep -rn "@router\|include_router\|APIRouter" app/agent/          # → 无匹配
grep -rn "AsyncSession" app/agent/                                # → 仅 3 处注释，无代码引用
grep -n "^async def " app/agent/tools/*.py                        # → 5 个 Tool 全部 async
```

```text
app/agent/tools/query_spaces.py:37:async def query_spaces(capacity: int, space_type: int, start_time: str, end_time: str) -> dict:
app/agent/tools/query_devices.py:55:async def query_devices(device_type: str) -> dict:
app/agent/tools/lock_resources.py:72:async def lock_resources(
app/agent/tools/generate_notification.py:49:async def generate_notification(order_info: OrderInfo) -> dict:
app/agent/tools/submit_plan.py:73:async def submit_plan(plan: PlanPayload, backup_plan: PlanPayload | None = None, reason: str = "") -> dict:
```

`APIRouter` 的全部出现位置（均在 `app/api/` 下，与 `app/agent/` 无关）：

```text
app/api/v1/agent.py:35:   router = APIRouter(tags=["Agent"])
app/api/v1/monitor.py:33: router = APIRouter(tags=["Monitor"])
app/api/v1/mock.py:45:    router = APIRouter(tags=["Mock"])
app/api/v1/router.py:29:  api_router = APIRouter(prefix="/api/v1")
```

**结论**：三条禁令均未破。步骤 ④「检查是否注册了路由」由此通过。

### ⑥ 2026-09-28 收口复核：五项检查一次性重跑

阶段 7 的用例写好之后，本节把 `AGENT-STAGE-04` 的五项检查**从头重跑了一遍**，
不再用「等价手段」。执行环境同上（conda `smart_dev` / 离线 / `--no-cov`）。

```bash
# ⑤-pytest：Tool 层用例
pytest tests/test_agent_tools.py -p no:cacheprovider --no-cov

# ③-禁令三条
grep -rn "@router\|include_router\|APIRouter" app/agent/
grep -rn "AsyncSession" app/agent/
grep -c "^async def " app/agent/tools/*.py
```

```text
31 passed in 12.49s

@router / APIRouter      → 无任何匹配（退出码 1）
AsyncSession             → 3 处，全部是**文档字符串/注释**，无一行代码引用：
  tools/lock_resources.py:14   （解释「正因为不该用，所以这里没有事务代码」）
  tools/_common.py:3           （纯函数，不碰库）
  tools/__init__.py:6          （禁令原文）
  ——另有 3 个 .pyc 命中，是上面三段注释的编译产物，不是新引用
async def 计数（每文件）: query_spaces=1  query_devices=1  lock_resources=1
                          generate_notification=1  submit_plan=1  （_common/__init__=0）

注入检查（4 条构造数据 → 只留健康样本）：
  id=901 deviceStatus=2 availableCount=1  注入-损坏    → 被滤（status）
  id=902 deviceStatus=1 availableCount=0  注入-零库存  → 被滤（库存）
  id=903 deviceStatus=2 availableCount=0  注入-又坏又空 → 被滤（两道都中）
  id=904 deviceStatus=1 availableCount=2  注入-健康    → ✅ 唯一存活
  → ok=True count=1 ids=[904]；service 只被调 1 次（过滤确实在 Tool 层）
负控（只喂 901/902，该类型一台都不可借）：
  → ok=False；reason=「『音响』共 2 台，但当前**没有一台可借用**（损坏或库存为 0）。
     建议改用替代设备类型，或与用户确认是否接受替代。」
```

**为什么要注入**：种子数据里 id=13 / id=15 本来就带坏值，只看「结果里没有它们」
分不清是「Tool 真在滤」还是「数据本来就没有」。注入之后 4 条走同一条路径，
留下的那条是唯一健康样本（id=904），过滤生效才解释得通。
负控再证一遍**两道过滤各自独立**（只剩坏样本时给的是专属话术，而不是静默返回空列表——
后者会让模型以为「这个类型不存在」，转而去推荐别的设备类型）。

五项结论：**① 通过（31 passed）② 通过 ③ 通过（三条禁令均未破）④ 通过 ⑤ 通过**。

## 4. 交付物清单

| 交付物 | 计划路径 | 实际路径 | 状态 |
| --- | --- | --- | --- |
| Tool 1 场地查询 | `app/agent/tools/query_spaces.py` | 同左 | 已交付 |
| Tool 2 设备查询 | `app/agent/tools/query_devices.py` | 同左 | 已交付 |
| Tool 3 资源锁定 | `app/agent/tools/lock_resources.py` | 同左 | 已交付 |
| Tool 4 通知文案 | `app/agent/tools/generate_notification.py` | 同左 | 已交付 |
| Tool 5 方案提交（增补） | —— | `app/agent/tools/submit_plan.py` | 已交付（增补项，见第 5 节偏离 #3） |
| 共享校验helper | —— | `app/agent/tools/_common.py` | 已交付 |
| 调用上下文 | —— | `app/agent/context.py` | 已交付 |
| Tool 注册表 | —— | `app/agent/tools/__init__.py`（`AGENT_TOOLS`） | 已交付 |

## 5. 偏离计划之处

| # | 计划 | 实际 | 原因 | 影响 | 是否需要同步团队 |
| --- | --- | --- | --- | --- | --- |
| 1 | 本阶段跑 `test_agent_tools.py` | 未跑，用例未编写 | 按「先把全部代码生成完毕再补测试」的排期调整 | 验收步骤 ①⑤ 以等价的直接调用取证；阶段 7 必须补 `AGENT-U-01/02/03`，否则本阶段证据链不完整 | 是（记入阶段 7 待办） |
| 2 | 增补的 `submit_plan` | 已实现并接入 Agent | 主文档 5.3 的 Tool 清单用的是「**包括**」而非「仅限」，故增补合法 | 属**建议**而非既定事项，需在 M3 评审同步团队，避免被认为擅自扩大接口范围 | 是 |
| 3 | `generate_notification(order_info: dict)` | 参数名不变、类型收紧为 `OrderInfo` | `dict` 的 JSON Schema 无字段提示，模型猜错键名会**静默**产出「所选场地」这类兜底文案 | 冻结签名对 service 层不变；被收紧的只是 Agent↔Tool 边界 | 是（告知黄嵩） |

## 6. 遗留问题与阻塞

| # | 问题 | 类型 | 影响 | 责任人 | 期望闭环时间 |
| --- | --- | --- | --- | --- | --- |
| 1 | `create_order` 仍是**只读桩**，`orderId` 恒为 None | 阻塞 | 阶段 7 的 `AGENT-C-01/02`（并发与库存扣减）无法验证；`agent_trace` 补写链路只能走到「跳过」分支 | 蔡玉礼（模块 3） | M3 末 |
| 2 | `notify_service` 的「延期致歉」在 6.3 字典内无 INT 值（未决 #6） | 待确认 | 该类型的通知文案生成会返回 `ok=False` | 黄嵩 + 集成组 | M3 末 |

## 7. 未决事项进展

| # | 事项 | 本阶段是否已闭环 | 结论 / 当前卡点 |
| --- | --- | --- | --- |
| 1 | `lock_resources` 的 `user_id` 传递方式 | **是**（2026-09-27 与蔡玉礼对齐） | 冻结签名不加 `user_id`；身份由 API 层从 JWT 解出后经 `app/agent/context.py` 的调用上下文注入 Tool。见 `docs/spec/contract-alignment.md` 第 1 条 |
| 2 | `TraceStep` 字段冻结待前端回执 | 否 | 字段已冻结并实现，**仍缺前端书面回执**（阶段 2 遗留） |
| 4 | `query_spaces`/`query_devices` 真实 service 签名 | 否 | 阶段 3 桩已可用；替换后需核对签名 |
| 6 | `notify_type` 映射 | 否 | 见第 6 节 #2 |

## 8. 下一阶段入口条件确认

- [x] `AGENT-STAGE-03` 的前置（`app/core/` 配置层与 `AsyncSession` 工厂）—— 满足了；
      `backend/app/core/config.py` 与 `database.py` 已就位（本阶段实测可连库、种子数据可读）
- [x] `TraceStep` 已冻结 —— 满足（仍缺前端回执，不阻塞开工）
- [x] 5 个 Tool 在 Agent 下可被真实调用 —— 满足，证据见 `stage-05-completion.md` 第 3 节

## 9. 经验与可复用产出

1. **`ContextVar` 在 LangGraph 工具里是单向的，这是实测过的坑。**
   最初把「模型交出的方案」和「落库的订单 ID」放进 `ContextVar` 由 Tool 写、调用方读——
   **静默失效**：LangGraph 的 `ToolNode` 用 `asyncio.gather()` 并发跑工具，
   `gather` 走 `ensure_future` → 创建 Task → **拷贝当前 context**，
   子任务里的 `set()` 不会回写父 context，读出来恒为 `None`。
   更麻烦的是它在假 LLM 下可能偶然通过，属于最难查的一类 bug。
   现改为**只从 LangGraph 的 `messages` 流里提取**（`AIMessage.tool_calls[].args` 与
   `ToolMessage.content`），提取点在 `app/agent/chains/builder.py`，
   坑的完整说明写在 `app/agent/context.py` 的模块 docstring。**建议写进流程文档。**

2. **`ToolMessage.content` 是字符串不是 dict。**
   框架把 Tool 的 dict 返回值序列化后才塞进 `content`，且不同版本可能用
   `json.dumps`（双引号）或 `str()`（单引号）。解析必须两种都试，
   实现在 `app/agent/chains/trace.py::parse_observation`。

3. **过滤要放在能被证伪的那一层。**
   把设备可用性过滤下沉到 service 会让 `AGENT-U-02` 变成假绿
   （结果里永远没有坏设备，分不清是滤掉了还是本来没有）。
   放在 Tool 层，`device_service` 桩返回全量数据，用例才有**独立见证者**。

## 10. 确认

| 角色 | 姓名 | 确认日期 | 备注 |
| --- | --- | --- | --- |
| 负责人 | 徐川 | 2026-09-27 | |
| 模块 3（`create_order` 时序与并发） | 蔡玉礼 | | 见第 6 节 #1 |
| 模块 7（`notify_type` 映射） | 黄嵩 | | 见第 6 节 #2 |
