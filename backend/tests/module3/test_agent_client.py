"""Agent 客户端的真实 HTTP 分支与降级（§9.3 / §9.4）。

`agent_client` 的设计是「配了 AGENT_URL 就优先走真实服务，不可用则降级 mock」，
保证本模块能独立演示。这里把三条路径都钉住：成功透传、传输失败降级、HTTP 错误降级。
"""
from datetime import datetime, timedelta

import httpx

from app.services import agent_client


class FakeResponse:
    """httpx.Response 的最小替身。"""

    def __init__(self, payload: dict | None = None, status: int = 200):
        self._payload = payload if payload is not None else {}
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._payload


# ------------------------------------------------------------ _post_json


def test_post_json_parses_success(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse({"plan": {"spaceId": 1}}))
    assert agent_client._post_json("http://x/schedule", {}) == {"plan": {"spaceId": 1}}


def test_post_json_returns_none_on_transport_error(monkeypatch):
    """连不上 / 超时一律返回 None，由调用方降级（不向上抛）。"""

    def refuse(*a, **k):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", refuse)
    assert agent_client._post_json("http://x/schedule", {}) is None


def test_post_json_returns_none_on_http_error(monkeypatch):
    """HTTP 4xx/5xx 同样降级，不当成有效响应。"""
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse({}, status=500))
    assert agent_client._post_json("http://x/schedule", {}) is None


# ------------------------------------------------------------ schedule 分流


def test_real_agent_url_takes_priority(monkeypatch):
    """配了 AGENT_URL 且服务可用时，原样透传远端结果（不叠加本地 mock）。"""
    remote = {
        "plan": {"spaceId": 9, "spaceName": "远端展厅", "deviceIds": [3],
                 "startTime": "2026-09-26 14:00:00",
                 "endTime": "2026-09-26 15:00:00", "reason": "远端方案"},
        "backupPlan": {"spaceName": "远端备选"},
        "trace": [{"step": 1, "result": "远端 Agent 思考",
                   "timestamp": "2026-09-26 13:59:12"}],
        "needConfirm": True,
    }
    monkeypatch.setattr(agent_client, "AGENT_URL", "http://agent.test/")
    called: dict = {}

    def fake_post(url, json=None, timeout=None):
        called["url"], called["json"] = url, json
        return FakeResponse(remote)

    monkeypatch.setattr(httpx, "post", fake_post)

    assert agent_client.schedule("要个会议室") == remote
    # 尾部斜杠不应拼出双斜杠
    assert called["url"] == "http://agent.test/schedule"
    assert called["json"]["text"] == "要个会议室"


def test_real_agent_failure_degrades_to_mock(monkeypatch):
    """AGENT_URL 配了但服务挂了 → 降级 mock，演示不中断（§9.4）。"""
    monkeypatch.setattr(agent_client, "AGENT_URL", "http://agent.test")

    def refuse(*a, **k):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", refuse)

    out = agent_client.schedule("要个会议室", space_name="会议室A")
    assert out["plan"]["spaceName"] == "会议室A"
    assert out["needConfirm"] is True
    assert out["trace"][0]["result"].startswith("解析需求")
    # 冻结契约：trace 是对象数组，timestamp 互不相同且递增
    stamps = [s["timestamp"] for s in out["trace"]]
    assert stamps == sorted(stamps) and len(set(stamps)) == len(stamps)


def test_unset_agent_url_skips_http_entirely(monkeypatch):
    """未配 AGENT_URL 时不应发起任何 HTTP 调用（模块可离线独立运行）。"""

    def explode(*a, **k):
        raise AssertionError("未配 AGENT_URL 却发起了 HTTP 调用")

    monkeypatch.setattr(agent_client, "AGENT_URL", "")
    monkeypatch.setattr(httpx, "post", explode)

    assert agent_client.schedule("要个会议室")["plan"]["spaceName"].startswith("场地#")


# ------------------------------------------------------------ 时段挑选兜底


def test_next_free_picks_first_free_hour():
    """前两个小时被占，应顺延到第 3 个小时。"""
    base = datetime(2026, 9, 26, 9, 0, 0)
    occupied = [(base, base + timedelta(hours=2))]
    assert agent_client._next_free(base, occupied) == base + timedelta(hours=2)


def test_next_free_falls_back_when_all_busy():
    """连续 8 小时全被占用时兜底返回基准时间，不抛异常（§9.3 硬编码兜底）。"""
    base = datetime(2026, 9, 26, 9, 0, 0)
    occupied = [(base, base + timedelta(hours=8))]
    assert agent_client._next_free(base, occupied) == base
