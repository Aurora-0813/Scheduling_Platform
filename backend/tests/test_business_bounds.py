"""
五、业务边界校验 / 幻觉拦截（H1–H12）—— 对应 docs/test.md 第五节

实现见 `dashboard_ai_service._filter_by_business_bounds`（《规范》9.3）。
思路：stats 里的数字是**唯一事实来源**，递归展开成白名单，
逐条校验 AI 输出的 `finding` / `evidence` 是否只引用了白名单内的数字。

校验范围只含 `finding` 与 `evidence` —— 这两个字段断言「事实」；
`suggestion` 是行动建议（如「避开 14:00 时段」），其数字来自 finding，不重复校验。

**H9 是缺陷回归，不要删**：初版 `_is_allowed` 把待校验数字四舍五入后去比对白名单，
导致白名单里有整数 3 时，编造的「闲置率 3.2%」因 `round(3.2) == 3` 被放行 ——
等价于给每个整数允许值开了 ±0.5 的口子。修正后变体只加在白名单一侧、
按容差判等，绝不取整待校验值。详见 docs/test.md 第五节。
"""
import json

import pytest

from app.services import dashboard_ai_service as ai_svc
from app.services import dashboard_service
from tests.helpers import fake_model, human_text, install_fake_llm, suggestions_text

DAYS = dashboard_service.DEFAULT_DAYS


# ------------------------------------------------------------
# 素材：数字全部来自 sample_stats 的白名单
#   sample_stats = 46.7 / 20.0 / peakHours(14, 5) / faultFrequency(3) + days 7
# ------------------------------------------------------------
VALID_ROWS = (
    ("近 7 天场地使用率 46.7%", "场地使用率 46.7%，最高峰在 14 点", "建议疏导至低谷时段"),
    ("设备闲置率 20.0%", "闲置率 20.0%，14 点有 5 条预约", "建议核查高闲置设备"),
    ("设备「投影仪A」故障 3 单居首", "故障频次统计 3 单，窗口 7 天", "建议排查投影仪A"),
)

FABRICATED_ROW = ("场地使用率高达 85.3%", "相比上周上升 12.4%", "建议扩容")

# 编造内容里出现过的数字，用于断言「一条都没漏出去」
FABRICATED_NUMBERS = ("85.3", "12.4")


def _enable_retry(monkeypatch, enabled=True):
    monkeypatch.setattr(ai_svc, "HALLUCINATION_RETRY_ENABLED", enabled)


def _stub_stats(monkeypatch, stats):
    async def _get(_db, days=DAYS):
        return stats
    monkeypatch.setattr(dashboard_service, "get_all_stats", _get)


def _dump(result) -> str:
    return json.dumps(result, ensure_ascii=False)


# ============================================================
# H1–H3：过滤的基本行为
# ============================================================
async def test_H1_全部有据可依时全保留且只调一次(monkeypatch, sample_stats):
    """H1：3 条建议的数字全部来自 stats → 全部保留，degraded=False，只调 1 次 LLM"""
    _enable_retry(monkeypatch, False)
    _stub_stats(monkeypatch, sample_stats)
    model = install_fake_llm(monkeypatch, fake_model(suggestions_text(*VALID_ROWS)))

    result = await ai_svc.generate_report(None, DAYS)

    assert result["degraded"] is False
    assert len(result["suggestions"]) == 3
    assert model.calls == 1
    # 首轮不应带重试指令。
    # 必须取消息**正文**比对 —— `str(model.received[0])` 是 repr，
    # 会把 `_RETRY_INSTRUCTION` 开头的换行转义成 `\n`，此断言就恒真了（见 helpers.human_text）。
    assert ai_svc._RETRY_INSTRUCTION not in human_text(model.received[0])


