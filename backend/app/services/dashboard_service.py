"""
AI 数据洞察面板 - 数据统计服务
负责从业务数据库聚合统计指标，供前端 ECharts 和 AI 报告模块使用。
对应文档：5.3 模块 8、7.3 后端规范
"""
from datetime import datetime, time, timedelta

from sqlalchemy import bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inspection import RepairTicket
from app.models.reservation import ReserveOrder
from app.models.resource import DeviceResource, SpaceResource

# 统计窗口默认值从请求契约处导入，保证「默认 7 天」只有一个定义处
# （app/schemas/dashboard.py 同时定义 MIN_DAYS / MAX_DAYS 供路由校验）
from app.schemas.dashboard import DEFAULT_DAYS  # noqa: F401  （对外仍可从本模块取）

# ============ 常量 ============
# 场地开放时段的**兜底**时长（小时/天）。
#
# ⚠️ 注意语义：它**不是**「每个场地每天开放多少小时」，而是
# 「某行读不到开放时段、或读到异常值时，按多少小时兜底」。
# 正常路径下每行用 space_resource.open_start_time / open_end_time 的真实差值累加。
#
# 14 = 08:00-22:00，即《规范》6.7 DDL 的回填值：
#     UPDATE space_resource SET open_start_time='08:00:00', open_end_time='22:00:00'
#     WHERE open_time IS NOT NULL;
#
# 2026-09-28 真库实测（8 个可用场地，无一行 NULL）：
#     1× 户外场地 06:00-23:00 = 17h / 5× 会议室+多功能厅 08:00-22:00 = 14h /
#     2× 展厅 09:00-21:00 = 12h  →  合计 111 h/天
# 说明**真库不是统一的 14h**，所以这个常量只作兜底，分母必须逐行算（见下）。
OPEN_HOURS_FALLBACK = 14

# ---------- 订单状态口径（两个口径不同，是刻意的，不是笔误）----------
# 状态定义见 reserve_order.order_status：1 待确认、2 已确认、3 已取消、4 已完成。
#
# 口径 A｜场地使用率 / 高峰时段 —— 「场地在窗口内被实际占用过」
#   待确认(1) 已占住时段、已确认(2) 确定占用、已完成(4) 是窗口内真实发生过的占用，
#   三者都算真实占用；已取消(3) 不占位，排除。
#   ⚠️ 旧实现用 [2, 4]，漏了状态 1，会低估使用率 —— 2026-09-27 修正。
SPACE_OCCUPIED_STATUS = [1, 2, 4]
#
# 口径 B｜设备闲置率 —— 「设备当前被预约(占用)的状态」
#   已完成(4) 意味着设备已归还，不再占用，故不含 4；已取消(3) 同样不占位。
#   依据：贾世杰 2026-09-27 确认。
DEVICE_OCCUPIED_STATUS = [1, 2]
#
# 两个口径唯一的差异就在「已完成(4)」：
#   场地使用率算的是「这段时间里场地被用过多久」—— 已完成是过去真实发生过的占用，计入；
#   设备闲置率算的是「此刻还有多少设备被占着」—— 已完成的设备已归还，不计入。
#   「已取消(3)」两个口径都排除（预约没成立，既没占场地也没占设备）。


# ============ 1. 场地使用率 ============
def _open_hours(start: time | None, end: time | None) -> float:
    """
    单个场地**每天**的开放小时数。

    - 时段齐全且 `end > start` → 真实差值（12 / 14 / 17 这样）
    - `NULL` → 兜底 `OPEN_HOURS_FALLBACK`（该场地在库里的开放时段没填）
    - `end <= start` → 兜底 `OPEN_HOURS_FALLBACK`，**不猜跨天**

    最后一条是有意为之（2026-09-28 定）：真库三种时段（06:00-23:00、08:00-22:00、
    09:00-21:00）都不跨零点，所以「跨天营业」和「字段填反了」在数值上无法区分 ——
    `20:00-02:00` 是跨天，`02:00-20:00` 是填反，两者算出来一个是 +18h 一个是 -18h，
    但都只是「end < start」。既然分不清，就不猜：按异常走兜底，
    让分母不至于因为一行脏数据变成负数（负分母会导致使用率 > 100% 甚至为负）。
    真出现跨天场地时，应先确认业务语义，再回来加分支。
    """
    if start is None or end is None:
        return OPEN_HOURS_FALLBACK

    span = timedelta(
        hours=end.hour - start.hour,
        minutes=end.minute - start.minute,
        seconds=end.second - start.second,
    )
    if span <= timedelta(0):
        return OPEN_HOURS_FALLBACK

    return span.total_seconds() / 3600.0


def _occupied_hours(start: datetime, end: datetime) -> float:
    """
    一条订单的占用时长（小时）。

    `end <= start` → **返回 0.0**，绝不返回负数（2026-09-28 补）。

    为什么必须夹住下界：`reserve_order` 的 start/end 只有 NOT NULL，
    **没有 CHECK 约束保证 `end > start`**。一行填反的脏数据（如 start=今天、
    end=四天前）会贡献 -99h，把分子整体拉成负数 —— 实测一条这样的订单就让
    `spaceUsageRate` 算成 **-30.5%**，而 `DashboardStatsData.space_usage_rate`
    是 `ge=0`，于是 FastAPI 的响应校验失败，**`/stats` 直接 500**，
    整个看板挂掉（不只那一项指标）。上界早有 `min(..., 100)` 挡着
    （防脏数据算出假饱和），下界一直漏着 —— 这是同一个防御的缺角。

    为什么夹在**每一行**、而不是最后夹总数：只有逐行夹 0，才能让那条脏数据
    既不虚增也不虚减。若改成最后夹总数，一条 -99h 会把同一批里真实的 +39.2h
    一起抹成 0 —— 等于用脏数据覆盖掉好数据。
    """
    seconds = (end - start).total_seconds()
    return seconds / 3600.0 if seconds > 0 else 0.0


async def get_space_usage_rate(db: AsyncSession, days: int = DEFAULT_DAYS) -> float:
    """
    场地使用率 = 已占用总时长(小时) / (各可用场地每天开放小时数之和 × 天数)

    订单状态口径：SPACE_OCCUPIED_STATUS = [1, 2, 4]（待确认 + 已确认 + 已完成）。
    已取消(3) 不占位，排除。详见文件顶部「订单状态口径」说明。

    **分母口径（2026-09-28 定型，原 P2 待办已关闭）**：逐行读
    `space_resource.open_start_time / open_end_time` 累加，不再用「场地数 × 固定 14h」。

    为什么必须逐行：真库 8 个可用场地实测有三种时段（17h / 14h / 12h，见
    `OPEN_HOURS_FALLBACK` 上方注释）。原来的固定 14h 会**低估**使用率 ——
    实测量化：该分布下分母偏大 0.90%（112 vs 111 h/天），
    若换成统一 12h 的场地构成则偏差达 14.3%。而且它不报错，只是数字静静地偏小。

    **为什么在 Python 层累加，而不是写 SQL 聚合**：
    `space_resource` 是**资源目录表**（真库 8 行），不是流水表 ——
    把 N 行的两个 TIME 值取回本地累加是微秒级，量级天然有限。
    换来的是：不必引入 `TIME_TO_SEC` 这类 MySQL 方言函数，
    离线测试的 SQLite 夹具因此不需要再注册 UDF（对比 `get_device_idle_rate`
    那个 case 必须在 SQL 里算 —— 它要跨全表订单展开 JSON 数组，Python 层会物化整列）。
    若将来场地数上千，再改回 SQL 聚合。
    """
    since = datetime.now() - timedelta(days=days)

    # ---------- 分母：各可用场地每天开放小时数之和 ----------
    # status = 1：停用场地不进分母。**分子必须取同一个场地集合**（下方 :149 的 JOIN），
    # 否则就是在「一个不存在的容量」上算占用 —— 使用率虚高且不报错。
    # 锁由 test_space_usage_rate.py 的 U4 守着。
    space_rows = (await db.execute(
        select(SpaceResource.open_start_time, SpaceResource.open_end_time)
        .where(SpaceResource.status == 1)
    )).all()
    if not space_rows:
        return 0.0

    hours_per_day = sum(
        _open_hours(r.open_start_time, r.open_end_time) for r in space_rows
    )
    total_capacity_hours = hours_per_day * days

    # ---------- 分子：窗口内被占用的总时长 ----------
    # 用 Python 层累加，避免 timestampdiff 的兼容问题。
    #
    # ⚠️ **JOIN space_resource + status == 1 不是可选项（2026-09-28 修）**：
    # 分母只累加 status=1 的场地，分子若不过滤就会把挂在**停用场地**上的订单也算进来，
    # 等于「在一个不存在的容量上算占用」。实测：分母 273h、分子多算停用场地的 2h
    # → 20.7% 而不是 20.0%，**不报错、只是数字静静地虚高**。
    # 真库当前 8 个场地全是 status=1，所以这个缺口在演示数据上看不出来；
    # 一旦有场地停用（维修 / 闭馆）就会显现。锁：tests/test_space_usage_rate.py::U4。
    rows = (await db.execute(
        select(ReserveOrder.start_time, ReserveOrder.end_time)
        .join(SpaceResource, SpaceResource.id == ReserveOrder.space_id)
        .where(
            ReserveOrder.order_status.in_(SPACE_OCCUPIED_STATUS),
            ReserveOrder.start_time >= since,
            SpaceResource.status == 1,
        )
    )).all()

    reserved_hours = sum(
        _occupied_hours(r.start_time, r.end_time) for r in rows
    )

    # 上界 min(..., 100) 防脏数据算出「假饱和」；下界 max(..., 0) 是 2026-09-28 补的，
    # 防脏数据算出负值把 /stats 打成 500 —— 逐行夹 0 已经挡住了主流情形，
    # 这里再兜一次是为了让「无论输入多脏，返回值都落在 schema 的 [0, 100] 内」成为
    # 这个函数的**不变式**，而不是靠调用方去猜。见 `_occupied_hours`。
    rate = reserved_hours / total_capacity_hours * 100
    return round(min(max(rate, 0.0), 100.0), 1)


# ============ 2. 设备闲置率 ============
# device_ids 的实际存储形态（2026-09-27 贾世杰确认，四处依据）：
#   alembic/versions/8969262c9d0c_init_tables_single_role.py:92 → sa.JSON()
#   app/models/reservation.py:26  → mapped_column(JSON, nullable=True)
#   docs/database.md:134          → device_ids | JSON | 设备ID列表
#   docs/api.md:64                → deviceIds: int[]
# 即：MySQL JSON 列，存「JSON 数组 of int」，形如 [1, 2] / [16] / []；
# 列可空、可为 NULL。**不是 "1,2,3" 逗号字符串** ——
# 故原先的字符串兼容逻辑连同临时开关 COUNT_MODE 一并删除。
#
# 展开用 JSON_TABLE（MySQL 8.0.4+，线上 8.0.39 支持）。
# 刻意不在 Python 层解析 JSON 数组：那样要把整列拉回本地再逐个去重，
# 设备量一大就是全表物化；而「展开 + 去重 + 求交 + 计数」SQL 一次能算完。

# 窗口内被占用的【去重】设备数
#   - COALESCE(device_ids, JSON_ARRAY())：NULL 视作空数组，不让 NULL 把聚合算崩
#   - '$[*]'：展开数组的每个元素；[] 展开出 0 行，天然计为 0 台，无需特殊分支
#   - COUNT(DISTINCT jt.did)：JSON 数组本身不去重，同一设备在多条订单（或同一条
#     订单）里重复出现时只算一次
#   - JOIN device_resource：只认真实存在的设备 ID，防脏数据虚增占用
_OCCUPIED_DEVICE_COUNT_SQL = text("""
    SELECT COUNT(DISTINCT jt.did)
    FROM reserve_order AS ro
    JOIN JSON_TABLE(
             COALESCE(ro.device_ids, JSON_ARRAY()),
             '$[*]' COLUMNS (did BIGINT PATH '$')
         ) AS jt
    JOIN device_resource AS dr ON dr.id = jt.did
    WHERE ro.order_status IN :statuses
      AND ro.start_time >= :since
""").bindparams(bindparam("statuses", expanding=True))


async def get_device_idle_rate(db: AsyncSession, days: int = DEFAULT_DAYS) -> float:
    """
    设备闲置率 = (登记设备总数 - 窗口内被占用的设备数) / 登记设备总数 × 100

    口径（2026-09-27 随 device_ids 格式一并定型，临时开关 COUNT_MODE 已删除）：

    - 分母：`SUM(device_resource.total_count)`，登记设备【台数】。
      `total_count` 是 NOT NULL 列，SUM 不会漏行。
    - 分子：窗口内 `order_status IN (1, 2)` 的订单所引用设备的【去重 ID 数】，
      由 JSON_TABLE 在 SQL 层展开后 COUNT(DISTINCT)。
      3 已取消、4 已完成不占位，故不计入（口径 B：DEVICE_OCCUPIED_STATUS）。
      与场地使用率的口径差异只在「已完成(4)」，见文件顶部说明。
    - `device_ids` 为 `[]` 或 NULL 都表示没借设备，均计 0 台。
    - 仅保留 `device_resource` 中真实存在的 ID，防止脏数据虚增占用。
    - `device_status` 为 2(损坏) / 3(缺失配件) 的设备计入分母：代表它们不可用，
      反而推高闲置率，符合业务直觉。若评审认为不妥再改为排除。

    ⚠️ 量纲前提（尚未用真库确认）：分子按【ID 个数】计，分母按【total_count 之和】
    计，两者仅在「每行 total_count = 1」时严格同量纲。若某行 total_count > 1
    （如一行代表 4 台投影仪），借走该行只会计 1 台占用，闲置率会偏高。
    阶段 0 的 scripts/check_data.py 第 3 节专门输出「行数 vs SUM(total_count)」
    判定，届时核对；不等则需重新讨论分子口径。
    """
    since = datetime.now() - timedelta(days=days)

    # ---------- 分母：登记设备台数 ----------
    total_devices = (await db.execute(
        select(func.coalesce(func.sum(DeviceResource.total_count), 0))
    )).scalar() or 0
    # ⚠️ **必须转 float（2026-09-29 修）**：MySQL 的 `SUM()` 返回 **DECIMAL**，
    # 而 SQLite 的 `SUM()` 返回整数 —— 同一段代码在离线用例里算出 float、
    # 在真库上算出 Decimal，**离线测不出来**。后果两条，都不是小事：
    #
    #   1. `tests/test_all_stats_aggregate.py` 明确断言 `isinstance(..., float)`，
    #      在真库上会红；
    #   2. Decimal 会顺着 stats 一路传到 `dashboard_ai_service` 的 `json.dumps`，
    #      直接抛「Object of type Decimal is not JSON serializable」，被外层 except
    #      收成「走纯统计降级」—— **AI 报告整条链路静默失效**，
    #      页面上只剩规则模板拼的建议，而 `degraded=true` 又极易被误读成
    #      「模型不稳定」，定位成本极高（实测踩过）。
    total_devices = float(total_devices)
    if total_devices == 0:
        return 0.0

    # ---------- 分子：窗口内被占用的去重设备数 ----------
    used_count = (await db.execute(
        _OCCUPIED_DEVICE_COUNT_SQL,
        {"statuses": DEVICE_OCCUPIED_STATUS, "since": since},
    )).scalar() or 0

    # min 兜底：占用数不可能超过登记总数，防止脏数据算出负闲置率。
    # 正常数据不会触发；保留是为了让异常数据表现为「0% 闲置」而不是负值。
    used_count = min(int(used_count), int(total_devices))

    return round((1 - used_count / total_devices) * 100, 1)


