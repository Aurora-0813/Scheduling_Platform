"""测试公共辅助：身份常量与时间构造（§5.1 时间统一 `YYYY-MM-DD HH:mm:ss`）。"""
from datetime import datetime, timedelta

# 演示阶段 mock 用户（deps.py 默认兜底），身份由 X-User-Id 头模拟
MOCK_USER_ID = 1
# 另一用户，用于越权类用例
OTHER_USER_ID = 2

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def time_dt(days: int = 1, hour: int = 9, minute: int = 0) -> datetime:
    """构造相对当前时间的整点 datetime（默认明天 09:00）。"""
    return (datetime.now() + timedelta(days=days)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )


def time_str(days: int = 1, hour: int = 9, minute: int = 0) -> str:
    """构造接口用的时间字符串（默认明天 09:00）。"""
    return time_dt(days, hour, minute).strftime(TIME_FORMAT)
