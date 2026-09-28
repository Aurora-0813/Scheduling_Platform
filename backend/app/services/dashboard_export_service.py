"""
模块 8 - 报告导出（CSV）

《规范》5.3 的 `/report` 契约里 `exportUrl` 是要填的（`"exportUrl": "..."`），
阶段 3 落地本文件。

**为什么用标准库 `csv` 而不是 openpyxl/pandas**
《规范》3.6 锁定的依赖清单里没有任何 Excel/CSV 库，而 `aiofiles==24.1.0` 已在清单内。
为一个「把已知结构写成表格」的需求去新增依赖，收益不抵引入风险
（何况导出的是数据而非样式，xlsx 的优势用不上）。

**为什么是 utf-8-sig**
带 BOM。Excel 双击打开 UTF-8 无 BOM 的 CSV 会按 GBK 解码，中文变乱码 ——
这是「导出的报告自己看不了」的经典坑，而 utf-8-sig 对非 Excel 的解析器同样无害
（pandas、Python `csv` 都能正常读）。

**为什么 CSV 里的统计数字由调用方传入，而不是在这里重新查库**
`write_report_csv(stats, ...)` 的 `stats` 必须与生成 AI 建议时用的是**同一份**。
若在这里重新 `get_all_stats()`，两次取数之间若有写入，
就会出现「建议说 46.7%、导出表格写 48.2%」的自相矛盾报告。
"""
import csv
import io
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import aiofiles

logger = logging.getLogger(__name__)

# backend/ 目录（本文件在 backend/app/services/ 下）
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent

# 导出目录与对外 URL。
# ⚠️ STATIC_MOUNT_PATH 必须与 app/main.py 里 StaticFiles 的挂载点一致 ——
#    所以 main.py 直接 import 这个常量，而不是各自手写 "/static" 字符串。
#    （改一处而漏另一处，exportUrl 就会指向 404。）
STATIC_MOUNT_PATH = "/static"
EXPORT_URL_PREFIX = f"{STATIC_MOUNT_PATH}/exports"
EXPORT_DIR = BACKEND_DIR / "static" / "exports"

# 文件名里的时间戳格式（《规范》要求 dashboard_YYYYMMDD_HHMMSS.csv）
TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"

# ---------- 表头文案（中文，Excel 直接可读）----------
CSV_HEADERS = ("序号", "发现", "数据依据", "建议动作")

# ---------- 过期清理 ----------
# 导出目录**必须定时清理**：每生成一次报告就落一个文件，报错重试还会多落，
# 不清理则 `static/exports/` 无限堆积（答辩演示机长期不重启时尤其明显）。
#
# 保留时长（天）。改这一个数即可调整。
RETENTION_DAYS = 7

# 只清理本模块生成的文件的文件名模式 —— 防止误删同事因调试放进同目录的东西。
EXPORT_FILE_GLOB = "dashboard_*.csv"


def _is_expired(path: Path, now: datetime, retention_days: int) -> bool:
    """
    文件是否已过期（纯函数，便于单测 —— 不碰磁盘时间以外的东西）。

    以 **mtime** 为准而不是文件名里的时间戳：文件名时间戳是「报告对应的数据窗口」，
    mtime 是「文件何时被写下」。两者在正常路径下一致，
    但若有人手工复制/改名文件，mtime 才是它真正开始占用磁盘的时间。
    """
    age = now - datetime.fromtimestamp(path.stat().st_mtime)
    return age > timedelta(days=retention_days)


def cleanup_expired_exports(
    now: datetime | None = None,
    retention_days: int | None = None,
) -> int:
    """
    删除导出目录里过期的 CSV，返回**实际删除的文件数**。

    ⚠️ 刻意是**同步**函数：目录里最多几十个小文件，几次 `stat` / `unlink` 是微秒级，
    换来的是「`main.py` 的启动清理」与「导出时的惰性清理」两处都能直接调用，
    不必为一个删文件的动作引入线程池或 async 包装。
    若将来导出量级变大（单目录上千文件），再改成 `asyncio.to_thread`。

    `now` / `retention_days` 可注入，是为了让用例不必依赖真实时钟、
    也不必真的等 7 天（否则这条清理逻辑根本没法测）。

    本函数**不抛异常**：清理是后台维护动作，删不掉（权限、文件被占用）不该影响
    调用它的那条业务路径。真出问题时记 warning 并返回已删数量。
    """
    target_dir = EXPORT_DIR
    reference = now or datetime.now()
    days = RETENTION_DAYS if retention_days is None else retention_days

    if not target_dir.is_dir():
        return 0

    removed = 0
    for path in target_dir.glob(EXPORT_FILE_GLOB):
        try:
            if _is_expired(path, reference, days):
                path.unlink()
                removed += 1
        except OSError as e:
            # 单个文件删不掉（被 Excel 占用等）不该中断整轮清理
            logger.warning("report: 清理过期导出失败 %s: %s: %s",
                           path.name, type(e).__name__, e)

    if removed:
        logger.info("report: 已清理 %d 个过期导出（保留 %d 天）", removed, days)
    return removed


