"""
预约订单模型
包含：reserve_order
"""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.state_machine import OrderStatus

#: 「占用资源」的订单状态：待确认 + 已确认。
#:
#: 这是 `order_status` **列**的语义（哪些单占着场地/设备），不是状态机的流转规则，
#: 所以归在模型层：模块 4 与模块 7 都要拿它查 `reserve_order`，从模型取列的语义
#: 比去引模块 3 的业务逻辑更自然，也不用多引一层 `services`。
#:
#: 取值直接引用枚举成员、不写字面量 1/2 —— 这里是当前**唯一**的占用口径真值，
#: `services/order_service.py`（`§5.5` 第 3、4 步）、`api/conflicts.py`（模块 7）、
#: `api/agent.py`（mock 调度器）四处共用，别再回去写死。
#:
#: 注意 `order_service._ALLOWED_CREATE_STATUS` 今天值相同但**含义不同**——那是
#: 「创建时允许传入的 `order_status`」，创建即完成/取消属于非法输入。一旦占用口径
#: 变化两者立刻分叉，不要合并。
#:
#: 3已取消 / 4已完成 是终态，不占资源。
ACTIVE_ORDER_STATUSES: tuple[int, ...] = (
    OrderStatus.PENDING.value,
    OrderStatus.CONFIRMED.value,
)


class ReserveOrder(Base):
    """预约订单表"""

    __tablename__ = "reserve_order"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment="主键"
    )
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
        Integer, default=1, nullable=False, comment="订单状态：1待确认，2已确认，3已取消，4已完成"
    )

    # AI 相关字段
    agent_request: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, comment="用户原始需求"
    )
    agent_trace: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="AI思考过程追踪")

    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    # 索引声明（项目文档 6.6）
    # idx_space_time 是并发预约冲突检测的关键索引：检测「同一空间时段重叠」
    # 时按 (space_id, start_time, end_time) 做范围扫描，缺了它模块 5
    # 的冲突检测会退化成全表扫描。
    __table_args__ = (
        Index("idx_user_id", "user_id"),
        Index("idx_space_time", "space_id", "start_time", "end_time"),
        Index("idx_status", "order_status"),
    )
