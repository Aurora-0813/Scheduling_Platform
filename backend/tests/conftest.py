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
"""

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

# ---- 必须最先执行，见模块 docstring 最后一段 ----
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
                            or (
                                ""
                                if payload is None
                                else json.dumps(payload, ensure_ascii=False)
                            )
                        )
                        try:
                            parsed = (
                                schema.model_validate(payload) if payload is not None else None
                            )
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

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003 - 对齐父类签名
        """create_agent 必需。基类默认实现直接抛 NotImplementedError。"""
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
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