async def test_H2_全部编造时全部丢弃并降级(monkeypatch, sample_stats):
    """H2：数字全部编造 → 全部丢弃走降级，**编造内容一条都不出现在响应里**"""
    _enable_retry(monkeypatch, False)
    _stub_stats(monkeypatch, sample_stats)
    install_fake_llm(monkeypatch, fake_model(suggestions_text(FABRICATED_ROW)))

    result = await ai_svc.generate_report(None, DAYS)
    dumped = _dump(result)

    assert result["degraded"] is True
    assert result["suggestions"]
    for number in FABRICATED_NUMBERS:
        assert number not in dumped, f"编造的数字 {number} 泄漏到了响应里"
    assert "建议扩容" not in dumped


async def test_H3_部分编造时只丢编造的那条(monkeypatch, sample_stats):
    """H3：2 条有效 + 1 条编造 → 只保留 2 条有效，degraded=False"""
    _enable_retry(monkeypatch, False)
    _stub_stats(monkeypatch, sample_stats)
    install_fake_llm(monkeypatch, fake_model(
        suggestions_text(VALID_ROWS[0], FABRICATED_ROW, VALID_ROWS[1])
    ))

    result = await ai_svc.generate_report(None, DAYS)

    assert result["degraded"] is False
    assert len(result["suggestions"]) == 2
    findings = [item["finding"] for item in result["suggestions"]]
    assert VALID_ROWS[0][0] in findings
    assert VALID_ROWS[1][0] in findings
    assert "85.3" not in _dump(result)


# ============================================================
# H4–H7：重试开关两种取值
# ============================================================
async def test_H4_首轮全编造重试通过时采用重试结果(monkeypatch, sample_stats):
    """H4：首轮全编造、重试通过（开关 = True）→ 调 2 次，第二轮收到重试指令，degraded=False"""
    _enable_retry(monkeypatch, True)
    _stub_stats(monkeypatch, sample_stats)
    model = install_fake_llm(monkeypatch, fake_model(
        suggestions_text(FABRICATED_ROW),          # 首轮：编造
        suggestions_text(VALID_ROWS[0]),           # 重试：有据
    ))

    result = await ai_svc.generate_report(None, DAYS)

    assert model.calls == 2
    assert ai_svc._RETRY_INSTRUCTION not in human_text(model.received[0]), "首轮不该带重试指令"
    assert ai_svc._RETRY_INSTRUCTION in human_text(model.received[1]), "重试时必须把上一轮错在哪告诉模型"
    assert result["degraded"] is False
    assert [item["finding"] for item in result["suggestions"]] == [VALID_ROWS[0][0]]


async def test_H5_重试仍编造时降级且不漏出(monkeypatch, sample_stats):
    """H5：首轮全编造、重试仍编造（开关 = True）→ 调 2 次，degraded=True，编造内容未漏出"""
    _enable_retry(monkeypatch, True)
    _stub_stats(monkeypatch, sample_stats)
    model = install_fake_llm(monkeypatch, fake_model(
        suggestions_text(FABRICATED_ROW),
        suggestions_text(FABRICATED_ROW),
    ))

    result = await ai_svc.generate_report(None, DAYS)
    dumped = _dump(result)

    assert model.calls == 2
    assert result["degraded"] is True
    for number in FABRICATED_NUMBERS:
        assert number not in dumped


async def test_H6_首轮通过时不触发重试(monkeypatch, sample_stats):
    """H6：首轮通过（开关 = True）→ 只调 1 次 LLM，不触发重试"""
    _enable_retry(monkeypatch, True)
    _stub_stats(monkeypatch, sample_stats)
    model = install_fake_llm(monkeypatch, fake_model(suggestions_text(*VALID_ROWS)))

    result = await ai_svc.generate_report(None, DAYS)

    assert model.calls == 1
    assert ai_svc._RETRY_INSTRUCTION not in human_text(model.received[0]), "开关开着但首轮通过，不该带重试指令"
    assert result["degraded"] is False


