"""语音输入模块 —— 接口层离线测试（模块 1）。

验证链路：路由注册 -> 鉴权闸门 -> 服务调用 -> 统一响应体。
不连库、不联网：服务函数用 monkeypatch 替换为固定返回。
"""

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import voice as voice_api
from app.main import app

client = TestClient(app)


@pytest.fixture
def fake_asr(monkeypatch):
    """替换语音识别服务为固定文本。"""

    async def _fake_speech_to_text(audio_bytes, audio_format="wav"):
        return "明天下午三点，我要订一个能坐40人的大会议室。"

    monkeypatch.setattr(voice_api, "speech_to_text", _fake_speech_to_text)


@pytest.fixture
def fake_format(monkeypatch):
    """替换口语格式化服务为固定结果。"""

    async def _fake_format_spoken_text(raw_text):
        return {
            "formattedText": "本周五（2026-09-25）下午，约四十人，需要一台投影仪。",
            "keywords": ["时间：2026-09-25 下午", "人数：约40", "设备：投影仪x1"],
        }

    monkeypatch.setattr(voice_api, "format_spoken_text", _fake_format_spoken_text)


def test_asr_success(fake_asr):
    resp = client.post(
        "/api/v1/voice/asr",
        files={"file": ("sample.wav", b"RIFFfakewavdata", "audio/wav")},
    )
    body = resp.json()
    assert body["code"] == 200
    assert body["data"]["text"] == "明天下午三点，我要订一个能坐40人的大会议室。"


def test_asr_empty_file():
    resp = client.post(
        "/api/v1/voice/asr",
        files={"file": ("empty.wav", b"", "audio/wav")},
    )
    body = resp.json()
    assert body["code"] == 400


def test_format_success(fake_format):
    resp = client.post(
        "/api/v1/voice/format",
        json={"rawText": "嗯……那个周五下午吧，大概四十来号人"},
    )
    body = resp.json()
    assert body["code"] == 200
    assert "投影仪" in body["data"]["formattedText"]
    assert len(body["data"]["keywords"]) == 3


def test_format_missing_field():
    # 缺少 rawText：HTTP 恒 200，业务码 400
    resp = client.post("/api/v1/voice/format", json={})
    body = resp.json()
    assert body["code"] == 400
