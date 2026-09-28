"""
分页出参与入参

出参结构（camelCase）
---------------------
    {"page": 1, "pageSize": 10, "total": 57, "items": [...]}

命名为 `items` 而非 `list`：`list` 是 Python 内置类型名，作为字段名会让
类体内的类型标注 `list[T]` 自己引用自己，是个持续的坑。

入参结构中 `pageSize` 用 alias 声明，因此请求必须是
`?page=1&pageSize=10`（snake_case 的 `page_size` 不会被识别）。
这是项目文档 6.2「API 传输字段 camelCase」的自然延伸。
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from fastapi import Query
from fastapi.params import Query as QueryParam

from app.core.camel import CamelModel

__all__ = ["PageParams", "PageResult", "DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE"]

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100

T = TypeVar("T")


def _unwrap_query_default(value: Any, fallback: int) -> int:
    """
    把 FastAPI 的 `Query(...)` 默认值还原成真实整数。

    为什么需要这一步：以 `Depends()` 方式注入时，FastAPI 会解析 `__init__`
    签名并把 `Query` 默认值换成从查询串取到的真实值，此时 `page` 已是 int。
    但**直接构造** `PageParams()`（测试、服务层内部调用、`PageResult.create`）
    不走 FastAPI，属性里存的就是 `Query` 对象本身，后续 `params.offset`
    会算出类型错误的结果。这里统一兜住，让两种用法行为一致。

    注意用 `fastapi.params.Query`（类）判断：`fastapi.Query` 是工厂**函数**，
    `isinstance(x, fastapi.Query)` 会抛 TypeError。
    """
    if isinstance(value, QueryParam):
        default = value.default
        if default is None or default is Ellipsis:
            return fallback
        return int(default)
    return int(value)


class PageParams:
    """
    分页入参依赖。

    用法：`params: PageParams = Depends()`，然后用 `params.offset` / `params.limit`
    拼 SQL 的 OFFSET/LIMIT。也可以直接 `PageParams(page=2, page_size=20)` 构造。
    """

    def __init__(
        self,
        page: int = Query(1, ge=1, description="页码，从 1 开始"),
        page_size: int = Query(
            DEFAULT_PAGE_SIZE,
            ge=1,
            le=MAX_PAGE_SIZE,
            alias="pageSize",
            description=f"每页条数，1~{MAX_PAGE_SIZE}",
        ),
    ) -> None:
        self.page = _unwrap_query_default(page, 1)
        self.page_size = _unwrap_query_default(page_size, DEFAULT_PAGE_SIZE)

    @property
    def offset(self) -> int:
        """SQL OFFSET。"""
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        """SQL LIMIT。"""
        return self.page_size

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"PageParams(page={self.page}, page_size={self.page_size})"


class PageResult(CamelModel, Generic[T]):
    """分页出参。"""

    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    total: int = 0
    items: list[T] = []

    @classmethod
    def create(cls, items: list[Any], total: int, params: PageParams) -> PageResult[Any]:
        """由查询结果与总数构造分页出参。"""
        return cls(page=params.page, page_size=params.page_size, total=total, items=items)

    @property
    def total_pages(self) -> int:
        """总页数（向上取整，空结果时为 0）。"""
        if self.page_size <= 0 or self.total <= 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size
