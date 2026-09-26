"""
预约订单模型
包含：reserve_order

主键类型用 `PK_TYPE`（本模块对团队版的唯一偏离），原因见 core/database.py。

跨模块字段说明：`user_id` 指向公用表 `sys_user.id`，此处为**真外键**（与团队版一致）。
真外键要求 `sys_user` 实体同时注册在 metadata 中，故本模块一并引入
`app.models.system`（见 models/__init__.py）；云库中的外键约束由集成组的 Alembic 迁移建立。
"""
from datetime import datetime

from sqlalchemy import BigInteger, String, Integer, DateTime, JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import PK_TYPE, Base


class ReserveOrder(Base):
    """预约订单表"""
    __tablename__ = "reserve_order"

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True, comment="主键")
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=False, comment="预约人ID"
    )
    space_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("space_resource.id"), nullable=False, comment="空间ID"
    )

    # JSON 字段存设备ID列表
    device_ids: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="设备ID列表")

    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="开始时间")
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="结束时间")
    order_status: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False,
        comment="订单状态：1待确认，2已确认，3已取消，4已完成"
    )

    # AI 相关字段
    agent_request: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, comment="用户原始需求"
    )
    # §5.3：trace 落库为 JSON **数组**（元素为 TraceStep 对象，见 schemas/agent.py）
    agent_trace: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="AI思考过程追踪"
    )

    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )
