"""
配置与环境模板

盯住三类会让全体成员「服务起不来」或「违反硬规范」的问题：
1. `.env.example` 里出现 Settings 不认识的键 —— Settings 是 extra="forbid"，
   照抄模板建 .env 后启动即 ValidationError（已实测）
2. 同步驱动 mysql+pymysql 扩散 —— 开发流程.md 3.4 禁止同步驱动，
   只允许 core/config.py 为 Alembic 保留一条，且业务代码不得引用
3. DB_PORT 口径搞混 —— 云服务器侧 MySQL 监听 3307，本机隧道入口是 3308，
   代码连的是后者，填错只会得到一句「连接被拒绝」
4. 同步引擎在导入时被创建 —— 那会让 pymysql 变成应用与离线测试的硬依赖，
   未装它时整套测试在收集阶段就挂掉（合并团队代码时实测踩过）
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.config import Settings, settings

BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = BACKEND_DIR / ".env.example"
APP_DIR = BACKEND_DIR / "app"


def _env_example_keys() -> list[str]:
    keys: list[str] = []
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        keys.append(stripped.split("=", 1)[0].strip())
    return keys


def _env_example_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def test_env_example_exists():
    assert ENV_EXAMPLE.is_file()


#: 代码里的 DB_PORT 默认值 —— 取自 `Settings` 的**字段默认**。
#:
#: 为什么不能直接用 `settings.DB_PORT`（2026-09-28 修正）：
#: `settings` 会被**开发机自己的 `backend/.env`** 覆盖，而 `.env` 是
#: gitignore 的、每台机器把 SSH 隧道开在本机哪个端口完全自由
#: （本机就开在 3307，见 `backend/.env` 文件头的说明）。
#: 原先下面两条用例直接断言 `settings.DB_PORT`，于是任何隧道端口不是 3308
#: 的机器都会红 —— 可它们真正要守的是
#: 「**模板与代码默认值**必须一致、且默认值是 3308」，
#: 这件事与开发机实际开了哪个端口无关。
_DB_PORT_CODE_DEFAULT = Settings.model_fields["DB_PORT"].default


def test_env_example_port_matches_the_code_default():
    """
    ★ 模板与代码默认值必须一致。

    不一致时，没在 .env 里改 DB_PORT 的人会连到错误的隧道端口，
    报错只有一句「连接被拒绝」，极难定位。

    比的是「`.env.example` 的取值」与「`Settings` 的字段默认」，
    **不读开发机的 `.env`**（理由见上方常量注释）。
    """
    declared = _env_example_values()

    assert int(declared["DB_PORT"]) == _DB_PORT_CODE_DEFAULT


def test_db_port_is_the_local_tunnel_entry_port():
    """
    ★ DB_PORT 是「本机到达 MySQL 的实际端口」，即 SSH 隧道的本地入口。

    这里**刻意不钉** 开发流程.md 6.1 模板里的 3307：那个 3307 是
    **云服务器侧 MySQL 的监听端口**，与代码实际连接的端口不是同一个数。
    团队 .env.example 的隧道备忘写得很明确：

        ssh -L 3308:127.0.0.1:3307 <user>@<云服务器IP> -N

    代码连的是本机入口，所以默认值必须是 3308。若钉成 3307，
    忘配 .env 的人会连到本机一个没人监听的端口，报错只有一句
    「连接被拒绝」，极难定位 —— 这正是本用例要防的。

    同样只断言**字段默认值**，不看开发机的 `.env`（2026-09-28 修正）。
    """
    assert _DB_PORT_CODE_DEFAULT == 3308, (
        "DB_PORT 必须是本机隧道入口端口。"
        "云服务器侧 MySQL 监听 3307，本机隧道入口是 3308，别把两者搞混。"
    )


def test_env_example_has_no_unknown_keys():
    """★ 多一个键，照抄模板的人就起不来服务"""
    known = set(Settings.model_fields)
    unknown = sorted(key for key in _env_example_keys() if key not in known)

    assert not unknown, (
        f".env.example 里的 {unknown} 不是 Settings 的字段；"
        "Settings 是 extra='forbid'，照抄该模板建 .env 会导致启动失败"
    )


def test_env_example_lists_every_required_setting():
    """3.5：模板必须列全所有必需配置项，漏项会让新成员卡在配置上"""
    declared = set(_env_example_keys())
    # 这几项有安全的代码默认值，不写进模板也能跑，故不要求列出
    optional = {
        "APP_NAME",
        "APP_ENV",
        "DEBUG",
        "JWT_ALGORITHM",
        "JWT_EXPIRE_MINUTES",
        "CORS_ORIGINS",
        "CONFLICT_DEDUP_TTL_SECONDS",
        # ---- 2026-09-30：ASR 从百度换成 Qwen3-ASR-Flash 后**已废弃**的配置项 ----
        #
        # 它们仍留在 Settings 里、但**不再被任何代码读取**，也**刻意不写进
        # .env.example** —— 模板不该让新成员去配一个已经不用的服务。
        #
        # 为什么不是直接删字段：Settings 是 extra="forbid"，字段一旦消失，
        # **队友本地 .env 里残留的 BAIDU_API_KEY=... 会让服务起不来**，
        # 而报错只是 pydantic 的 extra_forbidden —— 排查成本高于收益。
        # 因此走「保留字段 + 模板不列」的过渡期，确认无人再持有旧 .env 后再删。
        "BAIDU_APP_ID",
        "BAIDU_API_KEY",
        "BAIDU_SECRET_KEY",
        "ASR_MODEL_PID",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
    }
    missing = sorted(set(Settings.model_fields) - declared - optional)

    assert not missing, f".env.example 缺少配置项：{missing}"


def test_env_example_contains_no_real_secrets():
    """3.5：模板只放占位符，严禁真实密钥"""
    content = ENV_EXAMPLE.read_text(encoding="utf-8")
    for line in content.splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        key, _, value = line.partition("=")
        if key.strip() in {"LLM_API_KEY", "DB_PASSWORD", "JWT_SECRET_KEY"}:
            assert value.strip().startswith("<"), f"{key} 必须是占位符，不能是真实值"


# ---------- 驱动规范 ----------


def test_database_url_uses_the_async_driver():
    """3.4：连接串固定 mysql+asyncmy://

    ⚠️ **2026-09-28 修正：不能再直接断言全局 `settings.database_url`。**

    测试进程里 `tests/conftest.py` 会在 import 任何 `app.*` **之前**
    把 `DATABASE_URL` 环境变量指向临时 SQLite（见该文件顶部那段「必须最先执行」），
    好让整套用例不碰云库。于是全局 `settings.database_url` 在测试期
    **本来就不是 MySQL** —— 原写法断言它 `startswith("mysql+asyncmy://")`
    必然失败，而失败原因跟「驱动规范」毫无关系。

    本用例要守的是**生产规则**（§3.4），所以显式构造一份 `DATABASE_URL=""`
    的配置来验 §3.4 的拼接结果：既不依赖环境变量，也照样把驱动前缀与 charset 钉死。
    `DATABASE_URL` 非空时原样返回（§13.1 的 SQLite 应急口）由
    `tests/unit/test_config.py` 之外的用例与 `config.py` 的启动校验负责。
    """
    fresh = Settings(
        DATABASE_URL="",
        DB_USER="u",
        DB_PASSWORD="p",
        DB_HOST="h",
        DB_PORT=3308,
        DB_NAME="d",
    )
    url = fresh.database_url

    assert url.startswith("mysql+asyncmy://")
    assert "pymysql" not in url
    assert url.endswith("charset=utf8mb4")


# 唯一允许出现同步驱动连接串的文件：Alembic 的迁移环境是同步的，
# 必须有一条 mysql+pymysql 连接串才能对比模型元数据与实际库结构。
# 这个例外**只此一处**，多一处就是有人在业务链路里绕过了异步驱动。
SYNC_DRIVER_ALLOWLIST = {"core/config.py"}


def test_only_the_allowlist_may_mention_the_sync_driver():
    """
    ★ 3.4 禁止同步驱动，唯一例外是 Alembic（经 core/config.py 的 sync_database_url）。

    注意例外是「一个文件」而不是「一个字符串」：允许 config.py 暴露这条 URL，
    但没允许任何业务代码去用它 —— 用没用由下一条用例盯。
    """
    offenders = sorted(
        path.relative_to(APP_DIR).as_posix()
        for path in APP_DIR.rglob("*.py")
        if "mysql+pymysql" in path.read_text(encoding="utf-8")
        and path.relative_to(APP_DIR).as_posix() not in SYNC_DRIVER_ALLOWLIST
    )

    assert not offenders, (
        f"这些文件出现了同步驱动连接串：{offenders}。"
        f"3.4 只允许 {sorted(SYNC_DRIVER_ALLOWLIST)} 为 Alembic 保留一条，"
        "业务链路一律走 asyncmy"
    )


def test_sync_engine_stays_inside_the_infrastructure_layer():
    """
    ★ 例外不能扩散到业务层：同步引擎只准活在 core/ 里。

    `core/config.py` 暴露 sync_database_url、`core/database.py` 用它建
    sync_engine —— 这两处都是基础设施，为 Alembic 服务，合理。

    但 api / services / agent 是业务链路，**任何一处引用都意味着可能有请求
    走同步连接**，而 3.4 禁止同步驱动的初衷正是防止业务请求占死同步连接池。
    所以这里只扫业务层三个目录，不扫 core/。
    """
    business_layers = ("api", "services", "agent")
    offenders = sorted(
        path.relative_to(APP_DIR).as_posix()
        for layer in business_layers
        for path in (APP_DIR / layer).rglob("*.py")
        if "sync_database_url" in path.read_text(encoding="utf-8")
        or "sync_engine" in path.read_text(encoding="utf-8")
        or "SyncSessionLocal" in path.read_text(encoding="utf-8")
    )

    assert not offenders, (
        f"这些业务层文件引用了同步引擎：{offenders}。"
        "同步引擎只供 Alembic 使用，业务链路一律走 async_engine / AsyncSessionLocal"
    )


def test_sync_engine_is_not_created_at_import_time():
    """
    ★ 同步引擎必须在函数体内惰性创建，不能写在模块顶层。

    `create_engine("mysql+pymysql://...")` 在调用那一刻就解析 DBAPI，
    写在顶层就等于要求「凡是 import app.core.database 的环境都得装 pymysql」。
    实测过这个后果：未装 pymysql 时 7 个测试模块在收集阶段直接
    ModuleNotFoundError，整套离线测试跑不起来 —— 而离线测试是本项目
    唯一的自动化防线。合并团队代码时正是踩了这里。

    用 AST 而非正则：只认「模块顶层语句里出现 sync_database_url」，
    写在函数体内（即惰性）一律放行，避免误伤注释与文档字符串。
    """
    import ast

    source = (APP_DIR / "core" / "database.py").read_text(encoding="utf-8")
    module = ast.parse(source)

    offenders: list[int] = []
    for stmt in module.body:
        # 顶层函数/类体内的创建是惰性的，符合要求，跳过不看
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for node in ast.walk(stmt):
            if isinstance(node, ast.Attribute) and node.attr == "sync_database_url":
                offenders.append(node.lineno)

    assert not offenders, (
        f"core/database.py 第 {offenders} 行在模块顶层引用了 sync_database_url："
        "这会让 import 该模块时就去解析 pymysql，应用启动与离线测试都会被拖住。"
        "请把创建逻辑放进函数，由 __getattr__ 惰性触发"
    )


def test_importing_database_module_leaves_the_sync_engine_unbuilt():
    """
    ★ 上一条的运行时直接证据：导入后模块字典里不该有 sync_engine。

    惰性实现把引擎存进 `_sync_engine`，故 `sync_engine` 这个名字
    永远不会出现在 `vars()` 里 —— 一旦有人改回顶层赋值，这条立刻红。
    """
    import app.core.database as db

    assert "sync_engine" not in vars(db), (
        "导入 app.core.database 时就构造了同步引擎；"
        "它应当只在首次访问时才创建"
    )
    assert "SyncSessionLocal" not in vars(db), (
        "导入 app.core.database 时就构造了同步会话工厂；应当惰性创建"
    )


def test_alembic_env_is_async_and_has_no_sync_url():
    """
    ⚠️ **2026-09-28 由 `test_alembic_env_still_consumes_the_sync_url` 反向改写。**

    原护栏的前提是「Alembic 的迁移环境是同步的，必须有一条 mysql+pymysql 连接串」，
    因此断言 `alembic/env.py` 引用了 `settings.sync_database_url`。
    **合并之后这个前提已经不成立**：团队把 Alembic 改成了**全异步迁移**
    （`async_engine_from_config` + `connection.run_sync`），同步引擎连同
    `Settings.sync_database_url` 一并删除 —— 理由见 `app/core/config.py`
    的「模块 3 引入的配置」段：「本仓库已把 Alembic 改为全异步迁移、
    requirements 也不再包含 PyMySQL，同步引擎已无任何消费者，留着只是死代码。」

    原断言因此在当下必红；而它要防的事（删掉 sync url 导致迁移 AttributeError）
    已经不可能发生 —— 现在要防的是**反向**的那个：
    有人让 env.py 又回去依赖一个 Settings 上并不存在的同步配置。
    """
    env_py = BACKEND_DIR / "alembic" / "env.py"
    if not env_py.is_file():
        pytest.skip("alembic/env.py 不在本仓库（未合并团队 Alembic 配置）")

    content = env_py.read_text(encoding="utf-8")

    assert "async_engine_from_config" in content, (
        "alembic/env.py 不再走异步迁移引擎。§3.4 要求全链路异步；"
        "若这是有意改回同步，必须同步改本用例并说明理由"
    )
    assert not re.search(r"settings\.sync_database_url", content), (
        "alembic/env.py 又引用了 settings.sync_database_url，"
        "但 Settings 上已无此属性（同步引擎已随全异步迁移一并移除）——"
        "这会在导入迁移环境时直接 AttributeError"
    )
    assert not hasattr(settings, "sync_database_url"), (
        "Settings 不应再暴露 sync_database_url：同步引擎没有任何消费者"
        "（见 app/core/config.py 的说明），留着只会诱导别人去用"
    )


def test_no_source_file_imports_a_sync_driver():
    import re

    pattern = re.compile(r"^\s*(import|from)\s+(pymysql|MySQLdb)\b", re.MULTILINE)
    offenders = [
        path.relative_to(BACKEND_DIR).as_posix()
        for path in APP_DIR.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert not offenders, f"这些文件导入了同步数据库驱动：{offenders}"


# ---------- 扫描配置 ----------


def test_scan_interval_is_positive():
    assert settings.CONFLICT_SCAN_INTERVAL_SECONDS > 0


def test_jwt_secret_has_no_default_in_production():
    """默认值只能用于本地；生产必须由 .env 覆盖（此用例防止默认值被当成真值）"""
    assert settings.JWT_SECRET_KEY


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("无人机,直播设备", ("无人机", "直播设备")),
        (" 无人机 , 直播设备 ", ("无人机", "直播设备")),
        ("无人机,,直播设备,", ("无人机", "直播设备")),
        ("", ()),
    ],
)
def test_csv_setting_parsing(monkeypatch, raw, expected):
    """列表型阈值走逗号分隔字符串，避开 .env 里 JSON 引号的坑"""
    monkeypatch.setattr(settings, "CONFLICT_HIGH_VALUE_DEVICE_TYPES", raw)
    assert settings.high_value_device_types == frozenset(expected)
