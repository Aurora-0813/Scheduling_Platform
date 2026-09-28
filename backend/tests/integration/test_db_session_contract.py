"""
数据库会话契约测试（模块 10 的基建约定）

被测对象：`app/core/database.py` 的 `get_db()`。

它是本项目最容易踩、**踩了不会报错**的一个坑（决策 11）：

    `get_db` 只负责「异常回滚 + 关闭会话」，**不负责提交**。
    提交必须由 `services/` 层在业务结尾显式 `await session.commit()`。

忘记提交的后果是「接口返回 200、日志里没有任何异常、数据没落库」，
表现为「刚创建的预约刷新一下就不见了 / 强制下线的账号重新登录又活了」。
这类缺陷一旦进到演示环境，排查成本极高，因此必须有测试盯着。

为什么不能靠认证接口的用例覆盖
------------------------------
`app/services/auth_service.py` 整条链路**不写库**（登录只读、续期只读、
登出只动 Redis），所以认证测试无论如何覆盖不到事务边界。本文件直接驱动
`get_db`，用「未提交的写入在**另一个连接**里查不到」这个可观测后果把它钉死。

为什么不用 conftest 的 `client`
-------------------------------
接口测试里 `get_db` 被 `app.dependency_overrides` 换成了测试自己的会话工厂
（见 `tests/conftest.py` 的 `make_application`）。那份覆盖必须复制一遍
「关闭 / 回滚」逻辑（它要保证每个请求一个新会话），于是**生产的 `get_db`
本体一次都没被执行到** —— 生产代码里加了 `commit()` 也不会有任何用例失败。
这里改为 monkeypatch `get_db` 依赖的 `AsyncSessionLocal`，让本体真的跑起来。

（观察用的连接来自 conftest 的 `engine` 夹具：**另一个引擎、另一条连接**。
 用同一个会话去验证「提交了没有」是无效的 —— 未提交的数据在自己会话里
 一定看得到，这正是「测试全绿、线上丢数据」的来源。）
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core import database as database_module
from app.models.system import SysRole

pytestmark = pytest.mark.db


class _RollbackRecordingSession(AsyncSession):
    """记录 `rollback()` 调用次数的会话。

    「未提交的写入没落库」既可能因为回滚，也可能因为会话只是被关掉。
    两种情形对业务的影响不同（后者说明异常分支没跑），所以把回滚本身
    也断言下来 —— 用行为（数据在不在）是无法区分它们的。
    """

    rollback_calls = 0

    async def rollback(self) -> None:
        type(self).rollback_calls += 1
        await super().rollback()


@asynccontextmanager
async def request_session() -> AsyncIterator[AsyncSession]:
    """
    像 FastAPI 那样驱动一次 `get_db`。

    FastAPI 用 `contextlib.asynccontextmanager` 包装 yield 依赖，于是有两条路径：

    - 正常结束 → `aclose()`（在 yield 处抛 `GeneratorExit`）；
    - 接口抛异常 → `athrow(exc)`，`get_db` 里的 `except` 分支才会执行。

    这里逐字复刻这两条路径。若只调 `aclose()`，`get_db` 的回滚分支永远不会
    被执行到，用例会得出「回滚没发生」的假结论（`GeneratorExit` 是
    `BaseException`，`except Exception` 捕不到它）。
    """
    generator = database_module.get_db()
    session = await anext(generator)
    try:
        yield session
    except BaseException as exc:
        # 必须捕 BaseException：GeneratorExit / CancelledError 都不在 Exception 之下，
        # 只会捕 Exception 的话，取消路径根本走不进来（也就无法复刻生产行为）
        try:
            # 生成器会把同一个异常再抛回来（get_db 里是 `raise` 原样抛出），
            # 这里吞掉它，由下一行的 `raise` 保持原有异常语义
            await generator.athrow(exc)
        except BaseException:  # noqa: BLE001 - 同上
            pass
        raise
    else:
        await generator.aclose()


@pytest.fixture
async def app_side(
    monkeypatch: pytest.MonkeyPatch,
    db_path: str,
    # 依赖 engine 只为**排序**：必须先由它建好表，这里才有表可写。
    # 用不到它的引擎（观察用的连接由用例自己声明），因此函数体不使用该参数
    # （pytest 靠参数名解析夹具，不能改名为 _engine）。
    engine: AsyncEngine,
) -> AsyncGenerator[AsyncEngine, None]:
    """
    把生产代码使用的 `AsyncSessionLocal` 换成指向测试库的会话工厂。

    会话类换成 `_RollbackRecordingSession`（只是为了能断言回滚），其余参数与
    `app/core/database.py` 中的保持一致（`expire_on_commit=False`、
    `autoflush=False`），否则测的就不是同一种会话行为了。
    """
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        poolclass=NullPool,
        connect_args={"check_same_thread": False},
    )
    factory = async_sessionmaker(
        engine,
        class_=_RollbackRecordingSession,
        expire_on_commit=False,
        autoflush=False,
    )
    _RollbackRecordingSession.rollback_calls = 0
    monkeypatch.setattr(database_module, "AsyncSessionLocal", factory)
    try:
        yield engine
    finally:
        await engine.dispose()


async def _role_names(engine: AsyncEngine, pattern: str) -> list[str]:
    """用**另一个引擎的连接**去查角色名，作为「数据到底落库了没有」的证据。"""
    async with engine.connect() as connection:
        result = await connection.execute(
            select(SysRole.role_name).where(SysRole.role_name.like(pattern))
        )
        return list(result.scalars())


# ==========================================================================
# 核心约定：不提交
# ==========================================================================
async def test_uncommitted_write_is_invisible_to_other_connections(
    app_side: AsyncEngine, engine: AsyncEngine
) -> None:
    """
    `get_db` **不会**替服务层提交 —— 这是决策 11 的核心。

    三步递进，任何一步失败都说明事务边界被改坏了：

    1. `flush()` 之后 INSERT 真的下发了（主键已由 SQLite 赋值），
       但**别的连接看不到** → 说明没有隐式提交；
    2. 请求结束（会话关闭）后仍然看不到 → 说明关闭 = 回滚，而不是提交；
    3. 若有人给 `get_db` 加了 `commit()`，第 2 步会看到 `ghost` 而失败。
    """
    async with request_session() as session:
        # 断言生产 `get_db` 本体跑起来了：会话是它用我们的工厂造出来的
        assert isinstance(session, _RollbackRecordingSession)

        ghost = SysRole(role_name="ghost", permissions=[])
        session.add(ghost)
        await session.flush()  # 不 flush 的话连 SQL 都没发出去，测不到东西
        assert ghost.id is not None, "flush 后应已下发 INSERT 并拿回主键"

        assert await _role_names(engine, "ghost%") == [], (
            "未提交的写入被别的连接看到了 —— 事务没有真正隔离，说明会话处于自动提交模式"
        )

    assert await _role_names(engine, "ghost%") == [], (
        "会话关闭后未提交的写入竟然落库了 —— get_db 是不是被改成了自动提交？"
        "（决策 11：提交必须由 services/ 层显式完成）"
    )


async def test_explicit_commit_is_what_persists(app_side: AsyncEngine, engine: AsyncEngine) -> None:
    """服务层显式 `await session.commit()` 之后，数据才对别的连接可见。"""
    async with request_session() as session:
        session.add(SysRole(role_name="keeper", permissions=[]))
        # ↓ 这一行就是 services/ 层必须自己写的那句
        await session.commit()

    assert await _role_names(engine, "keeper") == ["keeper"]


# ==========================================================================
# 异常路径
# ==========================================================================
async def test_exception_rolls_back_and_is_not_swallowed(
    app_side: AsyncEngine, engine: AsyncEngine
) -> None:
    """
    业务异常：先回滚，再把异常**原样抛出去**。

    吞掉异常比不提交更危险 —— 接口会返回 200，前端以为成功。
    因此这里同时断言「回滚发生了」与「异常没被吃掉」。
    """

    class _Boom(RuntimeError):
        """模拟 services/ 层的业务校验失败。"""

    with pytest.raises(_Boom):
        async with request_session() as session:
            session.add(SysRole(role_name="doomed", permissions=[]))
            await session.flush()
            raise _Boom("业务校验失败")

    assert _RollbackRecordingSession.rollback_calls == 1, "异常路径必须回滚一次"
    assert await _role_names(engine, "doomed") == []


async def test_cancellation_discards_the_write_without_using_the_except_branch(
    app_side: AsyncEngine, engine: AsyncEngine
) -> None:
    """
    客户端断连 / `--reload` 重启 → `asyncio.CancelledError`（`BaseException` 子类）。

    这里要把「**安全**」与「**走了哪个分支**」分开看，两者并不相同（实测确认）：

    - **安全**：未提交的写入最终没有落库。兜底者是 `AsyncSession.close()` ——
      关闭连接时 SQLAlchemy 会回滚该连接上未结束的事务，不会把半截事务
      还回连接池（MySQL 上同理，池的 `reset_on_return` 也是回滚）。
    - **分支**：`get_db` 里的 `except Exception` **不会**被 `CancelledError` 命中
      （Python 3.8 起它继承 `BaseException`），所以 `rollback_calls` 是 0：
      显式回滚只属于 `Exception` 那条路径。

    因此本用例分别钉两件事：有人把取消路径上的 `close()` 换成 `commit()`
    （安全被破坏）会失败；有人以为取消路径会走 except 分支也不会再被误导。
    """
    with pytest.raises(asyncio.CancelledError):
        async with request_session() as session:
            session.add(SysRole(role_name="cancelled", permissions=[]))
            await session.flush()
            raise asyncio.CancelledError

    assert _RollbackRecordingSession.rollback_calls == 0, (
        "取消路径居然走了 get_db 的 except 分支 —— 该分支是否被改成了 "
        "`except BaseException`？若确实改宽了，请同步更新本用例与 "
        "app/core/database.py 的说明（当前契约是：只有 Exception 才显式回滚）。"
    )
    assert await _role_names(engine, "cancelled") == [], (
        "取消路径的写入竟然落库了 —— 未提交事务的兜底回滚是否被破坏？"
    )


# ==========================================================================
# 请求隔离
# ==========================================================================
async def test_each_request_gets_its_own_session(app_side: AsyncEngine) -> None:
    """
    每次调用产出**不同**的会话，且各自的未提交数据互不可见。

    共用会话（例如把会话挂在模块级变量上）是性能上的小聪明，代价是
    「A 请求未提交的写入被 B 请求读到，B 顺手 commit 就替 A 提交了」——
    事务边界从此说不清。这里把它钉住。
    """
    async with request_session() as first, request_session() as second:
        assert first is not second

        first.add(SysRole(role_name="only-in-first", permissions=[]))
        await first.flush()

        found = await second.execute(select(SysRole.id).where(SysRole.role_name == "only-in-first"))
        assert found.scalar_one_or_none() is None, "两个请求的会话不应共享事务"
