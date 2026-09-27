# 测试用例文档

> 依据《项目文档.md》10.1~10.3（测试规范）、6.8（测试库）、6.9（种子数据）、11.1~11.2。
> 接口变更或种子数据变更时，本文件须同步更新。

---

## 一、环境基线

> 用途：M4 联调时他人照此复现。**本小节必须与实际执行结果一致，未核对项如实标注。**

| 项 | 值 | 状态 |
| --- | --- | --- |
| 核对日期 | 2026-09-27（2026-09-24 首核） | ✅ 已核对 |
| Python 版本 | 3.11.9 | ✅ 已核对 |
| conda 环境 | `smart_dev`（`F:\conda_envs\envs_dirs\smart_dev`） | ✅ 已核对 |
| 依赖安装方式 | `pip install -r requirements.txt`（版本全量 `==` 锁定） | ✅ 已执行 |
| 关键版本 | langchain 1.3.11 / langchain-openai 1.5.0 / langchain-classic 1.0.0 / langchain-core 1.6.4 / langgraph 1.2.12 | ✅ 已核对 |
| 测试工具版本 | pytest 9.1.1 / pytest-asyncio 1.4.0 / pytest-cov 7.1.0 | ✅ 已核对 |
| 数据库驱动 | asyncmy 0.2.10 | ✅ 已安装 |
| 认证依赖 | passlib 1.7.4 + bcrypt 4.0.1（哈希自检 `verify: True`） | ✅ 已核对 |
| 锁文件 | `backend/requirements.lock`（68 行，`pip freeze` 生成） | ✅ 已生成 |
| `.env` | 已存在（含 `DB_*` / `JWT_SECRET_KEY`）；**LLM 三项已填且实测可用**（`qwen-plus` + DashScope 兼容模式，2026-09-27 真实调用跑通） | ✅ 已核对 |
| 数据库连通 | SSH 隧道 `localhost:3308` → 远程 3307，开发库可读 | ✅ 已核对 |
| DDL 版本 | 未与 6.7 逐条对比 | ⛔ 未闭环：需集成组确认 |
| 种子数据条数 | 场地 8 / 设备 15 / 预约 10 | ✅ 已核对（开发库实测） |
| 测试库 | `smart_scheduler_test` | ⛔ 无权访问（错误码 1044） |

**仍未闭环的两项**：DDL 版本需集成组确认；测试库权限缺失（见第五节）。

`.env` 的 **LLM 三项已不再是缺口**：2026-09-27 用 `qwen-plus` 真实调用跑通了一次
场景 A（4 步 trace / 18.3 秒 / `success=true`，原始输出见 `stage-05-completion.md` §3.2）。
决策质量那一层因此有了第一条真实证据，也随之暴露了一个**标准层面**的问题：
`AGENT-S-01` 的预期结果「设备降级为单投影」在数据模型里**算不出来**
（`device_resource` 无价格字段），详见 3.2 末尾。

> **该标准已于 2026-09-27 经项目群裁定为 A + C 并落地**：A 把 `AGENT-S-01` 的预期改为
> 「保住场地 + 说明为何不需降级」；C 新增 `AGENT-S-06`（要两台直播设备、库里只有一台可借）
> 承接「真的降级」那半边，其前提由 `test_seed_supports_the_degradation_case` 对着真库验。
> 选项 B（补设备单价口径）未采纳。本节 §3.2 保留裁定前的推理原文作为留痕。

### 运行夹具的两个环境要点（**照抄，否则用例会偶发失败**）

1. **全部异步用例必须跑在同一个事件循环里**（`pytest.ini` 的
   `asyncio_default_test_loop_scope = session`）。`asyncmy` 的连接与创建它的循环绑定，
   而连接池是进程级的；每条用例换循环时，池里旧连接指向已关闭的 loop，表现为
   `asyncmy.errors.InternalError: network operation failed` 包着
   `AttributeError: 'NoneType' object has no attribute 'send'`。
   症状是**只有复用池化连接的用例偶发失败**，极易被误判成「数据库不稳定」。
2. **跑测试请用 conda 环境 `smart_dev` 的解释器**。裸 `python` 是 miniconda base（3.13），
   缺 `asyncmy` 与整个 langchain 栈：

```bash
cd backend && PYTHONIOENCODING=utf-8 "F:/conda_envs/envs_dirs/smart_dev/python.exe" -m pytest -q
```

### 运行环境注意