def _format_peak_hours(peak_hours) -> str:
    """`[{hour, count}]` → `14点:5次; 9点:3次`（空列表给一个明确的占位，不留空单元格）"""
    if not peak_hours:
        return "窗口内无预约"
    return "; ".join(f"{item.get('hour')}点:{item.get('count')}次" for item in peak_hours)


def _format_fault_frequency(fault_frequency) -> str:
    """`[{deviceName, count}]` → `投影仪A:3单; 设备2:1单`"""
    if not fault_frequency:
        return "窗口内无维修工单"
    return "; ".join(
        f"{item.get('deviceName')}:{item.get('count')}单" for item in fault_frequency
    )


def build_csv_text(stats: dict, suggestions, days: int, degraded: bool) -> str:
    """
    组装 CSV 文本（纯函数，便于单测 —— 不碰磁盘）。

    结构（两段之间用空行分隔，Excel 里是「两张表」的观感）：

        模块 8 - AI 数据洞察报告
        统计窗口(天),7
        生成时间,2026-09-27 19:45:00
        是否降级,否
        （空行）
        统计指标,数值
        场地使用率(%),46.7
        设备闲置率(%),20.0
        预约高峰时段,14点:5次; 9点:3次
        设备故障频次,投影仪A:3单
        （空行）
        序号,发现,数据依据,建议动作
        1,...,...,...
    """
    buffer = io.StringIO()
    # lineterminator="\n"：csv 默认写 \r\n，混进 utf-8-sig 后在部分 Linux 工具里
    # 会显示成 ^M。统一成 \n，Windows 的 Excel 也能正常打开。
    writer = csv.writer(buffer, lineterminator="\n")

    writer.writerow(["模块 8 - AI 数据洞察报告"])
    writer.writerow(["统计窗口(天)", days])
    writer.writerow(["生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    writer.writerow(["是否降级", "是" if degraded else "否"])
    writer.writerow([])

    # 四项统计：统计字段恰好四行（《规范》5.3 模块 8）
    writer.writerow(["统计指标", "数值"])
    writer.writerow(["场地使用率(%)", stats.get("spaceUsageRate")])
    writer.writerow(["设备闲置率(%)", stats.get("deviceIdleRate")])
    writer.writerow(["预约高峰时段", _format_peak_hours(stats.get("peakHours"))])
    writer.writerow(["设备故障频次", _format_fault_frequency(stats.get("faultFrequency"))])
    writer.writerow([])

    # AI 建议三要素（《规范》4.4 模块 8：缺一不可）
    writer.writerow(CSV_HEADERS)
    for index, item in enumerate(suggestions or (), start=1):
        writer.writerow([
            index,
            item.get("finding", ""),
            item.get("evidence", ""),
            item.get("suggestion", ""),
        ])

    return buffer.getvalue()


async def write_report_csv(
    stats: dict,
    suggestions,
    days: int,
    degraded: bool = False,
) -> str:
    """
    写出 CSV 并返回**相对 URL**（如 `/static/exports/dashboard_20260927_194500.csv`）。

    返回相对路径而非绝对地址，是为了不让后端把自己的域名写进响应体 ——
    前端部署到哪个域名、Nginx 怎么反代都由前端一侧决定
    （前端用 `resolveExportUrl()` 还原，见 frontend/src/api/dashboard.js）。

    失败时**向上抛**，由调用方（`generate_report`）兜住并把 exportUrl 置 null：
    导出失败不该让整个报告失败，但也不该悄悄吞掉 —— 调用方会记 warning。

    **惰性清理**：写之前先顺手清一次过期文件（见 `cleanup_expired_exports`）。
    顺序是先清后写 —— 新文件在清理之后才出现，任何保留时长下都不会被本轮误删。

    `cleanup_expired_exports` 自身已经吞掉了单文件的失败，这里仍再包一层 try：
    它的「不抛异常」是靠内部实现维持的承诺，而**导出才是这条路径的目的**。
    多这三行，是为了让「某人将来在清理里加了一句会抛的代码」不至于把导出带崩 ——
    E15 就是这条意图的哨兵（它注入一个必抛的清理函数，断言导出照常成功）。
    """
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        cleanup_expired_exports()
    except Exception as e:
        logger.warning("report: 清理过期导出失败，跳过（不影响本次导出）: %s: %s",
                       type(e).__name__, e)

    filename = f"dashboard_{datetime.now().strftime(TIMESTAMP_FORMAT)}.csv"
    file_path = EXPORT_DIR / filename

    text = build_csv_text(stats, suggestions, days, degraded)

    # utf-8-sig：带 BOM，Excel 打开中文不乱码（见文件头说明）
    async with aiofiles.open(file_path, "w", encoding="utf-8-sig", newline="") as handle:
        await handle.write(text)

    logger.info("report: 已导出 CSV %s（%d 字节）", filename, os.path.getsize(file_path))
    return f"{EXPORT_URL_PREFIX}/{filename}"
