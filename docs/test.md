# 测试用例文档

> 依据《项目文档.md》10.1~10.3（测试规范）、6.8（测试库）、6.9（种子数据）、11.1~11.2。
> 接口变更或种子数据变更时，本文件须同步更新。

---

## 一、环境基线

> 用途：M4 联调时他人照此复现。**本小节必须与实际执行结果一致，未核对项如实标注。**

| 项 | 值 | 状态 |
| --- | --- | --- |
| 核对日期 | 2026-09-24 | ✅ 已核对 |
| Python 版本 | 3.11.9 | ✅ 已核对 |
| conda 环境 | `smart_dev`（`F:\conda_envs\envs_dirs\smart_dev`） | ✅ 已核对 |
| 依赖安装方式 | `pip install -r requirements.txt`（版本全量 `==` 锁定） | ✅ 已执行 |
| 关键版本 | langchain 1.3.11 / langchain-openai 1.5.0 / langchain-classic 1.0.0 / langchain-core 1.6.4 / langgraph 1.2.12 | ✅ 已核对 |
| 数据库驱动 | asyncmy 0.2.10 | ✅ 已安装 |
| 认证依赖 | passlib 1.7.4 + bcrypt 4.0.1（哈希自检 `verify: True`） | ✅ 已核对 |
| 锁文件 | `backend/requirements.lock`（68 行，`pip freeze` 生成） | ✅ 已生成 |
| DDL 版本 | 未核对 | ⛔ 阻塞：无 `.env` 凭据，无法连库 |
| 种子数据条数 | 未核对（期望 场地 8 / 设备 15 / 预约 10） | ⛔ 阻塞：同上 |
| 测试库 | 未核对（`smart_scheduler_test`） | ⛔ 阻塞：同上 |

**未核对项的阻塞原因**：`backend/.env` 不存在，无数据库连接凭据；且 6.7 的 DDL 与 6.9 的种子数据尚未由集成组执行。补齐后须重跑基线核对并更新本表。

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

`tests/conftest.py` 的 `fake_llm` 夹具使用 `StubChatModel`：

```python
class StubChatModel(BaseChatModel):
    """自实现 bind_tools 的替代夹具，供 create_agent 使用。"""
    responses: list[AIMessage] = []
    _cursor: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "stub-chat-model"

    def bind_tools(self, tools, **kwargs):
        """create_agent 必需。基类默认实现直接抛 NotImplementedError。"""
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        idx = min(self._cursor, len(self.responses) - 1)
        self._cursor += 1
        return ChatResult(generations=[ChatGeneration(message=self.responses[idx])])
```

说明：

- `bind_tools` 返回 `self` —— 夹具不需要真正绑定工具，只要不抛异常即可
- `_cursor` 用 `PrivateAttr` 而非普通字段，否则会被 pydantic 当成模型字段参与校验
- 响应列表按调用顺序消费：第一次调用返回带 `tool_calls` 的 `AIMessage`，第二次返回最终答复

---

## 三、用例清单（核心调度 Agent 模块）

编号规则：`AGENT-<类型>-<序号>`。全部用例须在**断网**状态下可跑通（10.2：真实 API 不进常规用例）。

### 3.1 单元与契约（AGENT-U）

| 编号 | 用例 | 输入 | 预期 | 状态 |
| --- | --- | --- | --- | --- |
| AGENT-U-01 | `query_spaces` 参数异常 | `capacity=0`、时间倒置 | 返回业务错误，不抛未捕获异常 | 待实现 |
| AGENT-U-02 | `query_devices` 过滤可用性 | 库中混入 `device_status=2`、`available_count=0` | 结果中不含这些设备 | 待实现 |
| AGENT-U-03 | `space_type` 映射 | 需求含"展厅" | 实际传给 Tool 的是 `2` | 待实现 |
| AGENT-U-04 | trace 映射 | 构造含 `tool_calls` 的 messages | `step` 从 1 递增、`result` 非空、`timestamp` 格式 `YYYY-MM-DD HH:mm:ss` | 待实现 |
| AGENT-U-05 | timestamp 单调 | 多步 trace | 各步 `timestamp` 不相同且递增 | 待实现 |

