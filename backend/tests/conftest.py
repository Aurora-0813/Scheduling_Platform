"""
pytest 全局夹具
===============

本文件是全后端的公共夹具入口（模块 1/2/4/9/10 共用），分三段：

1. 上方到「模块 1 / 模块 2 合并引入的夹具」之前 —— 基础支撑的通用夹具
   （SQLite 引擎、`db_session`、令牌白名单、指标存储、HTTP 客户端、登录助手）；
2. 「模块 1 / 模块 2 合并引入的夹具」段 —— 模块 2 的图片与假模型夹具；
3. 文件末尾 —— 模块 4 核心调度 Agent 的假模型夹具（`agent_fake_llm`）。

**模块 4 的假 LLM 选型结论**：`tests/smoke_fake_llm.py`（可独立运行，结论见
`docs/test.md` 第二节）——实测 langchain-core 1.6.4 下
`FakeMessagesListChatModel` 与 `GenericFakeChatModel` 都**没有**实现 `bind_tools`，
挂到 `create_agent` 上直接抛 `NotImplementedError`，阶段 7 §3.1 给的示例夹具**不可用**，
必须自实现一个 `bind_tools` 返回 `self` 的 `BaseChatModel` 子类
（即下方 `StubChatModel`）。阶段 7 的夹具与用例见 `docs/spec/stage-07-testing.md`。

整体策略（决策 8）
------------------
云库 MySQL 与 Redis 在当前环境**都不可达**，真库联调必须由人在隧道里做。
因此自动化测试全部离线：SQLite 临时文件库 + 假 Redis + 内存令牌白名单。
这份夹具的目标是「**尽量贴近生产行为**」，而不是「跑得快就行」——
凡是能真实执行的生产代码路径，就不要用替身绕过：

| 生产组件            | 测试替身                                | 为什么不留着真件        |
| ------------------- | --------------------------------------- | ----------------------- |
| MySQL（asyncmy）     | SQLite 临时文件库 + aiosqlite            | 云库不可达              |
| Redis（redis-py）    | `RedisTokenStore` 跑在 `FakeRedis` 上    | 无 Redis 服务           |
| 令牌白名单           | `InMemoryTokenStore`（生产降级实现）      | Redis 不可用时的真实路径 |
| Agent 指标           | `InMemoryMetricStore`（生产降级实现）     | 同上                    |

注意上表右列：`InMemoryTokenStore` 与 `InMemoryMetricStore` **本身就是生产
代码里的降级实现**（决策 7），不是为测试造的假货。只有 `FakeRedis` 是纯替身，
它存在的意义是让 `RedisTokenStore` 这个**生产实现**也能被真正执行到
（见 tests/unit/test_token_store.py 的说明）。

两个刻意的取舍
--------------
1. **临时文件库，不是 `:memory:`**。内存库必须配 `StaticPool`（所有会话共用
   一个连接），而共用连接意味着「未提交的数据在另一个会话里也看得到」——
   `services/` 层忘记 `await session.commit()` 这种最危险的缺陷就测不出来。
   用文件库 + `NullPool`，每个会话拿到独立连接，提交与否是**真实**可见的。
2. **应用会话与测试会话是两个引擎**。应用侧按生产逻辑「每个请求一个新会话、
   正常事务」；测试侧用 `AUTOCOMMIT` 引擎只做「造数据 / 查证据」，读完即走，
   不长时间持有 SQLite 的读锁（否则并发写会撞 `database is locked`）。

SQLite 与云库的差异（**已知且有意忽略**）
----------------------------------------
- `BigInteger` 主键在 SQLite 上不自增（见文件末尾的 `void_sqlite_bigint`）；
- `JSON` 列在 SQLite 上是 TEXT，`FOR UPDATE` 行锁是空操作，`func.now()` 渲染
  成 `CURRENT_TIMESTAMP`。因此**事务并发、行锁、时区**这三类行为无法在此验证，
  只能靠云库实测（文档 5.5 的锁流程属于这一类）。
- 初始迁移的 `server_default=sa.text('now()')` 在 SQLite 上是语法错误，因此
  测试建表走 `Base.metadata.create_all`（与 `tests/integration/test_migrations.py`
  同样的处理，理由见该文件）。

环境变量必须在导入 app 之前设置
-------------------------------
`app.core.config` 在**首次被 import 时**就构造了全局 `Settings` 单例，
之后再改环境变量（或 monkeypatch `settings`）对已固化的值无效。
所以下面几个 `os.environ[...]` 出现在所有 `app.*` 导入之前 —— 这不是笔误，
**不要为了排版把它们挪到文件中间**。
"""

from __future__ import annotations

import os
import tempfile

# ---- 必须最先执行，见模块 docstring 最后一段 ----
# 把全局 `DATABASE_URL` 指向临时 SQLite（§13.1 自测路径）。
#
# 为什么必须有：`app.core.database` 的模块级 `async_engine` / `AsyncSessionLocal`
# 在**导入时**就按 `settings.database_url` 固化了。`tests/module3/` 直接使用
# 这两个模块级对象（见该目录 conftest），若不覆盖，它们会指向 .env 里的云库
# `smart_scheduler_dev` —— 跑一次用例就把开发库写脏。环境变量优先于 `.env`，
# 因此这里的覆盖是有效的。
#
# 本文件自己的 `engine` / `db_session` 夹具走 `db_path(tmp_path)`，每个用例一个
# 独立文件库，**不受**这一行影响；受影响的是「直接用模块级引擎」的那部分用例。
_MODULE3_TEST_DB = os.path.join(
    tempfile.gettempdir(), "smart_scheduler_module3_test.db"
).replace("\\", "/")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_MODULE3_TEST_DB}"

# 关掉 Redis：默认走内存实现，且 /ready 探针不会去连 127.0.0.1:6380 白等超时
os.environ["REDIS_ENABLED"] = "false"
# bcrypt 成本 4（约 1 毫秒）而不是 12（约 250 毫秒）。
# 这只影响**新生成**的哈希；校验耗时由哈希自身记录的 cost 决定，
# 因此工厂用 4 造的密码，登录时也是 4 的成本。
os.environ["BCRYPT_ROUNDS"] = "4"
# 风控默认关闭（文档 4.4：可选增强，不影响主流程）。
# 需要它的用例自行 monkeypatch app.core.config.settings.AI_RISK_ENABLED。
os.environ["AI_RISK_ENABLED"] = "false"
# SQL 回显关闭：否则每条用例都会往日志里打带 bcrypt 哈希的 INSERT
os.environ["SQL_ECHO"] = "false"

from collections.abc import AsyncGenerator, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401  —— 导入以注册全部 ORM 模型
from app.api.deps import get_token_store, reset_token_store
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.metrics import InMemoryMetricStore, configure_metric_store, reset_metric_store

# 上面那段的顺序是**功能性**的，不是排版问题，所以在这里把它变成会失败的自检 ——
# 只用注释约束的话，下一个人把 import 挪到 os.environ 之前（IDE 的「优化导入」
# 就会这么干）不会有任何提示，只会得到「测试莫名变慢、偶发连不上 Redis」。
# lint 帮不了这一条：ruff 的 E402 对 sys.path / os.environ 之后的导入不报错。
assert settings.REDIS_ENABLED is False, (
    "REDIS_ENABLED 不是 false：app.core.config 在本文件的 os.environ 赋值之前就被导入了，"
    "环境变量没生效。请把 import app.* 放回 os.environ[...] 之后（见模块 docstring）。"
)
assert settings.BCRYPT_ROUNDS == 4, (
    f"BCRYPT_ROUNDS={settings.BCRYPT_ROUNDS}，期望 4（测试环境）。"
    "原因同上：环境变量必须在导入 app 之前设置。"
)

# ==========================================================================
# SQLite 类型兼容垫片
# ==========================================================================
# 项目模型用 `BigInteger` 主键（对齐云库 BIGINT），SQLAlchemy 在 SQLite 上把
# 它渲染成 `BIGINT PRIMARY KEY`。而 SQLite 只把声明为 **`INTEGER PRIMARY KEY`**
# 的列当作 rowid 别名并自动赋值，于是插入不带 id 的行会报
# `NOT NULL constraint failed: sys_role.id`（已实测）。
#
# 这里只在**测试进程内**把 BIGINT 编译成 INTEGER，让测试库的自增语义与云库一致。
# 生产代码与 ORM 字段定义**不受影响**（决策 10：不改任何字段定义）。
# 若哪天有人把它挪进 app/，就等于篡改了生产行为 —— 这个垫片必须留在 tests/。
SQLiteTypeCompiler.visit_BIGINT = lambda self, type_, **kw: "INTEGER"  # type: ignore[method-assign]


# ==========================================================================
# 数据库
# ==========================================================================
@pytest.fixture
def db_path(tmp_path: Path) -> str:
    """每个用例一个独立的 SQLite 文件。"""
    # SQLAlchemy 的 URL 不接受 Windows 的反斜杠路径，必须转成 POSIX 形式
    return (tmp_path / "test.db").as_posix()


async def _make_engine(url: str, *, isolation_level: str | None = None) -> AsyncEngine:
    kwargs: dict[str, Any] = {
        # NullPool：不缓存连接。每个会话用完即关，SQLite 的文件锁立刻释放，
        # 也避免 aiosqlite 的工作线程堆积（它的线程不是守护线程，
        # 不关连接会让解释器在退出时卡在 threading._shutdown，实测会挂住）。
        "poolclass": NullPool,
        # aiosqlite 在自己的线程里跑 sqlite3，需要关掉同线程检查
        "connect_args": {"check_same_thread": False},
    }
    if isolation_level is not None:
        kwargs["isolation_level"] = isolation_level
    return create_async_engine(url, **kwargs)


@pytest.fixture
async def engine(db_path: str) -> AsyncGenerator[AsyncEngine, None]:
    """
    应用侧引擎（每个请求一个会话、正常事务语义）。

    建表走 `Base.metadata.create_all` 而不是跑初始迁移，原因见模块 docstring。
    """
    engine = await _make_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(
    db_path: str,
    # 依赖 engine 只为**排序**：必须先由它建好表，这里才有表可写。
    # 函数体不使用该参数（pytest 靠参数名解析夹具，不能改名为 _engine）。
    engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """
    测试侧会话：**只用于造数据与查证据**。

    `isolation_level="AUTOCOMMIT"`：每条语句立即生效、读完不持有事务。
    否则一次 `SELECT` 就会留下一个 SQLite 读锁，应用侧随后的写会撞
    `database is locked`，表现为随机失败的「灵异」用例。

    副作用是这里的 `commit()` 只是空操作 —— 这是**特性**：
    验证「服务层有没有真的提交」时，用它去看是可靠的。
    """
    seed_engine = await _make_engine(f"sqlite+aiosqlite:///{db_path}", isolation_level="AUTOCOMMIT")
    factory = async_sessionmaker(seed_engine, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await seed_engine.dispose()


# ==========================================================================
# 令牌白名单与指标存储
# ==========================================================================
@pytest.fixture
def token_store() -> Any:
    """
    refreshToken 白名单：生产降级实现 `InMemoryTokenStore`，每个用例一份。

    每个用例重新构造是必需的：白名单里残留上一个用例的 jti，会让
    「令牌不在白名单必须被拒」这类断言变成假绿。
    """
    from app.core.token_store import InMemoryTokenStore

    return InMemoryTokenStore()


@pytest.fixture
def fake_redis() -> Any:
    """纯替身 Redis。需要验证 `RedisTokenStore` 本体的用例自行取用。"""
    from tests.fakes.fake_redis import FakeRedis

    return FakeRedis()


@pytest.fixture
def metric_store() -> InMemoryMetricStore:
    """
    Agent 指标存储。埋点中间件与 `/monitor/agent` 都通过
    `get_metric_store()` 取全局实例，因此这里用 `configure_metric_store` 替换。
    """
    store = InMemoryMetricStore()
    configure_metric_store(store)
    return store


@pytest.fixture(autouse=True)
def _reset_global_singletons() -> Iterator[None]:
    """
    用例前后清掉模块级单例。

    `app/api/deps.py` 的 token store、`app/core/metrics.py` 的指标存储、
    `app/core/redis.py` 的客户端都是模块级惰性单例 —— 不重置就会**跨用例泄漏**，
    典型症状是「单独跑通过、全量跑失败」。autouse 保证没人需要记得做这件事。
    """
    reset_token_store()
    reset_metric_store()
    yield
    reset_token_store()
    reset_metric_store()

    from app.core import redis as redis_module

    redis_module.reset_client()


# ==========================================================================
# HTTP 客户端
# ==========================================================================
def make_application(engine: AsyncEngine, token_store: Any) -> Any:
    """
    构造应用并接上测试用的依赖覆盖。

    单独抽成函数（而不是全写在夹具里）是为了让**需要改配置再建应用**的用例
    也能复用同一套覆盖 —— 最关键的是 `tests/api/test_mock_routes.py`：
    Mock 路由在 `create_app()` 里按 `settings.DEBUG` 决定注不注册，
    因此那个用例必须在调用本函数**之前**改好 `settings.DEBUG`。
    两处各写一份覆盖是维护陷阱：将来加了新的依赖覆盖，
    只改 conftest 会让那个文件里的应用少一层覆盖，症状极难定位。

    依赖覆盖：
    - `get_db` → 每个请求一个**新会话**（与生产完全一致，不用共享会话糊弄），
      这样「服务层忘了 commit」会被真实地暴露出来；
    - `get_token_store` → 用例级 `InMemoryTokenStore`；
    - 指标存储已由 `metric_store` 夹具用 `configure_metric_store` 替换
      （它是被直接调用的，不是依赖项，所以不能走 dependency_overrides）。
    """
    from app.main import create_app

    instance = create_app()
    request_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _get_db_override() -> AsyncGenerator[AsyncSession, None]:
        async with request_factory() as session:
            try:
                yield session
            except Exception:
                # 与 app/core/database.py 的 get_db 行为一致：只回滚不提交
                await session.rollback()
                raise

    async def _get_token_store_override() -> Any:
        return token_store

    instance.dependency_overrides[get_db] = _get_db_override
    instance.dependency_overrides[get_token_store] = _get_token_store_override
    return instance


@pytest.fixture
async def application(
    engine: AsyncEngine,
    token_store: Any,
    metric_store: InMemoryMetricStore,
    _reset_global_singletons: None,
) -> AsyncGenerator[Any, None]:
    """
    构造好的 FastAPI 应用（依赖已覆盖）。

    单独出一个夹具（而不是藏在 `client` 里）是为了让用例能改
    `application.dependency_overrides` 来构造故障场景 —— 例如把
    token store 换成「下一次读 Redis 就失败」的实例，验证降级路径。
    """
    instance = make_application(engine, token_store)
    yield instance
    instance.dependency_overrides.clear()


@pytest.fixture
async def client(application: Any) -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    指向应用的 ASGI 客户端。

    用 `httpx.ASGITransport` 而不是 `AsyncClient(app=...)`：后者在
    httpx 0.27 起已废弃；而且它的 lifespan 事件会去探 DB/Redis，
    测试里刻意不跑（夹具直接构造应用即可）。
    """
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        # 不跟随重定向：测试里出现重定向基本都是配错路径，应当暴露出来
        follow_redirects=False,
    ) as http_client:
        yield http_client


# ==========================================================================
# 常用动作
# ==========================================================================
@pytest.fixture
def login() -> Callable[..., Any]:
    """
    登录助手：`await login(client, "admin", "Test@123456")`。

    只负责发请求，**不做任何断言** —— 断言属于用例。失败时把响应体一并返回，
    由用例自己决定「这里的失败是不是预期」。
    """

    async def _login(client: httpx.AsyncClient, username: str, password: str) -> httpx.Response:
        return await client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )

    return _login


@pytest.fixture
def auth_headers() -> Callable[[dict[str, Any]], dict[str, str]]:
    """把登录响应里的 accessToken 变成 `Authorization` 头。"""

    def _headers(data: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {data['accessToken']}"}

    return _headers


# ==========================================================================
# 模块 1 / 模块 2 合并引入的夹具
# ==========================================================================
# 来源
# ----
# 模块 2（摄像头空间感知）与模块 4（核心调度 Agent）在基础支撑交付前自建过一份
# tests/conftest.py。合并时把其中的夹具整体迁入本文件，夹具名与语义保持不变，
# 使两个模块的既有用例无需改动即可运行。
#
# 刻意**未**迁入的部分
# --------------------
# 原文件里的 `db_session`（连 smart_scheduler_test 真库，连不上则 skip）。
# 原因有二：
#   1. 本文件上方已有同名夹具，走 SQLite 离线库，符合本项目「自动化测试全离线」
#      的整体策略（见模块 docstring）；
#   2. 原文件中的 `db_session` 实际上**没有任何用例使用** —— 它只出现在自己的
#      docstring 示例里。
# 真库联调仍由 tests/integration/ 下的用例承担。
#
# 两个假 LLM 夹具的名字必须区分开，它们的契约正好相反：
#   - fake_llm        故意**不**支持 bind_tools，让 image_service 走「策略 B
#                     降级」分支（普通 ainvoke + 手工 JSON 解析）；
#   - agent_fake_llm  **必须**支持 bind_tools，供 create_agent 组装使用。

import io  # noqa: E402
import json  # noqa: E402
import struct  # noqa: E402
import zlib  # noqa: E402

from langchain_core.language_models import BaseChatModel  # noqa: E402
from langchain_core.language_models.fake_chat_models import (  # noqa: E402
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402
from pydantic import PrivateAttr  # noqa: E402


# --------------------------------------------------------------------------
# 图片字节构造（模块 2）
# --------------------------------------------------------------------------
def build_png(width: int = 8, height: int = 8, rgb: tuple = (120, 160, 200)) -> bytes:
    """
    生成一张**真正合法**的 PNG 图片字节。

    参数：
        width / height : 尺寸（像素）
        rgb            : 填充色

    返回：
        bytes，可被 Pillow / 浏览器正常打开

    为什么用代码生成而不是塞图片文件：
        避免往仓库里加二进制资源，同时让「图片尺寸」这类参数可在用例里随意调整。

    结构：PNG = 8 字节签名 + 若干 chunk（IHDR / IDAT / IEND），
    每个 chunk = 长度(4B) + 类型(4B) + 数据 + CRC32(4B)
    """
    signature = b"\x89PNG\r\n\x1a\n"

    # IHDR：宽、高、位深 8、颜色类型 2（真彩色 RGB）、压缩/滤波/隔行均为 0
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

    # 每行数据前导一个滤波类型字节（0 = None），随后是 width 个 RGB 像素
    raw_rows = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    idat = zlib.compress(raw_rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        """组装一个 PNG chunk，末尾附 CRC32 校验码。"""
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    return signature + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


@pytest.fixture
def fake_jpeg() -> bytes:
    """
    构造一段**魔数正确**的类 JPEG 字节。

    说明：
        不构造完整合法的 JPEG —— 模块 2 从头到尾不解码图片，只是把它 base64 后
        丢给大模型（测试里模型也是假的）。流水线真正校验的只有文件头魔数
        FF D8 FF，带上正确文件头即可。需要完整合法图片时用 build_png()。
    """
    return b"\xff\xd8\xff\xe0" + b"\x00" * 512


@pytest.fixture
def fake_png() -> bytes:
    """一张真正合法的 PNG（8x8 像素），用于需要经得起解码的场景。"""
    return build_png()


@pytest.fixture
def make_upload_file():
    """
    把裸字节包装成 FastAPI 的 UploadFile，供服务层直接调用。

    用法：
        file = make_upload_file(content=b"...", filename="site.jpg")
        data = await analyze_space_image(db=None, file=file, llm=fake_llm([...]))

    参数：
        content      : 图片字节；None 表示用默认的假 JPEG
        filename     : 文件名（测试路径穿越时传 "../../evil.jpg"）
        content_type : 客户端声明的 MIME
    """

    def _make(
        content: bytes | None = None,
        filename: str = "site.jpg",
        content_type: str = "image/jpeg",
    ):
        from fastapi import UploadFile

        raw = content if content is not None else (b"\xff\xd8\xff\xe0" + b"\x00" * 512)
        return UploadFile(
            file=io.BytesIO(raw),
            filename=filename,
            # UploadFile 从 headers 里读 content-type
            headers={"content-type": content_type},
        )

    return _make


# --------------------------------------------------------------------------
# 假模型（模块 2）
# --------------------------------------------------------------------------
@pytest.fixture
def fake_llm():
    """
    构造「按剧本回复」的假多模态模型。

    用法：
        llm = fake_llm(['{"spaceId": 101, "confidence": 0.92}'])
        data = await analyze_space_image(db=None, file=..., llm=llm)

    说明：
        FakeMessagesListChatModel 每次调用按顺序吐出一条预设回复，因此可以精确
        模拟「模型返回非 JSON」「返回 markdown 包裹」等各种剧本。

    ⚠️ 这条路径实际走的是 image_service._recognize 的**策略 B**（普通 ainvoke +
       手工 JSON 解析）：FakeMessagesListChatModel 没有实现 bind_tools，调用
       with_structured_output 会抛 NotImplementedError，被 _recognize 捕获后
       自动降级。这也说明假模型天然无法覆盖策略 A —— 策略 A 由 structured_llm
       夹具单独覆盖。
    """

    def _make(responses: list) -> FakeMessagesListChatModel:
        return FakeMessagesListChatModel(
            responses=[AIMessage(content=r) if isinstance(r, str) else r for r in responses]
        )

    return _make


@pytest.fixture
def structured_llm():
    """
    构造支持 with_structured_output 的假模型，用于覆盖**策略 A**。

    说明：
        刻意不继承 BaseChatModel —— 那样需要实现 _generate，还得让 bind_tools
        真的产出符合协议的输出，成本远高于收益。这里用鸭子类型只实现被调用的
        两个方法，专注验证「_unpack_structured 拆包 + 策略 A 优先」这段逻辑。

    用法：
        llm = structured_llm({"spaceId": 101, "confidence": 0.92})
        llm = structured_llm(None, raw_text="我认不出这张图")   # 解析失败但有原始文本
    """

    def _make(payload, raw_text: str = ""):

        class _StructuredStub:
            def with_structured_output(self, schema, include_raw: bool = False, **kwargs):

                class _Runner:
                    async def ainvoke(self, messages, **kwargs):
                        # 模拟 with_structured_output(include_raw=True) 的返回结构
                        raw = AIMessage(
                            content=raw_text
                            or ("" if payload is None else json.dumps(payload, ensure_ascii=False))
                        )
                        try:
                            parsed = schema.model_validate(payload) if payload is not None else None
                        except Exception as exc:  # noqa: BLE001 - 模拟解析失败分支
                            return {"raw": raw, "parsed": None, "parsing_error": exc}
                        return {"raw": raw, "parsed": parsed, "parsing_error": None}

                return _Runner()

        return _StructuredStub()

    return _make


@pytest.fixture
def failing_llm():
    """
    构造一调用就抛异常的假模型，用于模拟模型超时 / 网络故障。

    用法：
        monkeypatch.setattr(settings, "VISION_STRUCTURED_OUTPUT", False)
        with pytest.raises(ImageRecognitionError) as exc:
            await analyze_space_image(db=None, file=..., llm=failing_llm(TimeoutError()))
        assert exc.value.code == 41003

    说明：
        默认跳过结构化输出分支（VISION_STRUCTURED_OUTPUT=False），让异常直接从
        ainvoke 抛出，精确命中「策略 B 失败」这条路径。
    """

    def _make(exc: Exception | None = None):

        class _FailingStub:
            async def ainvoke(self, messages, **kwargs):
                raise exc or TimeoutError("simulated model timeout")

            def with_structured_output(self, schema, **kwargs):
                # 让策略 A 也走同样的失败路径，保证异常最终被转成 41003
                return self

        return _FailingStub()

    return _make


# --------------------------------------------------------------------------
# 目录与环境（模块 2）
# --------------------------------------------------------------------------
@pytest.fixture
def temp_upload_dir(tmp_path, monkeypatch):
    """
    把图片落盘目录重定向到 pytest 的临时目录。

    用法：
        def test_save(temp_upload_dir, fake_png): ...

    说明：
        直接把 IMAGE_UPLOAD_DIR 设成**绝对路径**即可生效 ——
        settings.image_upload_path 内部是 `backend_dir / IMAGE_UPLOAD_DIR`，
        而 pathlib 在右侧为绝对路径时会直接采用右侧，不做拼接。
        这样测试既不用改代码，也不会往仓库的 uploads/ 里写垃圾文件。
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "IMAGE_UPLOAD_DIR", str(tmp_path))
    return tmp_path


# --------------------------------------------------------------------------
# 假模型（模块 4 核心调度 Agent）
# --------------------------------------------------------------------------
class StubChatModel(BaseChatModel):
    """
    自实现 bind_tools 的假聊天模型，供 create_agent 组装使用。

    为什么不用现成的 FakeMessagesListChatModel / GenericFakeChatModel：
        create_agent 组装时会调 model.bind_tools(tools)，而实测 langchain-core
        1.6.4 下这两个现成夹具都没有实现 bind_tools，直接抛 NotImplementedError，
        后面所有用例都会变成「假绿」。冒烟验证见 tests/smoke_fake_llm.py。
    """

    responses: list[AIMessage] = []
    _cursor: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "stub-chat-model"

    def bind_tools(self, tools, **kwargs):
        """create_agent 必需。基类默认实现直接抛 NotImplementedError。"""
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        # 每次调用往下走一条剧本；越界后停在最后一条（便于观察是否被重复调用）
        idx = min(self._cursor, len(self.responses) - 1)
        self._cursor += 1
        return ChatResult(generations=[ChatGeneration(message=self.responses[idx])])


@pytest.fixture
def agent_fake_llm():
    """
    构造供 create_agent 使用的假模型（**支持** bind_tools）。

    用法：
        model = agent_fake_llm([tool_call_msg, AIMessage(content="已找到方案")])
        agent = create_agent(model, tools=[query_spaces], system_prompt="你是调度助手")

    参数：
        responses : 按顺序返回的消息；传 str 会自动包成 AIMessage

    说明：
        典型剧本是「第一条带 tool_calls，第二条给最终答复」，对应 create_agent
        「调工具 → 再总结」两轮。只需覆盖模型直接给答复的场景时，传一条即可。
    """

    def _make(responses: list) -> StubChatModel:
        return StubChatModel(
            responses=[AIMessage(content=r) if isinstance(r, str) else r for r in responses]
        )

    return _make


# ==========================================================================
# 模块 4 核心调度 Agent（2026-09-28 合并 origin/main 时并入）
# ==========================================================================
# 并入原则与两组夹具的分工
# ------------------------
# 上面的通用夹具（引擎 / `db_session` / `client` / 令牌 / 指标）来自基础支撑，
# **全部离线**：SQLite 临时库 + 假 Redis，这是全组约定的默认形态。
#
# 模块 4 的阶段 7 用例（`tests/test_agent_schedule.py` 等）与此不同：它们要断言
# 的主文档 6.9 种子数据事实（场地 8 / 设备 15 / 预约 10 的**真实 id 与状态**），
# SQLite 空库里没有，只能连开发库。因此本段夹具**成对使用 `dev_` 前缀**，
# 与离线夹具区分开：
#
#     dev_client      → 全局 `app`（不覆盖 get_db），请求打到开发库
#     dev_db_session  → 开发库只读会话，只用于「查证据」
#
# 名字区分不是为了排版好看：`db_session` / `client` 这**两个名字**在同一个
# conftest 里只能有一个语义，合并时取的是上面那套离线版（基础支撑的用例依赖它）。
# 谁把 `dev_` 前缀去掉，就会同时打坏两边——离线用例连上真库、真库用例连上空库。
#
# ⚠️ 该依赖已登记在 `docs/spec/README.md` 硬卡点 #4（`smart_scheduler_test` 无权
# 访问，责任人申云飞），测试库权限到位后才谈得上「全离线」。

import asyncio  # noqa: E402
import socket  # noqa: E402

from pydantic import Field  # noqa: E402
from sqlalchemy import event  # noqa: E402

# --------------------------------------------------------------------------
# 种子数据事实（6.9）—— 断言基准
# --------------------------------------------------------------------------
# 这些值来自开发库实测，不是文档抄录。**种子数据一变，这里与相关用例必须同步改**
# （docs/test.md §3.2 末尾的明文要求）。
#
# 实测基线（2026-09-27）：
#   space_resource  8 行：会议室×3（cap 12/20/30）、展厅×2（cap 50/35）、
#                        多功能厅×2（cap 80/25）、户外×1（cap 100）
#   device_resource 15 行：投影仪×4、音响×4、显示屏×3、无人机×2、直播设备×2
#   reserve_order  10 行
SEED = {
    # 场地
    "space_hall_40": 4,        # A栋3楼展厅，type=2，cap=50，¥800
    "space_hall_35": 5,        # C栋1楼展厅，type=2，cap=35，¥600
    "space_small_hall": 7,     # 综合楼小多功能厅，type=3，cap=25
    "space_big_hall": 6,       # 综合楼大礼堂，type=3，cap=80
    # 设备
    "projectors": [1, 2, 3, 4],
    "speakers": [5, 6, 7, 8],
    "screens": [9, 10, 11],
    "drone_ok": 12,            # 无人机01，status=1，available=2
    "drone_broken": 13,        # 无人机02，status=2（损坏）→ 必须被 Tool 滤掉
    "live_ok": 14,             # 直播设备01，status=1，available=1
    "live_exhausted": 15,      # 直播设备02，status=1，available=0 → 必须被 Tool 滤掉
}

#: 一个**已被占用**的时段：`reserve_order` id=9（space=4，order_status=1）。
#: 同段被占的还有 space 1/2/3/5，所以这是确定性冲突，不是「碰巧」。
OCCUPIED_SLOT = ("2026-10-15 13:00:00", "2026-10-15 17:00:00")
#: 同一天、同长度，但**没有任何订单**——用于「无冲突」路径。space 6 在该段是空的。
FREE_SLOT = ("2026-10-15 09:00:00", "2026-10-15 11:00:00")

#: 用例里的时间一律用这两个常量，避免各处硬编码导致互相矛盾。
T_START = FREE_SLOT[0]
T_END = FREE_SLOT[1]


# --------------------------------------------------------------------------
# 护栏一：断网
# --------------------------------------------------------------------------
_LOOPBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}


@pytest.fixture(autouse=True, scope="session")
def _offline_guard() -> Any:
    """任何到非回环地址的 socket 连接直接判失败。

    阶段 7 §3.8 的原话是「**断网跑一遍验证这一点**，不要只凭『应该不联网』推断」。
    本机没有可靠的断网手段（关网卡要管理员权限，且会连 SSH 隧道一起断掉——
    而隧道断了连库的用例就没法跑了），所以用**拦截而不是拔线**：
    拦截的覆盖范围比拔线更精确，拔线只断外部网络，拦截能证明**每条用例**都没往外连。

    回环地址放行：`dev_*` 夹具要连隧道另一端的开发库（127.0.0.1:3308）。
    """
    real_connect = socket.socket.connect

    def guarded(self: socket.socket, address: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in _LOOPBACK:
            raise AssertionError(
                f"用例试图联网：{host}。主文档 10.2 规定真实 API 不进常规用例"
                "（费用不可控 + 用例结果受外部影响）。"
            )
        return real_connect(self, address)

    socket.socket.connect = guarded  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]


# --------------------------------------------------------------------------
# 护栏二：禁止写库
# --------------------------------------------------------------------------
#: 会被拦下的语句首关键字。故意**不含** `select` / `show` / `set` / `begin` 等
#: ——`SELECT ... FOR UPDATE` 是读，必须放行（真实 `create_order` 靠它）。
_FORBIDDEN_HEADS = frozenset({
    "insert", "update", "delete", "replace",
    "create", "drop", "alter", "truncate", "rename",
    "grant", "revoke", "call",
})


