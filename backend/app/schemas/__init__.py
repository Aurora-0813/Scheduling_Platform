"""
接口出入参模型（Pydantic）

按模块拆分：`base`（分页）、`common`（统一响应体）、`auth`（模块 9）、
`monitor`（模块 10）。其它模块（1~8）的 schema 由各自负责人按同样约定新增。

约定（详见 app/core/camel.py 的模块说明）：
- 一律继承 `CamelModel`，API 字段名自动转 camelCase；
- 时间字段用 `DateTimeStr`，金额字段用 `MoneyStr`，不要用裸 `datetime`/`Decimal`。

本文件刻意不 re-export 各子模块：`schemas.auth` 里的名字与其它模块的同名
schema（例如多个模块都要 `PageOut`）容易冲突，显式写全路径更不容易出错。
"""
