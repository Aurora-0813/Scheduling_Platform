"""asyncmy + `pool_pre_ping` 兼容补丁的回归保护。

`app/core/database.py::patch_asyncmy_ping` 只在连真库（`mysql+asyncmy`）时生效，
而用例默认跑在临时 SQLite 上——走的是另一套 `do_ping`。所以「80 个用例全绿」
并不代表真库能跑：2026-09-25 在云库上就踩到「同一接口 200/500 交替」，
根因是复用连接时 `pool_pre_ping` 必炸。本文件把那条路径固化成断言。

不连任何真库：用假驱动连接驱动**真实的**包装器与**真实的**方言 `do_ping`
（触发链与修法见 `patch_asyncmy_ping` 的注释）。
"""
import inspect
import os
import pathlib
import subprocess
import sys

import pytest

pytest.importorskip("asyncmy", reason="补丁只与 mysql+asyncmy 这条路径有关")

from sqlalchemy.dialects.mysql.asyncmy import (  # noqa: E402
    AsyncAdapt_asyncmy_connection,
    MySQLDialect_asyncmy,
)
from sqlalchemy.util import greenlet_spawn  # noqa: E402

from app.core.database import patch_asyncmy_ping  # noqa: E402

# 本文件位于 tests/module3/，上溯三层才是 backend/（用例下沉一层后此处曾算错）
BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent.parent


class _FakeDbapi:
    """占位 DBAPI：只在包装器的异常适配路径上被引用，本文件走不到。"""

    class InternalError(Exception):
        pass


class _FakeDriverConnection:
    """asyncmy 驱动的替身，只实现包装器真正会碰到的那一个方法。"""

    def __init__(self):
        self.pinged_with: list[bool] = []

    async def ping(self, reconnect):
        self.pinged_with.append(reconnect)


def _make_wrapper():
    """真实的 asyncmy 连接包装器 + 假驱动，避免用例依赖真库。"""
    driver = _FakeDriverConnection()
    return AsyncAdapt_asyncmy_connection(_FakeDbapi(), driver), driver


# ------------------------------------------------------------ 调用链


async def test_do_ping_reaches_driver_through_real_wrapper():
    """复现 `pool_pre_ping` 的调用：方言 `do_ping` → 包装器 `ping` → 驱动 `ping`。

    缺了补丁这里会抛
    `TypeError: ...ping() missing 1 required positional argument: 'reconnect'`
    ——正是真库上 200/500 交替的根因（新连接不 ping、复用连接必炸）。
    """
    patch_asyncmy_ping()  # 幂等：模块导入时已打过，这里只保证状态
    conn, driver = _make_wrapper()

    assert await greenlet_spawn(MySQLDialect_asyncmy().do_ping, conn) is True
    assert driver.pinged_with == [False], "ping 应真的下到驱动"


def test_ping_accepts_both_sqlalchemy_calling_conventions():
    """方言按 PyMySQL 的签名二选一调用，两种形式都必须接得住。

    `_send_false_to_ping` 依据 **PyMySQL** 的 `Connection.ping` 签名决定传不传参
    （`reconnect` 的默认值被改过）。锁定版本下判定为无参调用，即当前回归；
    日后升级 PyMySQL 可能翻成 `ping(False)`，那时也不能坏。
    """
    patch_asyncmy_ping()
    signature = inspect.signature(AsyncAdapt_asyncmy_connection.ping)
    stub_self = object()

    signature.bind(stub_self)  # do_ping 的无参分支
    signature.bind(stub_self, False)  # do_ping 的传参分支


async def test_reconnect_true_is_still_rejected():
    """补丁只补默认值，不打开自动重连：`reconnect=True` 仍须被拒。

    包装器里是 `assert not reconnect`。若有人把默认值改成 True，驱动会悄悄
    重建死连接，`pool_pre_ping` 的检查就失去意义了。
    """
    patch_asyncmy_ping()
    conn, _ = _make_wrapper()

    with pytest.raises(AssertionError):
        await greenlet_spawn(conn.ping, True)


def test_patch_is_idempotent():
    """重复调用不得层层包裹（模块导入与用例各调一次是常态）。"""
    patch_asyncmy_ping()
    once = AsyncAdapt_asyncmy_connection.ping
    patch_asyncmy_ping()

    assert AsyncAdapt_asyncmy_connection.ping is once


# ------------------------------------------------------------ 导入时的接线


_PROBE = """
import inspect

import app.core.database  # noqa: F401  导入即触发补丁接线
from sqlalchemy.dialects.mysql.asyncmy import (
    AsyncAdapt_asyncmy_connection as C,
)

try:
    inspect.signature(C.ping).bind(object())  # 允许无参 ping()
    print("no_arg_ping=True")
except TypeError:
    print("no_arg_ping=False")
"""


def _probe_with(database_url: str) -> bool:
    """另起解释器导入 `app.core.database`，问它「包装器接不接受无参 ping」。"""
    env = dict(
        os.environ,
        DATABASE_URL=database_url,
        PYTHONIOENCODING="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert result.returncode == 0, f"探测子进程失败：\n{result.stderr}"
    return "no_arg_ping=True" in result.stdout


def test_patch_is_wired_on_mysql_url():
    """连真库的配置下，导入 `app.core.database` 必须自动装上补丁。

    本进程是按 SQLite 配置导入的，测不到这条接线，只能另起解释器。
    """
    assert _probe_with("mysql+asyncmy://u:p@127.0.0.1:3306/probe_db") is True


def test_patch_is_skipped_on_sqlite_url():
    """自测用的 SQLite 配置不得改动 asyncmy 的包装器（守 guard 的边界）。"""
    assert _probe_with("sqlite+aiosqlite:///./probe.db") is False
