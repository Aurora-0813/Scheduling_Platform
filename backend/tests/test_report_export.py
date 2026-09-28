"""
阶段 3 - CSV 报告导出（E1–E15）

覆盖 `dashboard_export_service`（纯函数 + 落盘 + 过期清理）与它在 `generate_report` 里的接入点。

**为什么单独一个文件，而不是并进 D 组或 C 组**
D 组测的是 AI 容错、C 组测的是 HTTP 契约；导出是**第三个关注点**（文件 IO 与编码）。
混进去会让「D11 失败」这种告警指向不清。

**关于编码断言**
`utf-8-sig` 不是可选项：Excel 双击打开无 BOM 的 UTF-8 CSV 会按 GBK 解码，中文变乱码。
所以这里断言文件**真的**以 BOM 开头（EF BB BF），而不是只看代码里写了什么参数。

**关于清理用例（E11–E15）**
清理逻辑若不做时间注入就**根本没法测** —— 总不能真等 7 天。
所以 `cleanup_expired_exports(now=...)` 接受注入的「当前时间」，
用例用 `os.utime` 把 mtime 拨到过去，再把同一个时间注入进去。

⚠️ 做**边界**断言（E11）时，「注入 now」还**不够**：mtime 存的是 float 秒，
`datetime` → `float` → `datetime` 往返有亚微秒误差。若 now 用真实时钟、
mtime 也不截断，「恰好 7 天」会漂到过期侧 —— 实测 200 次里 16 次（8%），
断言变成随机的、靠运气过的。E11 的做法是：注入同一个 now **且** mtime 截断到整秒。
"""
import codecs
import csv
import io
import os
import re
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.services import dashboard_ai_service as ai_svc
from app.services import dashboard_export_service as export_svc
from app.services import dashboard_service as svc
from tests.test_api_contract import REPORT_PATH, STATS, client_with

DAYS = svc.DEFAULT_DAYS

SUGGESTIONS = [
    {
        "finding": "近 7 天场地使用率 46.7%",
        "evidence": "场地使用率 46.7%，最高峰在 14 点",
        "suggestion": "建议疏导至低谷时段",
    },
]


def _read_rows(text):
    """
    把 CSV 文本按 csv.reader 读回。

    ⚠️ 必须交给 `io.StringIO`，**不要** `text.splitlines()`：
    `splitlines()` 会把行尾的换行符一并吃掉，于是「带引号的多行字段」
    读回来就丢了换行（实测 `'第一行\\n第二行'` → `'第一行第二行'`）。
    那样 E3 这类转义用例会**假通过** —— 检查不出转义有没有做对。
    StringIO 保留行尾，csv.reader 自己就能把跨行引号字段拼回原值。
    """
    return list(csv.reader(io.StringIO(text)))


# ============================================================
# E1–E2：CSV 文本结构（纯函数，不碰磁盘）
# ============================================================
def test_E1_含四项统计与三要素表头及数据行():
    """E1：统计字段恰好四行；建议表有表头；每条例一行、序号从 1 递增"""
    rows = _read_rows(export_svc.build_csv_text(STATS, SUGGESTIONS, DAYS, degraded=False))

    labels = [row[0] for row in rows if row]
    for label in ("场地使用率(%)", "设备闲置率(%)", "预约高峰时段", "设备故障频次"):
        assert label in labels, f"CSV 缺统计字段行 {label}"

    header_index = next(i for i, row in enumerate(rows) if row[:1] == ["序号"])
    assert rows[header_index] == ["序号", "发现", "数据依据", "建议动作"]

    # 三要素逐列落位，序号从 1 开始
    assert rows[header_index + 1] == [
        "1", SUGGESTIONS[0]["finding"], SUGGESTIONS[0]["evidence"], SUGGESTIONS[0]["suggestion"],
    ]


def test_E2_列表字段格式化与空窗口占位():
    """E2：高峰/故障两个列表字段渲染成可读串；空列表不留空单元格"""
    rows = _read_rows(export_svc.build_csv_text(STATS, SUGGESTIONS, DAYS, degraded=False))
    values = {row[0]: row[1] for row in rows if len(row) >= 2}

    # STATS 的高峰有两条（14 点、9 点），用 `; ` 串起来
    assert values["预约高峰时段"] == "14点:5次; 9点:3次"
    assert values["设备故障频次"] == "投影仪A:3单"

    empty = {"spaceUsageRate": 0.0, "deviceIdleRate": 100.0,
             "peakHours": [], "faultFrequency": []}
    empty_values = {row[0]: row[1] for row in _read_rows(
        export_svc.build_csv_text(empty, SUGGESTIONS, DAYS, degraded=True)) if len(row) >= 2}

    assert empty_values["预约高峰时段"] == "窗口内无预约"
    assert empty_values["设备故障频次"] == "窗口内无维修工单"


def test_E3_含英文逗号与换行的字段被正确转义():
    """
    E3：字段里出现 `,` 或换行时，csv 模块会加引号 —— 这条防的是「手拼字符串」。

    若有人把实现改成 `",".join(...)`，含逗号的建议会把 CSV 列数冲乱，
    Excel 里表现为整张表错位。这条用例就是那个改法的哨兵。
    """
    tricky = [{"finding": "使用率 46.7%, 且高峰在 14 点",
               "evidence": "第一行\n第二行",
               "suggestion": '含 "引号" 的建议'}]
    text = export_svc.build_csv_text(STATS, tricky, DAYS, degraded=False)

    # 必须能被标准 csv 解析器读回原值 —— 手拼字符串在这里就会露馅
    rows = _read_rows(text)
    header_index = next(i for i, row in enumerate(rows) if row[:1] == ["序号"])
    assert rows[header_index + 1][1] == tricky[0]["finding"]
    assert rows[header_index + 1][2] == tricky[0]["evidence"]
    assert rows[header_index + 1][3] == tricky[0]["suggestion"]


def test_E4_表头块反映窗口天数与降级状态():
    """E4：窗口天数与是否降级写进表头块（看报告的人要能分辨建议是谁生成的）"""
    normal = {row[0]: row[1] for row in _read_rows(
        export_svc.build_csv_text(STATS, SUGGESTIONS, 30, degraded=False)) if len(row) >= 2}
    degraded = {row[0]: row[1] for row in _read_rows(
        export_svc.build_csv_text(STATS, SUGGESTIONS, 30, degraded=True)) if len(row) >= 2}

    assert normal["统计窗口(天)"] == "30"
    assert normal["是否降级"] == "否"
    assert degraded["是否降级"] == "是"


# ============================================================
# E5–E7：落盘
# ============================================================
async def test_E5_落盘返回相对路径且带BOM可被解析(export_dir):
    """E5：返回 `/static/exports/dashboard_YYYYMMDD_HHMMSS.csv`；文件带 BOM 且能读回"""
    url = await export_svc.write_report_csv(STATS, SUGGESTIONS, DAYS)

    assert re.match(r"^/static/exports/dashboard_\d{8}_\d{6}\.csv$", url), url

    file_path = export_dir / url.rsplit("/", 1)[1]
    assert file_path.exists(), "返回了链接却没有文件"

    raw = file_path.read_bytes()
    assert raw[:3] == codecs.BOM_UTF8, "utf-8-sig 的 BOM 缺失 —— Excel 打开会中文乱码"

    # 用 utf-8-sig 读回（会吃掉 BOM），确认内容可解析、中文没坏
    text = file_path.read_text(encoding="utf-8-sig")
    assert "场地使用率(%)" in text
    assert SUGGESTIONS[0]["finding"] in text


async def test_E6_目录不存在时自动创建(tmp_path, monkeypatch):
    """E6：导出目录不存在 → 自动创建（克隆仓库后没建过 static/exports 也能跑）"""
    nested = tmp_path / "not" / "yet" / "created"
    monkeypatch.setattr(export_svc, "EXPORT_DIR", nested)

    url = await export_svc.write_report_csv(STATS, SUGGESTIONS, DAYS)

    assert nested.is_dir()
    assert (nested / url.rsplit("/", 1)[1]).exists()


async def test_E7_csv里的统计与传入的stats同源(export_dir):
    """
    E7：CSV 里的统计数字就是**调用方传进来的那一份**，不是重新查库的结果。

    这条锁的是文件头写明的设计意图：若导出服务自己再查一次库，
    报告里就会出现「建议说 46.7%、表格写 48.2%」的自相矛盾。
    用法：传一份**不可能查得到**的 stats，若 CSV 里出现了它，就证明没有二次取数。
    """
    sentinel = {"spaceUsageRate": 12.3, "deviceIdleRate": 87.6,
                "peakHours": [{"hour": 3, "count": 1}],
                "faultFrequency": [{"deviceName": "哨兵设备", "count": 9}]}

    url = await export_svc.write_report_csv(sentinel, SUGGESTIONS, DAYS)
    text = (export_dir / url.rsplit("/", 1)[1]).read_text(encoding="utf-8-sig")

    assert "12.3" in text and "87.6" in text
    assert "哨兵设备:9单" in text


