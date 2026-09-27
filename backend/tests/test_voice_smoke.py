"""语音模块 真实接口冒烟测试（模块 1）。

默认跳过（会真实消耗百度/DeepSeek 额度），需要时显式运行：
    cd backend
    pytest -m smoke tests/test_voice_smoke.py
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.smoke

client = TestClient(app)
SAMPLE = Path(__file__).parent / "sample.wav"


def test_asr_smoke():
    with open(SAMPLE, "rb") as f:
        resp = client.post(
            "/api/v1/voice/asr",
            files={"file": ("sample.wav", f, "audio/wav")},
        )
    body = resp.json()
    assert body["code"] == 200
    assert body["data"]["text"]


def test_format_smoke():
    resp = client.post(
        "/api/v1/voice/format",
        json={"rawText": "嗯……那个周五下午吧，大概四十来号人，还要个投影仪对吧"},
    )
    body = resp.json()
    assert body["code"] == 200
    assert body["data"]["formattedText"]