### 3.2 五个决策场景（AGENT-S）

对应主文档 4.4 模块 4 的表格，是评审与答辩直接看的证据。**断言按 6.9 种子数据的实际值写**（场地 8：会议室×3、展厅×2、多功能厅×2、户外×1；设备 15：投影仪×4、音响×4、显示屏×3、无人机×2、直播设备×2）。

| 编号 | 场景 | 断言要点 | 状态 |
| --- | --- | --- | --- |
| AGENT-S-01 | A 预算降级（800 元 / 40 人 + 双投影） | 保住场地，设备降级为单投影，`plan.reason` 说明降级原因 | 待实现 |
| AGENT-S-02 | B 场地拆分（无 40 人场地 → 拆两个小的） | 生成两个时段对齐的小场地方案 | 待实现 |
| AGENT-S-03 | C 设备替代（投影仪全占用） | 推荐替代设备（如 LED 显示屏），而非返回无方案 | 待实现 |
| AGENT-S-04 | D 需求矛盾（40 人 / 500 元） | `plan` 为 `null`，`message` 含至少 3 条修改建议，不编造方案 | 待实现 |
| AGENT-S-05 | E 活动合并（同团队连续两场） | 给出合并建议并说明节省的资源 | 待实现 |

**种子数据变更时这些用例必须同步修改**——断言与数据强耦合。

### 3.3 异常与降级（AGENT-E）

| 编号 | 用例 | 触发方式 | 预期 | 状态 |
| --- | --- | --- | --- | --- |
| AGENT-E-01 | 模型返回非 JSON | 假模型返回自然语言文本 | HTTP 200，`plan=null`，`needConfirm=true`，`message` 为模型原文 | 待实现 |
| AGENT-E-02 | 模型调用超时 | 假模型抛 `TimeoutError` | 200，友好提示，`trace` 保留中断前的步骤 | 待实现 |
| AGENT-E-03 | 无可用资源 | 工具返回空集 | `plan=null`，`backupPlan=null`，明确说明无方案 | 待实现 |
| AGENT-E-04 | 工具抛异常 | 桩函数抛错 | 不 500，降级提示 | 待实现 |

### 3.4 接口（AGENT-I）

| 编号 | 用例 | 预期 | 状态 |
| --- | --- | --- | --- |
| AGENT-I-01 | 正常调用 | 200，符合统一响应体，`data.trace` 非空且字段齐全 | 待实现 |
| AGENT-I-02 | 无 `Authorization` 头 | 401 | 待实现 |
| AGENT-I-03 | `text` 为空字符串 | 422（`min_length=1` 生效，不空跑模型） | 待实现 |
| AGENT-I-04 | 请求体夹带 `userId` | 被忽略，实际使用 JWT 中的用户 | 待实现 |
| AGENT-I-05 | 响应体不含敏感信息 | 响应中无 API Key、数据库连接串 | 待实现 |

### 3.5 并发与事务（AGENT-C）

| 编号 | 用例 | 预期 | 状态 |
| --- | --- | --- | --- |
| AGENT-C-01 | 两个协程同时锁定同一场地同一时段 | 恰好一个成功，另一个收到冲突提示 | 待实现 |
| AGENT-C-02 | 设备数量扣减 | 锁定后 `available_count` 正确递减，回滚时不减 | 待实现 |

**AGENT-C-01 是本模块唯一无法靠"看代码正确"来保证的用例。** 5.5 的顺序写对了才过，写错了在低并发下测不出来，演示当天并发上来就翻车。

---

## 四、覆盖率要求

- `app/agent/` 覆盖率不低于 **80%**
- 阈值写入 `pytest.ini` 的 `--cov-fail-under`，由 CI 卡住
- 覆盖率是结果不是目标——为凑数字写空用例视为未完成

```bash
cd backend && pytest -q --cov=app --cov-report=term-missing
```

---

## 五、测试库规范（主文档 6.8）

- 连 `smart_scheduler_test`，不连开发库
- 用例结束后回滚，不残留数据
- 无建库权限时退回备选方案：`test_` 前缀表 + `TRUNCATE`
- **禁止测试写 `reserve_order` 正式表**