# ============ 3. 预约高峰时段 ============
async def get_peak_hours(db: AsyncSession, days: int = DEFAULT_DAYS) -> list:
    """
    按小时统计预约次数，降序返回 [{hour, count}, ...]

    订单状态口径：SPACE_OCCUPIED_STATUS = [1, 2, 4]（同场地使用率）。
    理由：「高峰时段」反映的是预约活动热度，已完成的预约同样是真实发生过的活动，
    计入才能反映真实高峰；与场地使用率保持同一口径，两块图表才不会互相矛盾。
    """
    since = datetime.now() - timedelta(days=days)

    hour_col = func.hour(ReserveOrder.start_time).label("h")
    rows = (await db.execute(
        select(hour_col, func.count().label("c"))
        .where(
            ReserveOrder.order_status.in_(SPACE_OCCUPIED_STATUS),
            ReserveOrder.start_time >= since,
        )
        .group_by(hour_col)
        .order_by(func.count().desc())
    )).all()

    return [{"hour": int(r.h), "count": int(r.c)} for r in rows]


# ============ 4. 设备故障频次 ============
async def get_fault_frequency(db: AsyncSession, limit: int = 10) -> list:
    """每台设备的维修工单数，降序返回 [{deviceName, count}, ...]"""
    rows = (await db.execute(
        select(
            DeviceResource.device_name,
            func.count(RepairTicket.id).label("c"),
        )
        .join(RepairTicket, RepairTicket.device_id == DeviceResource.id)
        .group_by(DeviceResource.id, DeviceResource.device_name)
        .order_by(func.count(RepairTicket.id).desc())
        .limit(limit)
    )).all()

    return [{"deviceName": r.device_name, "count": int(r.c)} for r in rows]


# ============ 5. 聚合入口（对应 /stats 接口）============
async def get_all_stats(db: AsyncSession, days: int = DEFAULT_DAYS) -> dict:
    """严格按文档 5.3 模块 8 的数据契约返回"""
    return {
        "spaceUsageRate": await get_space_usage_rate(db, days),
        "deviceIdleRate": await get_device_idle_rate(db, days),
        "peakHours": await get_peak_hours(db, days),
        "faultFrequency": await get_fault_frequency(db),
    }


def empty_stats() -> dict:
    """
    四项统计的**零值占位**，供路由层在数据库不可达时降级返回（2026-09-28，原 B1 待办）。

    形状必须与 `get_all_stats` **完全一致**（同样的 key、同样的类型）——
    前端看到的 data 结构不能因为降级而变，否则它得写两套解析。
    `tests/test_all_stats_aggregate.py` 有一条断言逐字对比两者的 key。

    刻意**不含 `degraded`**：那个标志由「知道自己正在降级」的那一层（路由）追加，
    服务层不猜自己是不是降级。所以它与 `get_all_stats` 的差别只有数值，
    这也正是上面那条 key 对比能成立的原因。
    """
    return {
        "spaceUsageRate": 0.0,
        "deviceIdleRate": 0.0,
        "peakHours": [],
        "faultFrequency": [],
    }