"""
四、AI 服务容错与降级（D1–D15）—— 对应 docs/test.md 第四节

用假 LLM 夹具离线执行，不依赖真实 API（《规范》10.2）。

**夹具分工**（答辩若问「离线怎么测大模型逻辑」）：
- `FakeMessagesListChatModel`：数据真的流过 `_invoke_llm` 的三层容错 ——
  第 1 层 `with_structured_output` 在假模型上抛 `NotImplementedError`，
  于是落到第 2 层 `json.loads`。**全程零网络调用**。
- 慢速假模型（`SlowFakeModel`）：`_generate` 里睡 5 秒，用来触发超时降级。
- 取数函数替换：D12/D13 证明库不可达时走的是「说明失败」而非「编造数字」。

网络边界只在 `_build_llm` 一处被替换（`install_fake_llm`），
其余全是生产代码。
"""
import json
from datetime import datetime

import pytest
from langchain_core.messages import AIMessage

from app.core.config import settings
from app.services import dashboard_ai_service as ai_svc
from app.services import dashboard_service
from tests.helpers import (
    SlowFakeModel,
    fake_model,
    install_fake_llm,
    suggestions_text,
)

DAYS = dashboard_service.DEFAULT_DAYS


# ------------------------------------------------------------
# 助手
# ------------------------------------------------------------
def stub_stats(monkeypatch, stats):
    """把取数换成固定 stats（避免 D 组依赖数据库）"""
    async def _get(_db, days=DAYS):
        return stats
    monkeypatch.setattr(dashboard_service, "get_all_stats", _get)


def stub_stats_error(monkeypatch, exc_type=RuntimeError):
    """取数直接抛异常，模拟数据库不可达"""
    async def _boom(_db, days=DAYS):
        raise exc_type("模拟数据库不可达")
    monkeypatch.setattr(dashboard_service, "get_all_stats", _boom)


def _three_keys_ok(item) -> bool:
    return all(isinstance(item.get(k), str) and item[k].strip()
               for k in ("finding", "evidence", "suggestion"))


# ============================================================
# D1–D6：`_build_llm` / 三层容错
# ============================================================
def test_D1_无key时抛LLMUnavailable且不构造客户端(monkeypatch):
    """D1：LLM_API_KEY 为空 → 抛 `_LLMUnavailable`，且不发起任何网络调用"""
    monkeypatch.setattr(settings, "LLM_API_KEY", "")

    def _boom(*_args, **_kwargs):
        raise AssertionError("未配置 key 时不应构造任何 LLM 客户端")

    monkeypatch.setattr("langchain_openai.ChatOpenAI", _boom)

    with pytest.raises(ai_svc._LLMUnavailable) as exc:
        ai_svc._build_llm()

    assert "LLM_API_KEY" in str(exc.value)


async def test_D2_纯JSON走第2层(monkeypatch, sample_stats):
    """D2：假模型返回纯 JSON 文本 → 第 2 层 json.loads 成功，返回 1 条"""
    model = fake_model(suggestions_text(("发现 46.7%", "依据 46.7%", "建议动作")))
    install_fake_llm(monkeypatch, model)

    items = await ai_svc._invoke_llm(sample_stats, DAYS)

    assert len(items) == 1
    assert _three_keys_ok(items[0])


async def test_D3_围栏JSON走第3层(monkeypatch, sample_stats):
    """D3：假模型返回含 ```json 围栏的文本 → 第 3 层正则抠块成功"""
    body = suggestions_text(("发现 46.7%", "依据 46.7%", "建议动作"))
    install_fake_llm(monkeypatch, fake_model(f"```json\n{body}\n```"))

    items = await ai_svc._invoke_llm(sample_stats, DAYS)

    assert len(items) == 1


async def test_D4_散文中的JSON走第3层抠括号(monkeypatch, sample_stats):
    """D4：无围栏、夹在散文里的 JSON → 第 3 层抠最外层 {} 成功"""
    body = suggestions_text(("发现 46.7%", "依据 46.7%", "建议动作"))
    install_fake_llm(monkeypatch, fake_model(f"好的，分析结果如下：{body}\n以上。"))

    items = await ai_svc._invoke_llm(sample_stats, DAYS)

    assert len(items) == 1


async def test_D5_缺三要素被丢弃后三层全败(monkeypatch, sample_stats):
    """D5：建议缺 suggestion 字段 → `_normalize` 丢弃该条 → 三层全败抛异常"""
    bad = json.dumps({"suggestions": [{"finding": "有数字 46.7", "evidence": "依据"}]},
                     ensure_ascii=False)
    install_fake_llm(monkeypatch, fake_model(bad))

    with pytest.raises(ai_svc._LLMUnavailable):
        await ai_svc._invoke_llm(sample_stats, DAYS)


async def test_D6_模型拒答三层全败(monkeypatch, sample_stats):
    """D6：假模型返回「抱歉，我无法完成」→ 三层全败抛异常"""
    install_fake_llm(monkeypatch, fake_model("抱歉，我无法完成这个请求。"))

    with pytest.raises(ai_svc._LLMUnavailable):
        await ai_svc._invoke_llm(sample_stats, DAYS)


# ============================================================
# D7–D11：端到端降级
# ============================================================
async def test_D7_超时走降级(monkeypatch, sample_stats):
    """D7：假模型 `_generate` 睡 5s，超时上限调至 0.2 → degraded=True"""
    monkeypatch.setattr(ai_svc, "LLM_TIMEOUT_SECONDS", 0.2)
    install_fake_llm(monkeypatch, SlowFakeModel(responses=[AIMessage(content="{}")], delay=1.0))
    stub_stats(monkeypatch, sample_stats)

    result = await ai_svc.generate_report(None, DAYS)

    assert result["degraded"] is True


async def test_D8_超时降级后建议非空且三要素齐全(monkeypatch, sample_stats):
    """D8：同 D7 —— 降级后 suggestions 非空且三要素齐全"""
    monkeypatch.setattr(ai_svc, "LLM_TIMEOUT_SECONDS", 0.2)
    install_fake_llm(monkeypatch, SlowFakeModel(responses=[AIMessage(content="{}")], delay=1.0))
    stub_stats(monkeypatch, sample_stats)

    result = await ai_svc.generate_report(None, DAYS)

    assert result["suggestions"], "降级也必须给出建议，不能返回空数组"
    assert all(_three_keys_ok(item) for item in result["suggestions"])


async def test_D9_无key端到端降级(monkeypatch, sample_stats):
    """D9：同 D1，走 `generate_report` 端到端 → degraded=True 且建议非空"""
    monkeypatch.setattr(settings, "LLM_API_KEY", "")
    stub_stats(monkeypatch, sample_stats)

    result = await ai_svc.generate_report(None, DAYS)

    assert result["degraded"] is True
    assert result["suggestions"]


async def test_D10_降级建议引用stats中的真实数字(monkeypatch, sample_stats):
    """D10：降级建议的 evidence 只含 stats 里真实存在的数字"""
    monkeypatch.setattr(settings, "LLM_API_KEY", "")
    stub_stats(monkeypatch, sample_stats)

    result = await ai_svc.generate_report(None, DAYS)
    allowed = ai_svc._collect_allowed_numbers(sample_stats, DAYS)

    for item in result["suggestions"]:
        for field in ("finding", "evidence"):
            unverified = ai_svc._unverified_numbers(item[field], allowed)
            assert not unverified, f"{field} 含无据可依的数字 {unverified}: {item[field]}"


async def test_D11_两条路径都产出导出链接(monkeypatch, sample_stats, export_dir):
    """
    D11：降级路径与正常路径**都**产出导出链接（阶段 3 已落地）。

    路径是相对于 `/static` 挂载点的，前端用 resolveExportUrl() 还原成绝对地址。
    导出目录已被 conftest 的 autouse fixture 指到临时目录，不会污染仓库。
    """
    import re

    pattern = re.compile(r"^/static/exports/dashboard_\d{8}_\d{6}\.csv$")

    # 降级路径（未配 key，但 stats 取到了 → 有东西可导出）
    monkeypatch.setattr(settings, "LLM_API_KEY", "")
    stub_stats(monkeypatch, sample_stats)
    degraded_result = await ai_svc.generate_report(None, DAYS)
    assert degraded_result["degraded"] is True
    assert pattern.match(degraded_result["exportUrl"] or ""), \
        f"降级路径也应产出导出链接，实际 {degraded_result['exportUrl']!r}"

    # 正常路径（LLM 可用且通过业务边界校验）
    monkeypatch.setattr(settings, "LLM_API_KEY", "test-key")
    install_fake_llm(monkeypatch, fake_model(
        suggestions_text(("场地使用率 46.7%", "统计显示 46.7%", "建议动作"))
    ))
    normal_result = await ai_svc.generate_report(None, DAYS)
    assert normal_result["degraded"] is False
    assert pattern.match(normal_result["exportUrl"] or "")


async def test_D11补充_无stats时exportUrl为null(monkeypatch):
    """
    补 D11 的另一半：**数据库不可达时 exportUrl 仍为 null**。

    这条路径在取数失败处就 return 了，手里没有 stats —— 没有统计数字可导，
    强行生成只会得到一个「统计字段全空」的 CSV，比 null 更容易误导。
    所以 `degraded=true` 与 `exportUrl=null` 并非等价，两者要分开断言。
    """
    stub_stats_error(monkeypatch, RuntimeError)

    result = await ai_svc.generate_report(None, DAYS)

    assert result["degraded"] is True
    assert result["exportUrl"] is None


