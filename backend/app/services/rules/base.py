"""
软冲突规则引擎契约

核心设计：规则的 detect() 是同步纯函数，输入是不可变快照，不碰数据库、不碰 LLM。

这样做的三个收益：
1. 规则可在无数据库、无网络的机器上直接单测
2. AI 富化（参会人数抽取）被隔离在规则之外，AI 挂了规则照跑
   —— 满足开发流程.md 4.2「移除 AI 后降级为硬冲突检测」
3. 定时扫描可以把「读快照 / 调 AI / 跑规则 / 写库」切成四段，
   绝不在持有数据库连接时调用大模型
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol

# ---------- 通知受众 ----------
# 决定该冲突通知推给谁：预约人本人 / 全部管理员 / 两者
AUDIENCE_OWNER = "owner"
AUDIENCE_ADMIN = "admin"
AUDIENCE_OWNER_AND_ADMIN: frozenset[str] = frozenset({AUDIENCE_OWNER, AUDIENCE_ADMIN})
AUDIENCE_ADMIN_ONLY: frozenset[str] = frozenset({AUDIENCE_ADMIN})


def fmt_dt(value: datetime | None, *, with_date: bool = True) -> str:
    """统一的文案时间格式，避免各规则各写一套"""
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M" if with_date else "%H:%M")


def normalize_token(raw: str | None) -> str:
    """设备类型 / 角色名的归一化，用于大小写与空白不敏感的白名单比对"""
    return (raw or "").strip().lower()


# ---------- 订单状态口径 ----------
# 【前瞻口径】参与冲突检测的「有效订单」：1 待确认 / 2 已确认。
# 口径由预约模块负责人 2026-09-27 确认：**不含 4 已完成**。
# 用于扫描窗口，服务 continuous_activity / capacity_overflow / high_value_device
# 这类「往后看」的规则。
#
# 待对方把常量落到 app/models/reservation.py 后，改为从那里导入，本模块不再留定义。
ACTIVE_ORDER_STATUSES: tuple[int, ...] = (1, 2)

# 【回看口径】证明资源被真实占用的订单：1 待确认 / 2 已确认 / 4 已完成
#（3 已取消不算占用）。**必须与上面的前瞻口径分开**：
# 长期闲置规则要回答的是「这个场地最近被用过吗」，读的是各场地
# 「最后一次预约的结束时间」；若沿用 (1,2)，任何最后一笔预约已完成的场地
# 都会丢掉这条记录，被误判成「长期闲置、无预约记录」——假警报且描述与事实相反。
HISTORY_ORDER_STATUSES: tuple[int, ...] = (1, 2, 4)


# ---------- 不可变快照 ----------


@dataclass(frozen=True, slots=True)
class OrderView:
    """订单快照。字段与 reserve_order 表对齐，但已剥掉本模块不关心的内容"""

    id: int
    user_id: int
    space_id: int
    start_time: datetime
    end_time: datetime
    order_status: int
    device_ids: tuple[int, ...] = ()
    agent_request: str | None = None
    # 由 AI 富化步骤回填；规则只看这个字段，不自己解析文本
    attendee_count: int | None = None


@dataclass(frozen=True, slots=True)
class SpaceView:
    """场地快照"""

    id: int
    space_name: str
    space_type: int = 1
    capacity: int = 0
    status: int = 1


@dataclass(frozen=True, slots=True)
class DeviceView:
    """设备快照"""

    id: int
    device_name: str
    device_type: str | None = None
    device_status: int = 1


@dataclass(frozen=True, slots=True)
class UserView:
    """用户快照"""

    id: int
    username: str
    role_id: int | None = None
    role_name: str | None = None


@dataclass(frozen=True, slots=True)
class ConflictRuleConfig:
    """阈值快照。默认值与 app/core/config.py 保持一致，测试可独立构造"""

    # ① 连续活动无休息：相邻两场间隔小于该分钟数即命中
    continuous_gap_minutes: int = 15
    # ② 容量远超需求：capacity >= 人数 * 倍数 且 差值 >= 绝对下限
    capacity_ratio: float = 3.0
    capacity_min_abs_gap: int = 10
    capacity_min_capacity: int = 10
    # ③ 高价值设备白名单与「普通使用者」角色名
    high_value_device_types: frozenset[str] = frozenset({"无人机", "直播设备", "显示屏"})
    normal_role_names: frozenset[str] = frozenset({"普通使用者", "普通用户"})
    # ④ 资源过度占用
    daily_occupy_hours: float = 8.0
    daily_occupy_min_orders: int = 2
    # ⑤ 长期闲置
    idle_days: int = 14

    @classmethod
    def from_settings(cls) -> ConflictRuleConfig:
        """从应用配置构造，供服务层使用；测试直接构造本类，不依赖 .env"""
        from app.core.config import settings

        return cls(
            continuous_gap_minutes=settings.CONFLICT_CONTINUOUS_GAP_MINUTES,
            capacity_ratio=settings.CONFLICT_CAPACITY_RATIO,
            capacity_min_abs_gap=settings.CONFLICT_CAPACITY_MIN_ABS_GAP,
            capacity_min_capacity=settings.CONFLICT_CAPACITY_MIN_CAPACITY,
            high_value_device_types=settings.high_value_device_types,
            normal_role_names=settings.normal_role_names,
            daily_occupy_hours=settings.CONFLICT_DAILY_OCCUPY_HOURS,
            daily_occupy_min_orders=settings.CONFLICT_DAILY_OCCUPY_MIN_ORDERS,
            idle_days=settings.CONFLICT_IDLE_DAYS,
        )


@dataclass(frozen=True, slots=True)
class RuleContext:
    """
    规则执行上下文：一次性从数据库读出的全量快照。

    space_last_order_at 是各场地**最后一次有效预约的结束时间**，
    由一条聚合查询单独提供 —— 因为扫描窗口（默认 ±7 天）比闲置判定窗口
    （默认 14 天）短，仅靠窗口内订单无法准确判断闲置。
    """

    orders: tuple[OrderView, ...]
    spaces: Mapping[int, SpaceView]
    devices: Mapping[int, DeviceView]
    users: Mapping[int, UserView]
    now: datetime
    config: ConflictRuleConfig = field(default_factory=ConflictRuleConfig)
    space_last_order_at: Mapping[int, datetime] = field(default_factory=dict)

    def space_name(self, space_id: int | None) -> str:
        """场地名，缺失时给出可读占位而不是抛异常"""
        if space_id is None:
            return ""
        space = self.spaces.get(space_id)
        return space.space_name if space else f"场地#{space_id}"

    def user_name(self, user_id: int | None) -> str:
        """用户名，缺失时给出可读占位"""
        if user_id is None:
            return ""
        user = self.users.get(user_id)
        return user.username if user else f"用户#{user_id}"


@dataclass(frozen=True, slots=True)
class RuleHit:
    """
    一条命中的软冲突。

    reason 只陈述事实（供 AI 与模板填充），不含处置建议 ——
    建议由 AI 单独生成，避免事实与建议混在一起后被模型张冠李戴。
    """

    rule_code: str
    rule_label: str
    order_ids: tuple[int, ...]
    reason: str
    space_id: int | None = None
    user_id: int | None = None
    audience: frozenset[str] = AUDIENCE_OWNER_AND_ADMIN
    facts: Mapping[str, Any] = field(default_factory=dict)
    severity: str = "medium"


class SoftConflictRule(Protocol):
    """软冲突规则接口"""

    code: str
    label: str

    def detect(self, ctx: RuleContext) -> list[RuleHit]:
        """同步执行检测，返回命中的冲突列表"""
        ...