class WriteForbiddenError(AssertionError):
    """用例试图写库。见 `_db_readonly_guard`。"""


@pytest.fixture(autouse=True, scope="session")
def _db_readonly_guard() -> Any:
    """拦住所有写语句。

    主文档 6.8 的红线是「测试禁止写 `reserve_order` 正式表」。正常做法是连测试库
    `smart_scheduler_test` 并把用例包在事务里回滚——但**该库当前无权访问**
    （`Access denied for user 'smart_dev'@'%' to database 'smart_scheduler_test'`），
    只能连开发库。连开发库又必须保证不污染，于是把「靠回滚兜底」换成
    「靠拦截保证根本写不进去」：**这个变体的安全性反而更高**，因为回滚方案在
    用例中途崩掉时可能留下半截数据，而拦截是每次都生效的前置拒绝。

    拦截是**全库级别**的，不只 `reserve_order`——测试里没有任何理由需要写库。

    只挂应用侧的全局引擎：上面那套离线夹具用的 SQLite 引擎是各用例自建的，
    不该被本护栏牵连（它们本来就该能写自己的临时库）。
    """
    from app.core.database import async_engine

    written: list[str] = []

    def _guard(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        head = statement.lstrip().split(None, 1)[0].lower() if statement.strip() else ""
        if head in _FORBIDDEN_HEADS:
            written.append(statement)
            raise WriteForbiddenError(
                f"用例试图写库：{statement.strip()[:160]}\n"
                "主文档 6.8：测试禁止写 reserve_order 正式表；"
                "当前测试库无权访问，连的是开发库，任何写入都会污染种子数据——"
                "而种子数据正是 AGENT-S-01~05 的断言基准。"
            )

    event.listen(async_engine.sync_engine, "before_cursor_execute", _guard)
    try:
        yield written
    finally:
        event.remove(async_engine.sync_engine, "before_cursor_execute", _guard)


# --------------------------------------------------------------------------
# 护栏三：埋点计数复位
# --------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_metrics() -> Any:
    """每个用例前清零埋点。`agent_service` 是进程内单例，不清零则用例互相影响。

    （基础支撑的 `_reset_global_singletons` 清的是 `app/core/metrics.py` 那套
    中间件指标，与本夹具不是同一份计数，两者都要。）
    """
    from app.services import agent_service

    agent_service.reset()
    yield
    agent_service.reset()


# --------------------------------------------------------------------------
# 假 LLM
# --------------------------------------------------------------------------
class ScriptedChatModel(BaseChatModel):
    """按顺序消费预设响应的假模型。

    - `bind_tools` 返回 `self`：`create_agent` 必需，基类默认实现直接抛
      `NotImplementedError`（这是本夹具存在的唯一理由，见 `tests/smoke_fake_llm.py`）
    - `_cursor` 用 `PrivateAttr` 而非普通字段，否则会被 pydantic 当成模型字段参与校验
    - 响应耗尽后**重复最后一条**，避免用例因为少写一条响应而拿到 IndexError
    - `delay` 用于 `AGENT-E-02`（超时）：不 sleep 就测不出 `wait_for` 分支

    与上面的 `agent_fake_llm` / `StubChatModel` 的关系：契约相同（都支持
    `bind_tools`），`ScriptedChatModel` 多一个 `delay` 且**异步**实现
    `_agenerate`（`StubChatModel` 只实现同步 `_generate`）。模块 4 的用例按名字
    取 `scripted`；基础支撑的用例取 `agent_fake_llm`。两者不合并，
    因为阶段 7 的用例是按 `scripted` 写的，改名会牵动 28 处调用。
    """

    responses: list[AIMessage] = Field(default_factory=list)
    delay: float = 0.0
    _cursor: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "scripted-chat-model"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:  # noqa: ANN401 - 对齐父类签名
        return self

    def _next(self) -> ChatResult:
        idx = min(self._cursor, len(self.responses) - 1)
        self._cursor += 1
        return ChatResult(generations=[ChatGeneration(message=self.responses[idx])])

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:  # noqa: ANN401
        return self._next()

    async def _agenerate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:  # noqa: ANN401
        if self.delay:
            await asyncio.sleep(self.delay)
        return self._next()


@pytest.fixture
def scripted() -> Any:
    """`scripted([...])` → 一个 `ScriptedChatModel`。

    写成工厂而不是直接给实例：用例需要按场景现编响应序列，
    一个固定内容的夹具会让所有用例被同一串 tool_call 绑死。
    """
    def _make(responses: list[AIMessage], delay: float = 0.0) -> ScriptedChatModel:
        return ScriptedChatModel(responses=responses, delay=delay)

    return _make


# --------------------------------------------------------------------------
# 开发库夹具（模块 4 阶段 7 用例专用，见本段开头的说明）
# --------------------------------------------------------------------------
@pytest.fixture
def token() -> str:
    """`sys_user.id=1`（zhangsan，6.9 种子数据）的 accessToken。

    2026-09-28 合并后改用基础支撑的 `create_token`：模块 4 阶段的
    `create_access_token` / `create_refresh_token` 在正式版里已收敛成一个
    `create_token(user_id, role, token_type, expires_delta, version=0)`，
    返回 `(token, payload)` 二元组，因此这里取 `[0]`。
    正式版的 `get_current_user` 不查白名单（只有 refreshToken 才进 Redis），
    所以直接签发即可，不必先登录。
    """
    from datetime import timedelta

    from app.core.security import TokenType, create_token

    issued, _payload = create_token(
        user_id=1,
        role="user",
        token_type=TokenType.ACCESS,
        expires_delta=timedelta(minutes=30),
    )
    return issued


@pytest.fixture
def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def dev_client() -> Any:
    """指向**全局应用**的 ASGI 客户端：请求打到开发库。

    与上面的 `client` 的差别只有一处、但很关键：这里**不覆盖 `get_db`**。
    上面的 `client` 走 `application`，把 `get_db` 覆盖成 SQLite 会话，
    连的是空库；模块 4 的用例断言的是 6.9 种子数据的真实 id 与状态，
    必须打到开发库（只读，写入由 `_db_readonly_guard` 拦下）。
    """
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


@pytest.fixture
async def dev_db_session() -> Any:
    """开发库只读会话，**只用于查证据**。

    ⚠️ **本夹具没有满足阶段 7 §3.2 的原文**（「连接 `smart_scheduler_test`，用例结束后回滚」）：

    | 要求 | 实际 | 原因 |
    | --- | --- | --- |
    | 连测试库 | 连的是 `smart_scheduler_dev` | `smart_scheduler_test` 报 1044 无权访问，属集成组 |
    | 用例后回滚 | 无需回滚 | 写入被 `_db_readonly_guard` 前置拒绝，不存在需要回滚的数据 |

    「回滚」这一步在连开发库的前提下本来就是错的安全手段：它保护的是「用例自己的写」，
    而用例压根不许写。真正的保护是拦截。这条偏差记在
    `docs/spec/done/stage-07-completion.md` 里，**未取得测试库权限前不得声称已合规**。
    """
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
def seed() -> dict[str, Any]:
    """种子数据事实（6.9 实测值）。断言基准集中在 `SEED` 一处，便于种子变更时同步。"""
    return SEED


@pytest.fixture
def slots() -> dict[str, tuple[str, str]]:
    """被占用 / 空闲的两个时段。"""
    return {"occupied": OCCUPIED_SLOT, "free": FREE_SLOT}