# ============================================================
# E8–E9：失败与接入
# ============================================================
async def test_E8_写盘失败时向上抛由调用方兜住(monkeypatch):
    """
    E8：写盘失败（磁盘满 / 无权限）→ 本函数**向上抛**。

    分工如此：这里抛，`generate_report` 兜住并把 exportUrl 置 null。
    本函数若自行吞掉异常，调用方就无从知道「有没有真的导出成功」。
    """
    def _boom(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(export_svc, "aiofiles", types.SimpleNamespace(open=_boom))

    with pytest.raises(OSError):
        await export_svc.write_report_csv(STATS, SUGGESTIONS, DAYS)


async def test_E9_导出失败不影响报告只置空exportUrl(monkeypatch, sample_stats, no_llm_key, export_dir):
    """
    E9：导出失败时报告的其余部分照常返回，exportUrl 为 null，且**不抛异常**。

    走的是**真实降级路径**（`no_llm_key` → `_build_llm` 抛 `_LLMUnavailable`），
    刻意**不**装假模型 —— 装了假模型就等于绕过 `_build_llm` 的 key 检查，
    `degraded` 会是 false，这条用例就测不到降级分支了。
    """
    def _boom(*_args, **_kwargs):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(export_svc, "aiofiles", types.SimpleNamespace(open=_boom))

    async def _get(_db, days=DAYS):
        return sample_stats
    monkeypatch.setattr(svc, "get_all_stats", _get)

    result = await ai_svc.generate_report(None, DAYS)

    assert result["exportUrl"] is None, "导出失败 → exportUrl 置空"
    assert result["suggestions"], "导出失败不该连建议一起丢"
    assert result["degraded"] is True


# ============================================================
# E10：挂载点与 URL 前缀一致性
# ============================================================
def test_E10_静态挂载点与export前缀一致_能真的下载到(monkeypatch, no_llm_key):
    """
    E10：`main.py` 的 StaticFiles 挂载点与 `EXPORT_URL_PREFIX` 一致
    → 导出的文件能通过 exportUrl 真的下载到。

    这条抓的是「改了 URL 前缀、忘了改挂载点」的漂移 ——
    两处隔着两个文件，靠人眼核对很容易漏，而症状是导出按钮 404。

    ⚠️ 本用例刻意**覆盖** conftest 的导出目录隔离，用真实的 `backend/static/exports/`：
    只有真实目录才在 StaticFiles 的服务范围内。用完自己删文件（见 finally）。
    """
    real_dir = export_svc.BACKEND_DIR / "static" / "exports"
    monkeypatch.setattr(export_svc, "EXPORT_DIR", real_dir)

    async def _stub(_db, days=svc.DEFAULT_DAYS):
        return STATS
    monkeypatch.setattr(svc, "get_all_stats", _stub)

    created = []
    try:
        with client_with(_stub) as api:
            url = api.get(REPORT_PATH).json()["data"]["exportUrl"]
            assert url, "导出链接为空，无法验证挂载点"
            created.append(real_dir / url.rsplit("/", 1)[1])

            downloaded = api.get(url)

        assert downloaded.status_code == 200, \
            f"{url} 取不到（挂载点与 EXPORT_URL_PREFIX 不一致？）"
        assert downloaded.content[:3] == codecs.BOM_UTF8
        assert b"AI" in downloaded.content
    finally:
        # 不留下运行时产物：这个目录是 gitignore 的产物目录，不该被测试塞东西
        for path in created:
            path.unlink(missing_ok=True)


# ============================================================
# E11–E15：过期清理
# ============================================================
def _plant(directory, name, when, content="x"):
    """
    在导出目录里放一个 mtime 为 `when` 的文件。

    ⚠️ 两个必须的细节：

    1. **要自己建目录** —— `export_dir` fixture 只把 EXPORT_DIR 指到临时路径，
       并不创建它（平时由 `write_report_csv` 自己 mkdir）。
    2. **`when` 截断到整秒** —— mtime 存的是 float 秒，`datetime` → `float` → `datetime`
       的往返会带亚微秒误差。做**边界**断言时那点误差足以让文件落到线的一侧：
       实测 200 次里 16 次「恰好 7 天」被算成 7 天零 0.0005 秒，于是被判过期。
       整秒的 epoch 值是 float 精确可表示的，截断后往返无损，
       边界比对才是确定的（配合 E11 注入同一个 `now`）。
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(content, encoding="utf-8")

    stamp = when.replace(microsecond=0).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def test_E11_过期文件被删未过期保留_且边界精确(export_dir):
    """
    E11：超过保留期的删掉，没超过的留着；返回值 = 实际删除数。

    **边界锁（双向）**：保留期是 7 天，判定是 `age > 保留期`，所以
    「恰好 7 天整」不删、「7 天零 1 秒」删。两个方向都要有 ——
    只断言「7 天整不删」的话，一个**什么都不删**的实现也能通过。

    ⚠️ 这里把 `now` 显式注入，不用真实时钟：
    真实时钟下 `now` 比造 mtime 时晚几微秒，「恰好 7 天」会漂到过期侧（实测 200 次里 16 次），
    断言变成随机的。注入 + mtime 截断到整秒后完全确定。
    """
    reference = datetime.now().replace(microsecond=0)

    old = _plant(export_dir, "dashboard_20260901_000000.csv",
                 reference - timedelta(days=8))
    just_over = _plant(export_dir, "dashboard_20260902_000000.csv",
                       reference - timedelta(days=7, seconds=1))
    exactly = _plant(export_dir, "dashboard_20260920_000000.csv",
                     reference - timedelta(days=7))
    fresh = _plant(export_dir, "dashboard_20260927_000000.csv",
                   reference - timedelta(days=1))

    removed = export_svc.cleanup_expired_exports(now=reference, retention_days=7)

    assert removed == 2, f"应删掉 8 天前与 7 天零 1 秒那两个，实际删了 {removed} 个"
    assert not old.exists(), "8 天前的应被删"
    assert not just_over.exists(), "超过 7 天 1 秒就该删（证明阈值确实在 7 天）"
    assert exactly.exists(), "恰好 7 天整不该被删（判定是 age > 保留期，不是 >=）"
    assert fresh.exists(), "1 天前的不该被删"


async def test_E12_只删自己生成的文件不碰同目录其他文件(export_dir):
    """
    E12：只按 `dashboard_*.csv` 匹配 —— 同事因调试放进同目录的东西**不动**。

    这条防的是「有人把 glob 写成 `*` 就顺手清空整个目录」。
    """
    long_ago = datetime.now() - timedelta(days=30)
    ours_old = _plant(export_dir, "dashboard_20260901_000000.csv", long_ago)
    theirs = _plant(export_dir, "someone_else_debug.csv", long_ago)
    theirs_txt = _plant(export_dir, "notes.txt", long_ago)

    removed = export_svc.cleanup_expired_exports(retention_days=7)

    assert removed == 1
    assert not ours_old.exists()
    assert theirs.exists(), "不是 dashboard_*.csv，不该被删"
    assert theirs_txt.exists(), "不是 CSV，不该被删"


async def test_E13_导出时顺手清理过期文件(export_dir):
    """
    E13：惰性清理 —— 调 `write_report_csv` 就会顺带清掉过期文件。

    这是「不引入调度库也能自动维护」的关键：只要还在生成报告，目录就不会涨。
    这条走**真实时钟**（不注入 now），因为要验的正是「生产路径没传 now 也能清」。
    所以挑一个离边界很远的时长（30 天），避免任何时钟漂移影响。
    """
    stale = _plant(export_dir, "dashboard_20260901_000000.csv",
                   datetime.now() - timedelta(days=30))

    await export_svc.write_report_csv(STATS, SUGGESTIONS, DAYS)

    assert not stale.exists(), "导出时应顺手清掉过期文件"


async def test_E14_单个文件删不掉不影响其余清理也不抛异常(export_dir, monkeypatch):
    """
    E14：某个文件删不掉（被 Excel 占用 / 权限）→ 只记 warning，继续删别的，**不抛异常**。

    清理是后台维护动作，不能因为它失败就把正在生成报告的那条业务路径带崩。
    """
    long_ago = datetime.now() - timedelta(days=30)
    blocked = _plant(export_dir, "dashboard_20260901_000000.csv", long_ago)
    removable = _plant(export_dir, "dashboard_20260902_000000.csv", long_ago)

    real_unlink = Path.unlink

    def _unlink(self, *args, **kwargs):
        if self.name == blocked.name:
            raise PermissionError(13, "Permission denied")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _unlink)

    removed = export_svc.cleanup_expired_exports(retention_days=7)   # 不该抛

    assert removed == 1, "另一个仍应被删掉"
    assert not removable.exists()
    assert blocked.exists(), "删不掉的就留着，下一轮再试"


async def test_E15_导出本身不受清理失败影响(export_dir, monkeypatch):
    """
    E15：清理步骤抛异常时，**导出照样成功**（exportUrl 仍返回路径）。

    与 E14 的区别：E14 测「清理自己吞掉单个文件的失败」，
    这条测「假设清理整体崩了，导出这条业务路径是否还活着」——
    所以这里直接把 cleanup 换成会抛的函数。
    """
    def _boom(*_args, **_kwargs):
        raise RuntimeError("模拟清理整体异常")

    monkeypatch.setattr(export_svc, "cleanup_expired_exports", _boom)

    url = await export_svc.write_report_csv(STATS, SUGGESTIONS, DAYS)

    assert re.match(r"^/static/exports/dashboard_\d{8}_\d{6}\.csv$", url), url
    assert (export_dir / url.rsplit("/", 1)[1]).exists()
