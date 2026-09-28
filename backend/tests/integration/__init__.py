"""需要外部依赖或独立进程的测试。

与 `tests/unit`、`tests/api` 的区别：
- `test_migrations.py` 通过 subprocess 驱动 alembic，落在临时 SQLite 库上（离线）；
  「连云库实测」不属于自动化测试范围，步骤见 docs/deploy.md。
- `test_auth_flow_db.py` 走 SQLite 内存库的真实读写路径，验证服务层显式 commit。
"""