async def test_H7_关闭校验开关时原样返回(monkeypatch, sample_stats):
    """H7：HALLUCINATION_CHECK_ENABLED = False + 编造内容 → 原样返回、不过滤（开关的回归保护）"""
    monkeypatch.setattr(ai_svc, "HALLUCINATION_CHECK_ENABLED", False)
    _enable_retry(monkeypatch, False)
    _stub_stats(monkeypatch, sample_stats)
    install_fake_llm(monkeypatch, fake_model(suggestions_text(FABRICATED_ROW)))

    result = await ai_svc.generate_report(None, DAYS)

    assert result["degraded"] is False
    assert result["suggestions"][0]["finding"] == FABRICATED_ROW[0]


# ============================================================
# H8：数字提取（时间不拆成分钟）
# ============================================================
def test_H8_时间只取小时不拆成分钟():
    """

    `"14:00"` 若被拆成 14 和 0，那个 0 通常不在白名单里，会造成误判。
    """
    assert ai_svc._extract_numbers("建议避开 14:00 的高峰时段") == [14.0]
    assert 0.0 not in ai_svc._extract_numbers("建议避开 14:00 的高峰时段")
    assert ai_svc._extract_numbers("14:30:00 开始") == [14.0]


# ============================================================
# H9–H10：白名单比对（H9 是缺陷回归）
# ============================================================
def test_H9_近似值与改写精度全部拦下():
    """
    H9：`3.2` / `3.4` / `46.9` / `47` 全部拦下（白名单有 `3`、`46.7`）。

    这条用例锁的就是「round 待校验值」那个缺陷：
    旧实现下 `3.2` 会因为 `round(3.2) == 3` 被放行。
    """
    allowed = ai_svc._collect_allowed_numbers({"a": 3, "b": 46.7}, DAYS)

    assert 3.0 in allowed, "白名单里必须有整数 3，否则这条回归用例证明不了什么"
    assert 46.7 in allowed

    for number in (3.2, 3.4, 46.9, 47.0):
        assert not ai_svc._is_allowed(number, allowed), f"{number} 无据可依，必须拦下"


def test_H10_原样值与纯换算写法放行():
    """H10：原样值 `46.7` / `3`，以及纯换算 `0.467` 全部放行"""
    allowed = ai_svc._collect_allowed_numbers({"a": 3, "b": 46.7}, DAYS)

    for number in (46.7, 3.0, 0.467):
        assert ai_svc._is_allowed(number, allowed), f"{number} 有据可依，应当放行"


# ============================================================
# H11–H12：不变式与白名单构造
# ============================================================
@pytest.mark.parametrize("fixture_name", ["sample_stats", "empty_window_stats"])
def test_H11_降级模板产出必须通过自己的校验(fixture_name, request):
    """
    H11：降级模板产出的建议回灌校验 → 全部通过。

    **降级路径不得被自己的校验拦掉** —— 那两个数字都取自 stats，
    若被拦就意味着会陷入「降级 → 被拦 → 再降级」的死循环。
    有数据与空窗口两种 stats 都要测。
    """
    stats = request.getfixturevalue(fixture_name)

    suggestions = ai_svc._degraded_suggestions(stats, DAYS)
    kept, dropped = ai_svc._filter_by_business_bounds(suggestions, stats, DAYS)

    assert suggestions, "降级路径必须给出建议，不能是空数组"
    assert dropped == []
    assert kept == suggestions


def test_H12_白名单的收录与排除(sample_stats):
    """H12：白名单含 days、原值、整数写法、`0.2` ↔ `20` 两种写法；不含编造值"""
    allowed = ai_svc._collect_allowed_numbers(sample_stats, DAYS)

    # 收录
    assert 7.0 in allowed, "「近 7 天」的 7（days）必须收录"
    assert 46.7 in allowed, "原值必须收录"
    assert 0.467 in allowed, "分数的纯换算写法也应收录"
    assert 3.0 in allowed, "整数原值必须收录"
    assert 0.2 in allowed, "0.2 ↔ 20 两种写法互通"

    # 排除：非整数原值不得被「约等于」成整数
    assert 47.0 not in allowed
    assert 21.0 not in allowed

    # 排除：编造值
    assert 85.3 not in allowed
    assert 999.0 not in allowed
