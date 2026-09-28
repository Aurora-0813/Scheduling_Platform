"""
snake_case ↔ camelCase 转换与自定义字段类型

为什么用 Pydantic `alias_generator` 而不是中间件
-----------------------------------------------
项目文档 6.2 要求「API 传输字段 camelCase」，而 ORM 模型是 snake_case
（文档 6.3 的表结构）。可选方案有三种，本项目选定 `CamelModel`：

1. **中间件重写请求体** —— 否决。multipart/form-data 的二进制体若要在中间件里
   解析，必须先整段读入内存，模块 1（语音）、模块 2（图像）上传时并发几个请求
   就会 OOM；且会破坏模块 4 Agent 的 SSE 流式响应。
2. **逐字段写 alias** —— 否决。字段多、易漏，改动一处忘一处。
3. **`alias_generator` + `populate_by_name`** —— 采用。零运行时开销、
   对上传与 SSE 完全透明，唯一代价是手写 dict 返回处必须显式 `by_alias=True`
   （统一响应体已封装，见 app/core/response.py）。

使用要点
--------
- 所有请求/响应模型继承 `CamelModel`。
- 出参一律走统一响应体 `ApiResponse`，它内部保证 `by_alias=True`，
  避免出现「成功响应是 accessToken、错误响应变 access_token」这种只在前端
  报错时才暴露的问题。
- 时间字段用 `DateTimeStr`，金额字段用 `MoneyStr`，不要用裸 `datetime` /
  `Decimal`，否则格式会退化为 ISO8601（带 T）与不定小数位。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer
from pydantic.alias_generators import to_camel

from app.utils.time_utils import DATETIME_FORMAT, format_datetime, parse_datetime

__all__ = [
    "CamelModel",
    "DateTimeStr",
    "MoneyStr",
    "DATETIME_FORMAT",
    "to_camel_alias",
]


def to_camel_alias(field_name: str) -> str:
    """字段名 snake_case → camelCase。用于需要手动转换的场合。"""
    return to_camel(field_name)


class CamelModel(BaseModel):
    """
    全部请求/响应模型的基类。

    - `alias_generator=to_camel`：序列化时字段名转 camelCase。
    - `populate_by_name=True`：反序列化时 camelCase 与 snake_case 都接受，
      内部代码与测试可以直接用 snake_case 构造，减少噪音。
    - `from_attributes=True`：允许直接由 ORM 对象构造响应模型。
    - `extra="ignore"`：忽略未知字段，避免前端多传一个字段就报 400。

    刻意**未开启** `str_strip_whitespace`：它会无差别去掉所有字符串字段的
    首尾空格，包括密码。用户密码若是 " abc123 " 会被静默改成 "abc123"，
    登录时输入同样的字符串却校验失败，排查成本极高。需要去空格的字段
    （如 username）在对应 schema 里单独声明。
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="ignore",
    )


def _parse_datetime_input(value: Any) -> Any:
    """
    入参时间解析：接受 `YYYY-MM-DD HH:mm:ss` 等常见格式。

    解析失败时把原值原样返回，交给 Pydantic 抛出标准的类型错误
    （这样错误信息里仍会带上字段名，前端提示完整）。
    """
    if isinstance(value, str):
        parsed = parse_datetime(value)
        return parsed if parsed is not None else value
    return value


# 时间字段类型：进出都是 `YYYY-MM-DD HH:mm:ss`（项目文档 5.1）
#
# when_used="json" 是关键：只在 JSON 序列化（即接口出参）时转字符串，
# Python 模式下仍是 datetime 对象。若不加此参数，`model_dump()` 也会转成
# 字符串，用它去写库时会污染 DATETIME 列。
DateTimeStr = Annotated[
    datetime,
    BeforeValidator(_parse_datetime_input),
    PlainSerializer(format_datetime, return_type=str, when_used="json"),
]


def _format_money(value: Decimal) -> str:
    """金额统一保留 2 位小数的字符串，避免浮点误差。"""
    return f"{value:.2f}"


# 金额字段类型（对应文档 6.3 的 DECIMAL(10,2) 列）
#
# 输出为**字符串**而非数字：DECIMAL(10,2) 用 JSON number 表示会经过
# IEEE754 双精度，980.10 可能变成 980.0999999999999。前端如需参与计算，
# 请先 Number(x) 转换。此约定已写入 docs/api.md。
MoneyStr = Annotated[
    Decimal,
    PlainSerializer(_format_money, return_type=str, when_used="json"),
]