终端为 GBK 码页时，脚本输出的中文会显示为乱码（内容无误）。跑中文输出脚本时加编码声明：

```bash
PYTHONIOENCODING=utf-8 python tests/smoke_fake_llm.py
```

---

## 二、假 LLM 夹具结论（核心调度 Agent 模块）

**结论：`FakeMessagesListChatModel` 与 `GenericFakeChatModel` 均不可用，须使用自实现 `bind_tools` 的 `StubChatModel`。**

### 验证方法

脚本：`backend/tests/smoke_fake_llm.py`

```bash
cd backend && python tests/smoke_fake_llm.py
```

原理：`create_agent` 内部会调用 `model.bind_tools(tools)`。基类 `BaseChatModel.bind_tools` 的默认实现直接抛 `NotImplementedError`，凡是没覆写该方法的假模型类，挂到 `create_agent` 上都会失败。

### 实测结果（langchain-core 1.6.4）

| 夹具 | 结果 | 说明 |
| --- | --- | --- |
| `FakeMessagesListChatModel` | ❌ FAIL | `NotImplementedError: bind_tools` |
| `GenericFakeChatModel` | ❌ FAIL | `NotImplementedError: bind_tools` |
| `StubChatModel`（自实现 `bind_tools`） | ✅ PASS | 绑定成功，4 条消息，1 条 `ToolMessage` |

**注意**：《核心调度Agent开发流程.md》阶段 7.1 预警了 `FakeMessagesListChatModel` 不可用，但推荐的替代方案 `GenericFakeChatModel` **同样不可用**。该处文档已过时，需按本结论修正。

### 后续用例的夹具方案

`tests/conftest.py` 里的实际夹具叫 **`ScriptedChatModel`**（工厂夹具名 `scripted`）。
它就是上文 `StubChatModel` 的定稿版，三处与冒烟脚本里的最小版不同：

| 差异 | 为什么 |
| --- | --- |
| 多了 `delay: float`，`_agenerate` 里 `await asyncio.sleep(delay)` | `AGENT-E-02`（超时）要有一个「调用开始后不返回」的模型，不 sleep 就测不出 `wait_for` 分支 |
| 同时实现 `_generate` 与 `_agenerate` | `create_agent` 走异步路径；只实现同步版会拿到 `NotImplementedError` |
| 响应耗尽后**重复最后一条**（`min(cursor, len-1)`） | 用例少写一条响应时不该拿到 `IndexError`；同时使「末尾必须是纯文本 AIMessage」成为一条**显式约定**（见 `test_agent_schedule.py` 模块 docstring） |

```python
class ScriptedChatModel(BaseChatModel):
    responses: list[AIMessage] = Field(default_factory=list)
    delay: float = 0.0
    _cursor: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "scripted-chat-model"

    def bind_tools(self, tools, **kwargs):
        """create_agent 必需。基类默认实现直接抛 NotImplementedError。"""
        return self

    def _next(self) -> ChatResult:
        idx = min(self._cursor, len(self.responses) - 1)
        self._cursor += 1
        return ChatResult(generations=[ChatGeneration(message=self.responses[idx])])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._next()

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.delay:
            await asyncio.sleep(self.delay)
        return self._next()
```

说明：

- `bind_tools` 返回 `self` —— 夹具不需要真正绑定工具，只要不抛异常即可
- `_cursor` 用 `PrivateAttr` 而非普通字段，否则会被 pydantic 当成模型字段参与校验
- 响应列表按调用顺序消费：中间几条返回带 `tool_calls` 的 `AIMessage`，**最后一条必须是纯文本**

### 三个 autouse 护栏夹具（`conftest.py`）

| 夹具 | 挡什么 | 怎么被验 |
| --- | --- | --- |
| `_offline_guard` | 到非回环地址的任何 socket 连接 | `test_guard_offline_is_actually_armed` 主动触发一次 |
| `_db_readonly_guard` | `INSERT/UPDATE/DELETE/DDL` 等全部写语句 | `test_guard_db_writes_are_actually_blocked` 主动触发一次 |
| `reset_metrics` | 埋点计数跨用例污染 | 每个用例前后各清零一次 |

前两个是**否定性结论的护栏**（「断网跑通」「没写正式表」），只报「没报错」证明不了
——没报错也可能是拦截根本没生效。所以各配一条主动触发它们的用例，把结论变成可执行证据。

---

## 三、用例清单（核心调度 Agent 模块）

