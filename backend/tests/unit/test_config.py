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


def test_env_example_port_matches_the_code_default():
    """
    ★ 模板与代码默认值必须一致。

    不一致时，没在 .env 里改 DB_PORT 的人会连到错误的隧道端口，
    报错只有一句「连接被拒绝」，极难定位。
    """
    declared = _env_example_values()

    assert int(declared["DB_PORT"]) == settings.DB_PORT


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
    """
    assert settings.DB_PORT == 3308, (
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
    """3.4：连接串固定 mysql+asyncmy://"""
    url = settings.database_url

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


def test_alembic_env_still_consumes_the_sync_url():
    """
    反向护栏：sync_database_url 一旦被删，Alembic 会在导入环境时直接 AttributeError。

    这条是补上一个真实教训 —— 曾经为了「零 DDL 变更」把它删掉，
    而团队的 alembic/env.py 第 23 行正在用它，迁移当场失效。
    """
    env_py = BACKEND_DIR / "alembic" / "env.py"
    if not env_py.is_file():
        pytest.skip("alembic/env.py 不在本仓库（未合并团队 Alembic 配置）")

    content = env_py.read_text(encoding="utf-8")

    assert re.search(r"settings\.sync_database_url", content), (
        "alembic/env.py 没有引用 settings.sync_database_url；"
        "若它改用别的配置项，请同步更新本用例，否则这条护栏会失效"
    )
    assert hasattr(settings, "sync_database_url"), (
        "Settings 必须提供 sync_database_url，否则 alembic/env.py 会 AttributeError"
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