# ============================================================
# D12–D13：取数失败
# ============================================================
async def test_D12_取数失败不抛异常且降级(monkeypatch):
    """D12：取数函数抛 RuntimeError（模拟库不可达）→ 不抛异常、degraded=True、建议非空"""
    stub_stats_error(monkeypatch, RuntimeError)

    result = await ai_svc.generate_report(None, DAYS)

    assert result["degraded"] is True
    assert result["suggestions"]


async def test_D13_取数失败只陈述失败不编造数字(monkeypatch):
    """D13：evidence 引用真实异常类型，**不编造数字**"""
    stub_stats_error(monkeypatch, RuntimeError)

    result = await ai_svc.generate_report(None, DAYS)
    suggestion = result["suggestions"][0]

    assert "RuntimeError" in suggestion["evidence"]
    # 取数失败时不得出现任何统计数字（0% / 100% 也不行 —— 那和「真实统计」无法区分）
    assert not ai_svc._extract_numbers(suggestion["finding"])
    assert not ai_svc._extract_numbers(suggestion["evidence"])


# ============================================================
# D16–D17：未预期异常的兜底（`generate_report` 里那两个 catch-all）
# ============================================================
async def test_D16_首轮LLM抛未预期异常也走降级不抛出去(monkeypatch, sample_stats):
    """
    D16：`_invoke_llm` 抛出**未预期**的异常（既不是超时也不是 `_LLMUnavailable`）
    → 走降级、不向外抛。

    这是「本接口不抛 500」的最后一道防线：`_invoke_llm` 内部已把三层的失败
    收敛成 `_LLMUnavailable`，所以能漏到这个 catch-all 的只有真正意外的情况
    （编码错、依赖内部 bug 等）。故这里直接替换 `_invoke_llm` 来注入 ——
    用假模型是注入不进去的，模型抛的异常会被 `_invoke_llm` 内部吞掉转成 `_LLMUnavailable`。
    """
    async def _boom(*_args, **_kwargs):
        raise ValueError("模拟未预期异常：比如 SDK 内部状态错乱")

    monkeypatch.setattr(ai_svc, "_invoke_llm", _boom)
    stub_stats(monkeypatch, sample_stats)

    result = await ai_svc.generate_report(None, DAYS)

    assert result["degraded"] is True
    assert result["suggestions"], "兜底后仍要给出降级建议，不能是空数组"


async def test_D17_重试时抛异常也走降级不抛出去(monkeypatch, sample_stats):
    """
    D17：首轮全部编造触发重试，而**重试本身**抛异常 → 走降级、不向外抛。

    与 D16 是两条不同的兜底分支：D16 管第一次调用，这条管重试那一次
    （`HALLUCINATION_RETRY_ENABLED` 打开时才会走到）。
    """
    monkeypatch.setattr(ai_svc, "HALLUCINATION_RETRY_ENABLED", True)
    stub_stats(monkeypatch, sample_stats)

    calls = {"n": 0}

    async def _first_ok_then_boom(stats, days, extra_instruction=""):
        calls["n"] += 1
        if calls["n"] == 1:
            # 首轮：全部编造 → 触发重试
            return [{"finding": "场地使用率高达 85.3%", "evidence": "上升 12.4%", "suggestion": "扩容"}]
        raise ValueError("模拟重试时的未预期异常")

    monkeypatch.setattr(ai_svc, "_invoke_llm", _first_ok_then_boom)

    result = await ai_svc.generate_report(None, DAYS)

    assert calls["n"] == 2, "必须先真的重试过一次（否则这条用例跑的是 D16 的分支）"
    assert result["degraded"] is True
    assert result["suggestions"]
    assert "85.3" not in json.dumps(result, ensure_ascii=False), "编造内容不得漏出"


# ============================================================
# D14–D15：边界形态
# ============================================================
def test_D14_窗口内无数据只输出数据不足(empty_window_stats):
    """
    D14：peakHours 与 faultFrequency 均为空 → 只输出「数据不足」1 条。

    `spaceUsageRate=0 / deviceIdleRate=100` 是**看似具体**的数字，
    但「没有数据」和「资源闲置」是两回事，不得输出「严重闲置」这类业务结论。
    """
    items = ai_svc._degraded_suggestions(empty_window_stats, DAYS)

    assert len(items) == 1
    assert "没有已确认预约" in items[0]["finding"]

    combined = " ".join(items[0].values())
    assert "严重闲置" not in combined
    assert "闲置率 100" not in items[0]["finding"]


async def test_D15_分块content仍能解析(monkeypatch, sample_stats):
    """D15：假模型 content 为分块 list → 仍能提取文本并解析成功"""
    body = suggestions_text(("发现 46.7%", "依据 46.7%", "建议动作"))
    install_fake_llm(monkeypatch, fake_model(
        AIMessage(content=[{"type": "text", "text": body}])
    ))

    items = await ai_svc._invoke_llm(sample_stats, DAYS)

    assert len(items) == 1
