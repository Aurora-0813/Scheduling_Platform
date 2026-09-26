"""
空间与设备资源模型
包含：space_resource, device_resource

主键类型用 `PK_TYPE`（本模块对团队版的唯一偏离）：MySQL 下仍是 BIGINT，
SQLite 下降级为 INTEGER，否则自增在 SQLite 上会被静默忽略。见 core/database.py。
"""
from datetime import datetime, time as dt_time
from decimal import Decimal

from sqlalchemy import BigInteger, String, Integer, DateTime, JSON, DECIMAL, Time, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import PK_TYPE, Base


class SpaceResource(Base):
    """空间资源表（会议室、展厅、多功能厅、户外场地）"""
    __tablename__ = "space_resource"

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True, comment="主键")
    space_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="空间名称")
    space_type: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="空间类型：1会议室 2展厅 3多功能厅 4户外场地"
    )
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, comment="容纳人数")
    location: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="位置")
    budget: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 2), nullable=True, comment="预算")

    open_start_time: Mapped[dt_time | None] = mapped_column(Time, nullable=True, comment="开放起始时间")
    open_end_time: Mapped[dt_time | None] = mapped_column(Time, nullable=True, comment="开放结束时间")

    status: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, comment="可用状态：1可用 0停用"
    )

    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )


class DeviceResource(Base):
    """设备资源表（投影仪、音响、无人机、直播设备等）"""
    __tablename__ = "device_resource"

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True, comment="主键")
    device_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="设备名称")
    device_type: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="设备类型")
    device_status: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, comment="设备状态：1完好，2损坏，3缺失配件"
    )
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="总数量")
    available_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="可用数量")

    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )
