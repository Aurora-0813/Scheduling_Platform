"""阶段 7 第一步：假 LLM 夹具冒烟。

create_agent 内部会调用 model.bind_tools(tools)。**实测 langchain-core 1.6.4 下
FakeMessagesListChatModel 与 GenericFakeChatModel 都没有实现 bind_tools**，
两者都会抛 NotImplementedError，因此需要自实现 bind_tools 的 StubChatModel。

写任何用例之前必须先验这一步，否则后面全是假绿——测试通过但根本没跑过真实逻辑。

运行：python tests/smoke_fake_llm.py
"""
import asyncio

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from pydantic import PrivateAttr


@tool
def query_spaces(capacity: int, space_type: int, start_time: str, end_time: str) -> dict:
    """查询可用场地。space_type: 1会议室 2展厅 3多功能厅 4户外场地"""
    return {"spaces": [{"id": 3, "name": "A栋3楼展厅", "capacity": 50}]}


def _tool_call() -> AIMessage:
    return AIMessage(content="", tool_calls=[{
        "name": "query_spaces",
        "args": {"capacity": 40, "space_type": 2,
                 "start_time": "2026-09-30 14:00:00", "end_time": "2026-09-30 16:00:00"},
        "id": "call_1",
    }])


class StubChatModel(BaseChatModel):
    """自实现 bind_tools 的替代夹具，供 create_agent 使用。"""

    responses: list[AIMessage] = []
    _cursor: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "stub-chat-model"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003 - 对齐父类签名
        """create_agent 必需。基类默认实现直接抛 NotImplementedError。"""
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        idx = min(self._cursor, len(self.responses) - 1)
        self._cursor += 1
        return ChatResult(generations=[ChatGeneration(message=self.responses[idx])])


async def probe(label: str, model) -> bool:
    try:
        agent = create_agent(model, tools=[query_spaces], system_prompt="你是调度助手")
        out = await agent.ainvoke({"messages": [{"role": "user", "content": "40人 展厅 投影"}]})
        msgs = out["messages"]
        tools_hit = [m for m in msgs if isinstance(m, ToolMessage)]
        print(f"[PASS] {label}：绑定成功，消息 {len(msgs)} 条，ToolMessage {len(tools_hit)} 条")
        return len(tools_hit) > 0
    except NotImplementedError:
        print(f"[FAIL] {label}：NotImplementedError（bind_tools 未实现）")
    except Exception as e:  # noqa: BLE001 - 冒烟脚本需要看清任何异常
        print(f"[WARN] {label}：{type(e).__name__} -> {e}")
    return False


async def main() -> None:
    # 第一次调用产生 tool_call，第二次给最终答复
    await probe("FakeMessagesListChatModel",
                FakeMessagesListChatModel(responses=[_tool_call(), AIMessage(content="已找到方案")]))
    await probe("GenericFakeChatModel",
                GenericFakeChatModel(messages=iter([_tool_call(), AIMessage(content="已找到方案")])))
    ok = await probe("StubChatModel（自实现 bind_tools）",
                     StubChatModel(responses=[_tool_call(), AIMessage(content="已找到方案")]))
    print("\n结论：", "StubChatModel 可用，作为本模块的假 LLM 夹具" if ok else "三个方案均不可用，需另寻")


if __name__ == "__main__":
    asyncio.run(main())
