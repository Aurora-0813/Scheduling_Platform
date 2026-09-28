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
#: 断言相等 —— 靠测试防漂移，不靠注释。
#:
#: ⚠️ **合入 `main` 时本常量要整体删掉**，改用蔡玉礼分支
#: （`origin/feat/module3-caiyuli`）**同一文件**里的 `ACTIVE_ORDER_STATUSES` ——
#: 那边已把收敛做完了，取值引 `app.state_machine.OrderStatus.PENDING/CONFIRMED`，
#: 比这里的字面量好，且他的注释已声明那是唯一真值、供 `order_service` /
#: `api/conflicts.py`（模块 7）/ `api/agent.py` 共用。
#:
#: ⚠️ 但**别「直接取他的版本」**——实测（2026-09-28）他那版 `reservation.py` 里
#: `__table_args__` / `Index(` / `idx_` 的出现次数**都是 0**：四条索引声明
#: （`idx_user_id` / `idx_space_time` / `idx_status` / `idx_status_start`）一条没有，
#: 他分支上也没有建这些索引的迁移。而 `main` 上四条俱在（`idx_status_start` 见迁移
#: `b7f1c4a92e35`），且本文件在 `main` 与徐川分支上**逐字节一致** —— 可见那是集成组
#: 后加的、他的分支较旧。盲取他的版本 = 静默丢掉四条索引声明：库里的索引还在
#: （迁移建的），但模型不再声明，`alembic autogenerate` 会反过来提议 **DROP** 它们。
#:
#: 故本文件的冲突要**三方合并**，最终须同时含：
#:   · 他的：`ACTIVE_ORDER_STATUSES`（引 `app.state_machine.OrderStatus`）、`PK_TYPE`
#:     主键、`device_ids` / `agent_trace` 的 `Mapped[list | None]` 标注（他把 `dict`
#:     改成 `list` 有理由：模块 8 看板要按它反推设备占用率）；
#:   · `main` 的：四条 `Index(...)` 与 `idx_status_start` 那段注释；
#:   · 删掉本段注释与 `OCCUPYING_STATUS`。
#:
#: 另需改三处引用：① `services/space_service.py` 的 import 与 `in_()` 用名；
#: ② `tests/test_space_service.py` 的 import 与护栏用例（改为比 `ACTIVE_ORDER_STATUSES`）；
#: ③ 本常量自身（连带本段注释）。
#:
#: 这里**故意保持字面量、且不与他的常量同名**：同名会让冲突从「两个常量取哪个」
#: 退化成「同一个名字两份定义」，反而更难判。故不预先改名，只在合并时收敛。
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
