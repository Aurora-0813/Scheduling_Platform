"""
通用分页模型（API 层入口）

分页的**实现**放在 `app/utils/pagination.py`，因为它是全组共享件：
模块 3/5/6/8 的 services 层也要用它构造分页结果，而 services 层不应该依赖
`app/schemas`（那是接口层的目录）。本模块只是把它转发到接口层的导入路径上，
让 router 写 `from app.schemas.base import PageParams` 时不必关心实现位置。
"""

from __future__ import annotations

from app.utils.pagination import PageParams, PageResult

__all__ = ["PageParams", "PageResult"]
