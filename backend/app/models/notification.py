"""
消息通知模型
包含：notify_message
"""
from datetime import datetime

from sqlalchemy import BigInteger, String, Text, Integer, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NotifyMessage(Base):
    """消息通知表"""
    __tablename__ = "notify_message"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    receiver_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=False, comment="接收人ID"
    )
    notify_type: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="通知类型：1预约提醒 2变更致歉 3故障告警"
    )
    order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("reserve_order.id"), nullable=True, comment="关联订单ID"
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="通知标题")
    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="通知内容")
    is_read: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="0未读，1已读")

    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )