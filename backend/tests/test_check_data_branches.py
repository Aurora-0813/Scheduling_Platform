"""
一、`check_data.py` 控制台分支（A–E）—— 对应 docs/test.md 第一节

这 5 条验证的是**诊断脚本的输出分支**，不是生产业务逻辑。
所以断言对象是「打印了哪句话」，没有分母也没有使用率（那两个指标属 U 系列）。

做法的取舍（重要）：
`_check_space_open_time()` 自身不含任何 SQL 语义 —— 它只是把查回来的行
分类、统计、打印。因此测试的**主语是分类与打印逻辑**，喂什么行由测试决定。

- A / B / D / E 走**真实 SQLite 引擎**（conftest 的 build_session），
  顺带覆盖了「真驱动把 Time / NULL 读成什么」这一段。
- C（值为字符串）**只能用手工假 conn**：实测 SQLAlchemy 的 `Time` 列在 SQLite 上
  会把字符串也转换回 `datetime.time`（连裸 SQL 写进去的 `'08:00:00'` 也一样），
  所以「字段里真躺着 str」这种形态无法经 ORM 复现。
  这也正是 docs/test.md 规定「用假 conn 直接调用」的原因。
"""
import importlib.util
from datetime import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.helpers import build_session, make_space

# 以文件路径加载诊断脚本：scripts/ 不是包，且不该为了测试给它加 __init__.py
_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "check_data.py"


def _load_check_data():
    spec = importlib.util.spec_from_file_location("check_data_under_test", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_data = _load_check_data()


# ============================================================
# C 专用的手工假 conn
# ============================================================
class _FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar(self):
        return self._scalar

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    """
    按调用顺序返回预设结果。

    刻意在多发查询时报错：脚本一旦改了查询顺序，
    测试必须失败而不是继续用错位的结果假绿。
    """

    def __init__(self, row_count, sample_rows, all_rows):
        self._results = [
            _FakeResult(scalar=row_count),      # 1) COUNT(*)
            _FakeResult(rows=sample_rows),      # 2) 前 5 条样本
            _FakeResult(rows=all_rows),         # 3) 全表
        ]
        self._index = 0

    async def execute(self, statement):
        assert self._index < len(self._results), "check_data 多发了查询，脚本可能已改动"
        result = self._results[self._index]
        self._index += 1
        return result


def _row(row_id, start, end):
    return SimpleNamespace(
        id=row_id, space_name=f"场地{row_id}", capacity=10, status=1,
        open_start_time=start, open_end_time=end,
    )


# ============================================================
# A–E
# ============================================================
async def test_A_全为time且无空值(capsys):
    """A：5 条，全 datetime.time，无 NULL"""
    session = build_session(
        spaces=[make_space(i, open_start=time(8 + i), open_end=time(22)) for i in range(1, 6)]
    )

    await check_data._check_space_open_time(session)
    out = capsys.readouterr().out

    assert "无 NULL 行" in out
    assert "分母可完全按各场地实际开放时段累加" in out
    assert "非空值类型均为 datetime.time" in out
    assert "存在 NULL 行" not in out
    # 2026-09-28 起脚本会调 _open_hours 实算分母，无兜底行
    assert "无兜底行" in out


async def test_B_部分为空值(capsys):
    """B：8 条，5 条 time + 3 条 NULL"""
    spaces = [make_space(i, open_start=time(9), open_end=time(18)) for i in range(1, 6)]
    spaces += [make_space(i) for i in range(6, 9)]       # open_* 均为 None

    await check_data._check_space_open_time(build_session(spaces=spaces))
    out = capsys.readouterr().out

    assert "存在 NULL 行" in out
    assert "start 3 条 / end 3 条" in out
    assert "不作为「不可用」排除" in out
    assert "非空值类型均为 datetime.time" in out
    # 3 条 NULL 行必须被逐行点名 + 标出兜底原因，而不是只报个总数
    assert "3 条走的是兜底" in out
    assert "← 兜底：时段为 NULL" in out


async def test_C_值为字符串(capsys):
    """
    C：5 条，值全为字符串 '08:00:00'。

    手工假 conn —— 见文件头说明，字符串无法经 ORM 复现。

    ⚠️ 2026-09-28 这条救了一个真 bug：脚本改成「调 `_open_hours` 实算分母」后，
    `end.hour - start.hour` 遇到 str 会直接 `AttributeError` 崩掉。
    旧脚本只打印类型、从不实算，所以没暴露。
    修法是把**类型核对提到实算之前**并早退 —— 诊断脚本的职责是报告，不是崩掉。
    """
    sample = [_row(i, "08:00:00", "22:00:00") for i in range(1, 6)]
    conn = _FakeConn(row_count=5, sample_rows=sample, all_rows=sample)

    await check_data._check_space_open_time(conn)
    out = capsys.readouterr().out

    assert "['str']" in out
    assert "统一解析后再看" in out
    assert "非空值类型均为 datetime.time" not in out
    # 类型对不上时**不往下算**，也不对分母下任何结论
    assert "先不实算分母" in out
    assert "无 NULL 行" not in out
    assert "分母可完全按各场地实际开放时段累加" not in out


async def test_F_无可用场地(capsys):
    """
    F：全是 status = 0 的停用场地 → 分母为 0，服务早退返回 0.0。

    这条锁的是 2026-09-28 新增的分支：脚本必须说清「这是设计行为，不是故障」，
    而不是打一行「合计 0.0 h/天」让人以为场地时段没填。
    """
    spaces = [make_space(i, status=0, open_start=time(9), open_end=time(18))
              for i in range(1, 3)]

    await check_data._check_space_open_time(build_session(spaces=spaces))
    out = capsys.readouterr().out

    assert "没有 status=1 的可用场地" in out
    assert "不是故障" in out
    assert "合计" not in out


async def test_D_全为空值(capsys):
    """D：3 条，全 NULL"""
    await check_data._check_space_open_time(
        build_session(spaces=[make_space(i) for i in range(1, 4)])
    )
    out = capsys.readouterr().out

    assert "存在 NULL 行" in out
    assert "该字段全部为 NULL" in out


async def test_E_表为空(capsys):
    """E：表为空（COUNT = 0）"""
    await check_data._check_space_open_time(build_session(spaces=[]))
    out = capsys.readouterr().out

    assert "无数据，无法确认" in out
    # 空表时应当在第一次查询后就返回，不应再打印分布
    assert "全表" not in out


async def test_假conn多发查询会报错():
    """自检：假 conn 的错位保护本身有效（防止脚本改动后测试假绿）"""
    conn = _FakeConn(row_count=5, sample_rows=[], all_rows=[])

    with pytest.raises(AssertionError, match="多发了查询"):
        for _ in range(4):
            await conn.execute(None)
