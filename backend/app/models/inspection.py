"""
巡检与工单模型
包含：inspect_record, repair_ticket
"""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InspectRecord(Base):
    """巡检记录表"""

    __tablename__ = "inspect_record"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment="主键"
    )
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

    # 索引声明（项目文档 6.6）：空间巡检查询
    __table_args__ = (Index("idx_space_id", "space_id"),)


class RepairTicket(Base):
    """维修工单表"""

    __tablename__ = "repair_ticket"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment="主键"
    )
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

    # ---------- 处理结果与 AI 核验（模块 6 追加）----------
    # 由 `POST /tickets/{ticketId}/handle` 写入，见 alembic/versions/c4d8e1f0a2b7。
    # 三列全部 nullable：核验不是「处理」的前置条件 ——
    # 旧的 PUT /status 路径仍可只改状态，那些工单这三列就是 NULL。
    handle_image_url: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="处理结果照片地址"
    )
    # 取值同 deviceStatus 四值（理由见 inspect_service.DEVICE_STATUSES）：
    # 完好 即核验通过；损坏 / 缺失配件 / 无法识别 即未通过。
    verify_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="AI 核验结论：完好/损坏/缺失配件/无法识别"
    )
    verify_report: Mapped[str | None] = mapped_column(
        String(1000), nullable=True, comment="AI 核验说明"
    )

    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    # 索引声明（项目文档 6.6）：设备工单查询、工单状态筛选
    __table_args__ = (
        Index("idx_device_id", "device_id"),
        Index("idx_ticket_status", "ticket_status"),
    )