编号规则：`AGENT-<类型>-<序号>`。全部用例须在**断网**状态下可跑通（10.2：真实 API 不进常规用例）。

### 3.1 单元与契约（AGENT-U）

| 编号 | 用例 | 输入 | 预期 | 状态 |
| --- | --- | --- | --- | --- |
| AGENT-U-01 | `query_spaces` 参数异常 | `capacity=0`、时间倒置、时间不可解析、`space_type` 越界 | 返回业务错误，不抛未捕获异常 | ✅ 5 例通过 |
| AGENT-U-02 | `query_devices` 过滤可用性 | 库中混入 `device_status=2`（id=13）、`available_count=0`（id=15） | 结果中不含这些设备 | ✅ 6 例通过 |
| AGENT-U-03 | `space_type` 映射 | 需求含"展厅" | 实际传给 Tool 的是 `2` | ✅ 4 例通过 |
| AGENT-U-04 | trace 映射 | 构造含 `tool_calls` 的 messages | `step` 从 1 递增、`result` 非空、`timestamp` 格式 `YYYY-MM-DD HH:mm:ss` | ✅ 11 例通过 |
| AGENT-U-05 | timestamp 单调 | 多步 trace，含**同一秒**与**乱序**两种输入 | 各步 `timestamp` 不相同且递增 | ✅ 4 例通过 |

`AGENT-U-02` 的两条关键用例是**见证者式**的：先断言 service 桩**确实返回**坏设备（id=13 / 15），
再断言 Tool 把它们滤掉了。少了前半条，后半条在「数据里本来就没有坏设备」时也会过——
分不清是 Tool 真在滤还是运气。

### 3.2 六个决策场景（AGENT-S）

对应主文档 4.4 模块 4 的表格，是评审与答辩直接看的证据。**断言按 6.9 种子数据的实际值写**（场地 8：会议室×3、展厅×2、多功能厅×2、户外×1；设备 15：投影仪×4、音响×4、显示屏×3、无人机×2、直播设备×2）。

| 编号 | 场景 | 断言要点 | 状态 |
| --- | --- | --- | --- |
| AGENT-S-01 | A 预算与设备（800 元 / 40 人 + 双投影） | **保住场地 + `reason` 非空且说明「无需降级」**（原标准为「设备降级为单投影」，前提算不出已裁定作废，见文末） | ✅ 通过（透传口径；标准已按 A 改写） |
| AGENT-S-02 | B 场地拆分（无 40 人场地 → 拆两个小的） | 生成两个时段对齐的小场地方案 | ✅ 通过（口径见下） |
| AGENT-S-03 | C 设备替代（投影仪全占用） | 推荐替代设备（如 LED 显示屏），而非返回无方案 | ✅ 通过（口径见下） |
| AGENT-S-04 | D 需求矛盾（40 人 / 500 元） | `plan` 为 `null`，`message` 含至少 3 条修改建议，不编造方案 | ✅ 通过（口径见下） |
| AGENT-S-05 | E 活动合并（同团队连续两场） | 给出合并建议并说明节省的资源 | ✅ 通过（口径见下） |
| AGENT-S-06 | 设备数量不足（要两台直播设备，库里只有 1 台可借） | **降级为可借数**：`deviceIds` 只有可借的那一台、`reason` 原样透传、`trace` 留有查询这一步 | ✅ 通过（透传口径；前提真成立，见下） |

`AGENT-S-06` 是 2026-09-27 按裁定 C 新增的。它的前提**不依赖时段参数、也不依赖尚未定论的扣减口径**：种子 `直播设备×2` 里 id=15 是 `status=1` 但 `available_count=0`，被 `query_devices` 的可用性过滤滤掉，于是这个类型只剩 id=14 一台。这比「投影仪在某时段被占满」更适合当降级用例——后者受 `query_devices` 签名无时段参数所限，**进不了主链路**。

#### ⚠️ 六条 S 用例**验的不是模型的判断**

假模型把「该怎么决策」当作**输入**喂进来（它按脚本调 `query_spaces` → `query_devices` →
`submit_plan`），系统侧全是真的：真的 `create_agent`、真的工具查开发库、真的 trace 提取、
真的统一响应体。所以这六条验的是**透传与形状**：

- 模型写在 `reason` 里的降级/替代理由、备选方案（含 `backup_plan` snake_case 入参）、
  矛盾场景下的多条修改建议，是否**一字不少**地到达用户（这是主文档 10.2 与契约的要求）
- 两次锁定的 trace 是否各自成步、替代路径是否留痕、`deviceIds` 是否被系统擅自改写

**它们证明不了「800 元该不该降级」「40 人该不该拆场地」——那是模型的判断质量。**
决策质量需要真实 LLM。`2026-09-27 19:58` 起这一层有了第一条真实证据（`qwen-plus`
跑场景 A，原始输出见 `stage-05-completion.md` §3.2），结论如下：

> **`AGENT-S-01` 的断言「设备降级为单投影」在现有数据模型下无法达成。**
> 模型交出的是 `deviceIds=[1, 2]`（双投影），并在 `reason` 里写明「预算 800 元正好匹配，
> 有 4 台可用投影仪，无需任何降级」。这个判断与数据是自洽的：`device_resource` 表
> **没有价格字段**（`docs/seed.sql:83-84`），设备不计费；唯一与预算有关的 `space_resource.budget`
> 恰好等于预算上限，没有超支；`capacity>=40 AND space_type=2` 也只命中这一个场地。
> 也就是说「预算与设备冲突」这个前提**没有任何可计算依据**，而 Prompt 又明文禁止
> 模型编造价格——任何模型都算不出「双投影超支」。**需裁定的是标准措辞，不是模型的输出。**
> 详见 `stage-05-completion.md` §3.2 与 §6 #1（含三个候选选项）。
>
> ✅ **已裁定并落地（2026-09-27）**：采纳 **A + C**。A —— `AGENT-S-01` 的断言改为
> 「`plan` 非空、`spaceId` 命中、`reason` 非空且说明无需降级」；C —— 新增 `AGENT-S-06`
> 与前提护栏 `test_seed_supports_the_degradation_case`。「真的降级」这半边从此有真用例。
> 选项 B（补设备单价口径）未采纳，仍留在集成组的账上。上面这段推理**原文保留**，
> 作为「标准为什么改」的留痕。

同一轮真实调用还暴露两条（都只可能由真实调用暴露）：模型把「下周三」算成
**2026-10-04**（当天是星期日，正确应为 **09-30**）；模型未调 `lock_resources`，
改为先问用户，因此 `create_order` 与 `agent_trace` 补写在真实路径下**尚未被走到**。

六条场景各自的**前提**（种子数据里确实存在「预算恰好卡在场地价上」「没有 40 人的会议室」
「显示屏可借」「直播设备只剩一台可借」这些约束）单独由 `test_seed_supports_the_five_scenarios`
与 `test_seed_supports_the_degradation_case` 对着**真库**验——那部分不依赖模型，是真实结论。

⚠️ 但要注意：`AGENT-S-01` 的那条前提（「预算恰好卡在场地价上」）**只能证到「场地没有超支」，
证不到「设备会超支」**——两者之间隔着「设备是否计费」这个数据模型问题。用例通过不代表
预期结果可达，这是本次真实调用揭出来的教训。**A + C 裁定正是对这条教训的处置**：
A 把标准改成前提确实可达的那件事，C 用一条前提能算出来的用例承接「降级」语义，
于是「用例通过」与「预期可达」在两条上重新对齐。

**种子数据变更时这些用例必须同步修改**——断言与数据强耦合。

### 3.3 异常与降级（AGENT-E）

| 编号 | 用例 | 触发方式 | 预期 | 状态 |
| --- | --- | --- | --- | --- |
| AGENT-E-01 | 模型返回非 JSON | 假模型返回自然语言文本；另有一条**正文里带 ```json 围栏**的可救回样例 | HTTP 200，`plan=null`，`needConfirm=true`，`message` 为模型原文 | ✅ 2 例通过 |
| AGENT-E-02 | 模型调用超时 | 假模型 `delay` 超过（被改小的）`AGENT_TIMEOUT` | 200，友好提示，`trace` 保留中断前的步骤 | ✅ 2 例通过 |
| AGENT-E-03 | 无可用资源 | 工具返回空集（10000 人户外场地） | `plan=null`，`backupPlan=null`，明确说明无方案 | ✅ 1 例通过 |
| AGENT-E-04 | 工具抛异常 | 工具依赖的 service 抛 `RuntimeError`；另有一条整条流抛错 | 不 500，降级提示 | ✅ 2 例通过 |

`AGENT-E-02` 记两处实证：

1. 阈值被 `monkeypatch` 改成 0.05 秒——**不改的话这条用例要跑满 30 秒**。
2. 第二条用例替换的是 `collect_stamped_messages` 而不是用慢模型。原因具体：慢模型在
   **第一次模型调用**就卡住，一步都不会被打点，验不出「保留」这件事。这正是
   `run_schedule` 把 `stamped` 提在 `wait_for` **外面**、以 sink 传进去的全部理由
   ——`wait_for` 取消协程后返回值根本拿不到，只剩这个列表。

### 3.4 接口（AGENT-I）

| 编号 | 用例 | 预期 | 状态 |
| --- | --- | --- | --- |
| AGENT-I-01 | 正常调用 | 200，符合统一响应体，`data.trace` 非空且字段齐全 | ✅ 1 例通过 |
| AGENT-I-02 | 无 `Authorization` 头 | 401（响应体仍是统一结构） | ✅ 1 例通过 |
| AGENT-I-03 | `text` 为空字符串 | 422（`min_length=1` 生效，不空跑模型） | ✅ 1 例通过 |
| AGENT-I-04 | 请求体夹带 `userId` / `user_id` / `role` | 被忽略，实际使用 JWT 中的用户 | ✅ 3 参数化例通过 |
| AGENT-I-05 | 响应体不含敏感信息 | 响应中无 API Key、数据库连接串、JWT 密钥 | ✅ 4 例通过 |

`AGENT-I-04` 的**观察点不是「返回了 200」**——那证明不了用的是谁。用例截住
`run_schedule` 的实参逐项核对：`user_id` 必须等于 token 里的 `1`，且请求体的身份字段
不许混进需求原文。`AGENT-I-05` 另外覆盖了「缺 LLM 配置 → 503，只报字段名不回显值」，
以及 `build_model()` 显式传 `api_key`（堵死 `ChatOpenAI` 隐式读 `OPENAI_API_KEY` 的路径）。

### 3.5 并发与事务（AGENT-C）

| 编号 | 用例 | 预期 | 状态 |
| --- | --- | --- | --- |
| AGENT-C-01 | 两个协程同时锁定同一场地同一时段 | 恰好一个成功，另一个收到冲突提示 | ⛔ **xfail(strict)**，未通过 |
| AGENT-C-02 | 设备数量扣减 | 锁定后 `available_count` 正确递减，回滚时不减 | ⛔ **xfail(strict)**，未通过 |

**AGENT-C-01 是本模块唯一无法靠"看代码正确"来保证的用例。** 5.5 的顺序写对了才过，写错了在低并发下测不出来，演示当天并发上来就翻车。

两条用例的**断言是真的、被测实现还不存在**：模块 3（蔡玉礼）的 `create_order` 目前是
**只读桩**（不 `FOR UPDATE`、不 INSERT、不扣减，`orderId` 恒为 `None`），桩自己的 docstring
写着「`AGENT-C-01` 的并发语义无法在桩上验，**假装能验就是假绿**」。所以标记为
`xfail(strict=True)` 而不是删掉或改成能过的形状——`strict` 保证真实现落地后会**变红
（XPASS）**，强制摘掉标记。

**还有第二道锁挡在前面**，三件事缺一不可，否则摘了标记也过不了：

1. 蔡玉礼替换 `create_order` / `update_agent_trace` 的真实实现
2. **测试库权限**（集成组）——并发用例必须能真写、真回滚
3. `_db_readonly_guard` 对这两个文件**放开**（否则第 1、2 步到位也会被拦成
   `WriteForbiddenError`）

另有两例 `*_stub_state_is_recorded_not_glossed_over` **刻意断言桩的当前行为**
（`orderId` 为 `None`、`stub=True`、库存不变）。它们是**桩期临时用例**，
真实现落地后会失败——那时应当**删除**，而不是放宽断言。存在意义是让「C 未通过」
这件事在测试输出里看得见。

---

## 四、覆盖率要求

- `app/agent/` 覆盖率不低于 **80%**
- 阈值写入 `pytest.ini` 的 `--cov-fail-under`，由 CI 卡住
- 覆盖率是结果不是目标——为凑数字写空用例视为未完成

阈值与范围都在 `pytest.ini` 的 `addopts` 里，直接 `pytest -q` 即可：

```bash
cd backend && PYTHONIOENCODING=utf-8 \
  "F:/conda_envs/envs_dirs/smart_dev/python.exe" -m pytest -q
```

范围刻意**限定 `app.agent`**，不放宽到整个 `app`：分母里混进模块 3 的桩、模块 1 的认证等
他人代码，阈值会变得没有意义。单独跑某个文件时会因达不到阈值而失败，属预期——
要临时绕过用 `--no-cov`。

### 实测结果（2026-09-27，核心调度 Agent 模块）

```
82 passed, 2 xfailed in 20.77s
Required test coverage of 80% reached. Total coverage: 92.29%

Name                                       Stmts   Miss  Cover   Missing
------------------------------------------------------------------------
app\agent\__init__.py                          0      0   100%
app\agent\chains\__init__.py                   0      0   100%
app\agent\chains\builder.py                  178     29    84%   134, 146-147, 149, 158-159, 185, 196, 213, 255-259, 279, 283, 302-311, 320, 423, 450-454
app\agent\chains\trace.py                    136      3    98%   103, 137, 189
app\agent\context.py                          19      0   100%
app\agent\prompts\__init__.py                  0      0   100%
app\agent\prompts\scheduler.py                 9      0   100%
app\agent\tools\__init__.py                    7      0   100%
app\agent\tools\_common.py                    22      3    86%   33, 35, 52
app\agent\tools\generate_notification.py      19      0   100%
app\agent\tools\lock_resources.py             33      1    97%   124
app\agent\tools\query_devices.py              23      1    96%   90
app\agent\tools\query_spaces.py               26      0   100%
app\agent\tools\submit_plan.py                21      1    95%   95
------------------------------------------------------------------------
TOTAL                                        493     38    92%
```

`2 xfailed` 就是 `AGENT-C-01/02`（见 3.5），不是通过。未覆盖的 38 行主要是
降级路径里的容错分支（`extract_plan_from_text` 的各类畸形输入、`_last_ai_text` 的
list 形态 content 等），已在阶段 7 完成文档里列为后续补测项。

> 📌 **2026-09-27 后续更新（A + C 落地后）**：新增 `AGENT-S-06` 与
> `test_seed_supports_the_degradation_case` 两条，当前实测为 **84 passed, 2 xfailed**，
> `app/agent` 覆盖率 **92.37%**。上面的原始输出**保留不改写**——它是 82 例那一刻的快照，
> 和 `stage-07-completion.md` 里那份一样属于证据，不是需要跟着刷新的摘要。
> （同一批还把 `lock_resources` 的时间格式接缝修了，见 `stage-05-completion.md` 遗留 #7。）

### 断网与写库两条否定性结论的证据

- **断网**：`_offline_guard` 是 autouse 的 socket 拦截，非回环地址一律打回。
  它**不是**「拔网线」——本机关不掉网卡（要管理员权限，且会连 SSH 隧道一起断）。
  拦截比拔线更强：拔线只断外部网络，拦截能证明**每条用例**都没往外连。
  证据用例：`test_guard_offline_is_actually_armed`。
- **没写 `reserve_order`**：`_db_readonly_guard` 在 `before_cursor_execute` 里拒绝
  一切写语句（`SELECT ... FOR UPDATE` 是读，放行）。证据用例：
  `test_guard_db_writes_are_actually_blocked`。

---

## 五、测试库规范（主文档 6.8）

- 连 `smart_scheduler_test`，不连开发库
- 用例结束后回滚，不残留数据
- 无建库权限时退回备选方案：`test_` 前缀表 + `TRUNCATE`
- **禁止测试写 `reserve_order` 正式表**

### ⚠️ 当前偏差（核心调度 Agent 模块，2026-09-27）

| 要求 | 实际 | 原因 |
| --- | --- | --- |
| 连 `smart_scheduler_test` | 连的是 `smart_scheduler_dev` | 测试库报 **1044 无权访问**，属集成组 |
| 用例后回滚 | **无需回滚** | 写入被 `_db_readonly_guard` 前置拒绝，不存在需要回滚的数据 |

**未取得测试库权限前，不得声称本模块已符合 6.8。**

「回滚」这一步在连开发库的前提下本来就是错的安全手段：它保护的是「用例自己的写」，
而用例压根不许写。真正的保护是**拦截**——回滚方案在用例中途崩掉时可能留下半截数据，
拦截是每次都生效的前置拒绝。安全性更高，但**不等于合规**，偏差照记。

第三节末尾所列的 `AGENT-C-01/02` 需要真写、真回滚，**必须等测试库权限到位**后才能验。
