"""时间解析与格式化（§5.1：时间统一 `YYYY-MM-DD HH:mm:ss`）。"""

from datetime import datetime, time

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_time(s: str) -> datetime:
    """解析 `YYYY-MM-DD HH:mm:ss`，失败抛 ValueError。"""
    try:
        return datetime.strptime(s, TIME_FORMAT)
    except (ValueError, TypeError):
        # `from None` 是刻意的：原始异常（`time data '...' does not match format`）会把
        # 用户输入的字面量原样带进 traceback，而这里要给的是一句**面向用户**的提示
        # （§5.1 的时间格式约定），调用方的 `invalid_param` 分支只转发这一句。
        raise ValueError("时间格式应为 YYYY-MM-DD HH:mm:ss") from None


def format_time(dt: datetime | None) -> str | None:
    return dt.strftime(TIME_FORMAT) if dt else None


def format_clock(t: time | None) -> str | None:
    return t.strftime("%H:%M:%S") if t else None
