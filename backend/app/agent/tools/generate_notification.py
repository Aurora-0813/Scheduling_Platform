"""Tool 4/5：`generate_notification` —— 生成通知文案。

对应主文档 5.3 模块 4 冻结签名：
    async def generate_notification(order_info: dict) -> dict

## 与冻结签名的一处偏差，以及为什么

参数名 `order_info` 未变，**类型标注由 `dict` 收紧为 `OrderInfo`（Pydantic 模型）**。
理由是模型侧的可用性：`dict` 在 JSON Schema 里退化成 `{"type": "object"}` 无字段提示，
模型只能靠 docstring 猜键名，而猜错键名的失败是**静默**的——`order_info.get("spaceName")`
拿到 `None`，文案里场地就变成「所选场地」，不报错、只是错。用 Pydantic 模型，
字段名与含义直接进 schema，由框架校验。

函数内部第一件事就是 `order_info.model_dump()` 转回 `dict` 再交给 service 层，
所以**对 `notify_service` 而言签名仍然是冻结的那个**——被收紧的只有 Agent 与 Tool 的边界。

边界（主文档 9.3）：「消息推送只负责生成文案，业务状态变更由后端控制」。
本 Tool **只产出标题与正文**，不发送、不落库、不改任何业务状态——
真正写 `notify_message` 是模块 7 的事，走 `notify_service`。
"""

from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.tools._common import fail
from app.services import generate_notification as _generate_notification_service

__all__ = ["generate_notification", "OrderInfo"]


class OrderInfo(BaseModel):
    """通知文案的输入信息（主文档 5.3 模块 7 的 `orderInfo`）。"""

    notifyType: str = Field(
        default="预约提醒",
        description="通知类型，取值：预约提醒 / 变更致歉 / 故障告警 / 延期致歉",
    )
    orderId: int | None = Field(None, description="订单 ID，来自 lock_resources 的 orderId")
    receiverId: int | None = Field(
        None, description="接收人用户 ID；省略时由后端按当前登录用户决定"
    )
    spaceName: str | None = Field(None, description="场地名称，来自 query_spaces")
    startTime: str | None = Field(None, description="开始时间，格式 YYYY-MM-DD HH:mm:ss")
    endTime: str | None = Field(None, description="结束时间，格式 YYYY-MM-DD HH:mm:ss")


@tool("generate_notification")
async def generate_notification(order_info: OrderInfo) -> dict:
    """根据订单信息生成一条通知文案（标题 + 正文）。

    什么时候用：预约创建成功、或方案有变更需要提前告知参会人员时调用。
    本工具**只生成文案，不发送消息**；把返回的 title / content 放进给用户的答复里。

    Args:
        order_info: 订单信息。`notifyType` 取 预约提醒 / 变更致歉 / 故障告警 / 延期致歉；
            其余字段（orderId、spaceName、startTime、endTime）尽量从前面工具的结果里带回，
            缺得越多，文案越笼统。

    Returns:
        {"ok": true, "notifyType": 1, "title": "预约成功提醒", "content": "..."}
        该通知类型在 6.3 的字典内没有对应 INT 值时返回 {"ok": false, "reason": "..."}，
        **不要因此自行编造文案**——按 reason 说明向用户交代或走替代类型。
    """
    # 收紧的类型在这里放回 dict，service 层看到的仍是冻结签名
    result = await _generate_notification_service(order_info.model_dump(exclude_none=True))

    if result.get("ok"):
        return {
            "ok": True,
            "notifyType": result.get("notifyType"),
            "title": result.get("title"),
            "content": result.get("content"),
            "stub": result.get("stub", False),
        }
    return fail(result.get("reason") or "通知文案生成失败，原因未提供。", title=None, content=None)
