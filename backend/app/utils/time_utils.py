"""
时间处理工具

项目文档 5.1 规定接口时间格式统一为 `YYYY-MM-DD HH:mm:ss`。

时区约定（重要）
----------------
全链路统一使用**本地时间（Asia/Shanghai）的 naive datetime**，不使用带时区的
datetime，数据库 `DATETIME` 列也不带时区。理由：

- 云库的 `@@global.time_zone` 与开发机时区可能不同，若混用 UTC 与本地时间，
  会出现「预约时间差 8 小时」这类直到联调最后一天才发现的 bug。
- 统一走本模块的 `now()`，禁止在业务代码中散落 `datetime.utcnow()`。

注意：本模块是格式常量的唯一定义处，其他模块（含 app/core/camel.py）
一律从这里导入，不要重复定义。
"""

from __future__ import annotations

from datetime import datetime

# 接口统一时间格式（项目文档 5.1）
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# 入库解析时可接受的额外格式
_ACCEPTED_INPUT_FORMATS = (
    DATETIME_FORMAT,
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


def now() -> datetime:
    """
    获取当前本地时间（naive）。

    业务代码一律使用本函数，禁止直接调用 `datetime.utcnow()`。
    """
    return datetime.now()


def format_datetime(value: datetime | None) -> str | None:
    """把 datetime 格式化为 `YYYY-MM-DD HH:mm:ss`。None 原样返回。"""
    if value is None:
        return None
    return value.strftime(DATETIME_FORMAT)


def parse_datetime(value: str | datetime | None) -> datetime | None:
    """
    解析时间字符串为 naive datetime。

    依次尝试 `YYYY-MM-DD HH:mm:ss`、ISO 8601（带 T）、`YYYY-MM-DD HH:mm`、
    `YYYY-MM-DD`。全部失败时返回 None，由调用方决定如何报错。
    """
    if value is None or isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None

    text = value.strip()
    # 统一把 ISO 的 T 分隔符归一，便于后续按空格格式解析
    for fmt in _ACCEPTED_INPUT_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None
