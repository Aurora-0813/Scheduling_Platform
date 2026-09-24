"""
巡检与工单模型
包含：inspect_record, repair_ticket
"""
from datetime import datetime

from sqlalchemy import BigInteger, String, Integer, DateTime, JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InspectRecord(Base):
    """巡检记录表"""
    __tablename__ = "inspect_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    space_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("space_resource.id"), nullable=True, comment="巡检关联的空间ID"
    )
    image_url: Mapped[str] = mapped_column(String(512), nullable=False, comment="巡检图片地址")
    ai_result: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="AI识别结果")
    inspector_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=False, comment="巡检人ID"
    )

    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )


class RepairTicket(Base):
    """维修工单表"""
    __tablename__ = "repair_ticket"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    inspect_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("inspect_record.id"), nullable=True, comment="关联巡检记录ID"
    )
    device_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("device_resource.id"), nullable=True, comment="关联设备ID"
    )
    space_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("space_resource.id"), nullable=True, comment="关联空间ID"
    )
    ticket_status: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, comment="工单状态：1待处理，2处理中，3已完成"
    )
    handler_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=True, comment="处理人ID"
    )

    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )