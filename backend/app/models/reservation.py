"""
预约订单模型
包含：reserve_order
"""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

#: `reserve_order.order_status` 中「占位」的状态（主文档 6.3 表 6）。
#: 1待确认、2已确认；3已取消与4已完成都不占位。
#:
#: ⚠️ 这里取 (1, 2) **比主文档 5.5 第 3 步更严**——5.5 原文写的是
#: 「该场地在目标时段是否存在**已确认**订单」，字面只覆盖 status=2。
#: 但 create_order 的 `order_status` 默认值是 1，若真实实现照 5.5 字面只查 status=2，
#: **Agent 落下的待确认订单就不占位**，并发下会被别人重复预约（模块 7 黄嵩的
#: 冲突监控也会漏报）。二者必须统一，见 `services/order_service.py` 的
#: 「待蔡玉礼确认」第 2 条。
#:
#: **本常量当前有两处定义**：此处，以及 `services/order_service.py`（模块 3）。
#: 「哪些状态占位」是 `order_status` 这个字段本身的性质，模块 3 的 `create_order`
#: 与模块 5 的 `query_spaces`（时段重叠排除）都要用它，而 service 子模块之间不宜
#: 互相 import（见 `services/__init__.py` 的「叶子」约定），故在两边都能 import 的
#: 模型层再声明一份。
#:
#: 之所以没有直接把 `order_service.py` 那行改成 import 本名来合并成一处：那个文件
#: 归属模块 3，且当前**不满足 ruff-format**，一旦改动它，pre-commit 的 `ruff-format`
#: 钩子会连带重排其内多处注释与推导式，给正在改它的同学制造无关冲突。故两份并存，
#: 由 `tests/test_space_service.py::test_occupying_status_matches_order_service`
#: 断言相等 —— 靠测试防漂移，不靠注释。等 `order_service.py` 下次被改到时，把它那行
#: 换成 `from app.models.reservation import OCCUPYING_STATUS` 即可合并。
OCCUPYING_STATUS = (1, 2)


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
    #
    # idx_status_start 不在 6.6 里，是集成组确认后补的：6.6 的索引在**设备
    # 维度**的时段统计上全部失效（设备是全局资源，`device_resource` 没有
    # space_id，idx_space_time 的最左前缀用不上；device_ids 又是 JSON 列）。
    # 模块 3 的 _device_conflicts 谓词为
    #     order_status IN (活跃) AND end_time > :start AND start_time < :end
    # 加这条后等值与范围都能走索引。其最左前缀 order_status 覆盖了
    # idx_status 的用途，保留后者只为不动线上既有索引，详见迁移
    # b7f1c4a92e35 的说明。
    __table_args__ = (
        Index("idx_user_id", "user_id"),
        Index("idx_space_time", "space_id", "start_time", "end_time"),
        Index("idx_status", "order_status"),
        Index("idx_status_start", "order_status", "start_time"),
    )
