"""
Schema 公共基类

开发流程.md 6.2：数据库表名字段名用 snake_case，API 传输字段用 camelCase。
统一由 alias_generator 完成转换，避免每个字段手写 alias 漏改。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """
    出入参基类：Python 侧写 snake_case，JSON 侧自动收发 camelCase。

    populate_by_name 让两种写法都能构造（测试里用 snake_case 更顺手），
    from_attributes 支持直接从 ORM 对象构造响应。
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )
