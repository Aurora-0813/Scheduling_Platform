"""时间解析与格式化（§5.1：时间统一 `YYYY-MM-DD HH:mm:ss`）。"""
from datetime import datetime, time

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_time(s: str) -> datetime:
    """解析 `YYYY-MM-DD HH:mm:ss`，失败抛 ValueError。"""
    try:
        return datetime.strptime(s, TIME_FORMAT)
    except (ValueError, TypeError):
        raise ValueError("时间格式应为 YYYY-MM-DD HH:mm:ss")


def format_time(dt: datetime | None) -> str | None:
    return dt.strftime(TIME_FORMAT) if dt else None


def format_clock(t: time | None) -> str | None:
    return t.strftime("%H:%M:%S") if t else None
