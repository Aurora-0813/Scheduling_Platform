"""
通知文案生成出入参模型

契约（开发流程.md 5.3 模块7）：
POST /api/v1/notify/generate：{ "type": "延期致歉", "orderInfo": {} } → { "title": "...", "content": "..." }
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from app.schemas.common import CamelModel


class NotifyGenerateRequest(CamelModel):
    """通知文案生成请求"""

    # 契约的字段名是 type，与 Python 内建名冲突，故属性名用 notify_type 并显式指定 alias。
    # 显式 alias 优先级高于 alias_generator，不会被改写成 notifyType。
    # 兼容字符串语气名（"延期致歉"）与 notify_type 整数（2）两种传法。
    notify_type: str | int = Field(alias="type", description="通知类型：1提醒 2致歉 3故障告警，或对应中文名")

    order_info: dict[str, Any] = Field(
        default_factory=dict,
        description="订单事实载荷，全部内容作为 AI 生成文案的输入依据",
    )


class NotifyContent(CamelModel):
    """
    通知文案响应。

    严格保持 title / content 两个字段 —— 契约如此，不加任何额外字段。
    """

    title: str
    content: str
