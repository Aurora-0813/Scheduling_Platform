"""
消息通知模型
包含：notify_message

本模块（AI 冲突预警与智能通知）的主表。表结构完全按开发流程.md 6.3 第 9 节，
不新增任何列 —— 通知去重状态存放在 Redis 而非表内，避免触发 DDL 变更流程。
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NotifyMessage(Base):
    """消息通知表"""

    __tablename__ = "notify_message"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment="主键"
    )
    receiver_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=False, comment="接收人ID"
    )
    notify_type: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, comment="通知类型：1预约提醒 2变更致歉 3故障告警"
    )
    order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("reserve_order.id"), nullable=True, comment="关联订单ID"
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="通知标题")
    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="通知内容")
    is_read: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="0未读，1已读"
    )
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )

    # 索引声明（项目文档 6.6）：未读消息查询。
    # 复合索引 (receiver_id, is_read) 让「查我的未读消息」走索引，
    # 单个 receiver_id 索引无法覆盖 is_read 的过滤。
    __table_args__ = (Index("idx_receiver_read", "receiver_id", "is_read"),)


# 通知类型取值，与 6.3 字段说明一致
NOTIFY_TYPE_REMIND = 1    # 预约提醒
NOTIFY_TYPE_APOLOGY = 2   # 变更致歉
NOTIFY_TYPE_FAULT = 3     # 故障告警

NOTIFY_TYPE_LABELS: dict[int, str] = {
    NOTIFY_TYPE_REMIND: "预约提醒",
    NOTIFY_TYPE_APOLOGY: "变更致歉",
    NOTIFY_TYPE_FAULT: "故障告警",
}
