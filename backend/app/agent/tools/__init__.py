"""Agent Tool 层（阶段 4）。

5 个 Tool，全部满足阶段 4 §3.1 的四条禁令：

1. 全部 `async def`（主文档 3.3 / 7.4）
2. **不直接使用 `AsyncSession`**——数据读写一律经 `app/services/`（主文档 3.4 / 7.4 / 9.3）
3. **不注册为 FastAPI 路由**（主文档 5.3 / 9.3）。这里是给模型用的函数，不是给人用的接口。
   全仓不存在 `/api/v1/tools/*`，`tests/test_agent_tools.py` 有用例守着这条
4. 每个 Tool 有含参数说明的 docstring——**Agent 靠这些描述决定调不调、怎么调**

| Tool | 作用 | 是否写库 |
| --- | --- | --- |
| `query_spaces` | 按容量与类型查场地 | 否 |
| `query_devices` | 按类型查**可借用**设备（已滤损坏与零库存） | 否 |
| `lock_resources` | 锁定资源、创建订单 | **是**（经 `create_order`） |
| `generate_notification` | 生成通知文案 | 否 |
| `submit_plan` | 模型交出最终方案（阶段 4 增补项） | 否 |

`AGENT_TOOLS` 是给 `create_agent` 的挂载清单。顺序即 Prompt 里的呈现顺序——
按「先查后锁」的调用先后排，减少模型跳步。

（模块 7 补充）本目录另含 `notify_tools.py`：模块 7 提供的通知文案生成 Tool，
签名为 `generate_notification(order_id, notify_type, reason)`，与上表模块 4 的**同名
Tool 签名不同**。当前 `AGENT_TOOLS` 仍挂上表这 5 个；是否换用/并存需模块 4 与模块 7
双方确认后再改这一处。
"""

from app.agent.tools.generate_notification import generate_notification
from app.agent.tools.lock_resources import lock_resources
from app.agent.tools.query_devices import query_devices
from app.agent.tools.query_spaces import query_spaces
from app.agent.tools.submit_plan import submit_plan

__all__ = [
    "query_spaces",
    "query_devices",
    "lock_resources",
    "generate_notification",
    "submit_plan",
    "AGENT_TOOLS",
]

#: 挂到 `create_agent` 上的 Tool 清单，顺序 = Prompt 里的呈现顺序。
AGENT_TOOLS = [
    query_spaces,
    query_devices,
    lock_resources,
    generate_notification,
    submit_plan,
]
