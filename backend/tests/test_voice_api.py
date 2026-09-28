"""语音输入模块 —— 接口层离线测试（模块 1）。

验证链路：路由注册 -> 鉴权闸门 -> 服务调用 -> 统一响应体。
不连库、不联网：服务函数用 monkeypatch 替换为固定返回。
"""

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import voice as voice_api
from app.core.config import settings
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _auth_bypass(monkeypatch):
    """
    本文件只测业务链路，不测鉴权，因此统一免 Token。

    合并前它依赖开发者本地 .env 里写着 AUTH_BYPASS=true；那会让用例结果
    取决于机器上的私有配置（CI 上全变成 40101）。这里显式打开。
    鉴权本身的用例见 tests/test_image_api.py 与 tests/api/test_auth_api.py。
    """
    monkeypatch.setattr(settings, "AUTH_BYPASS", True)


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
    # 空音频是路由层主动判定的「参数不合法」，用全局段 40001。
    # 原先的裸码 400 与全局分段约定不一致，已随合并遗留项一并修正。
    assert body["code"] == 40001


def test_asr_failure_returns_41004(monkeypatch):
    """ASR 调用失败 → 41004 ASR_FAILED（不是 41002）。

    回归闸门：合并遗留项里，这条路径曾借用 41002，而 41002 在
    error_codes.py 中的语义是 IMAGE_TOO_LARGE（图片过大）——
    前端据此会提示「请压缩图片」，与语音场景完全对不上。
    """

    async def _boom(audio_bytes, audio_format="wav"):
        raise RuntimeError("baidu sdk 鉴权失败: api_key=sk-should-not-leak")

    monkeypatch.setattr(voice_api, "speech_to_text", _boom)

    resp = client.post(
        "/api/v1/voice/asr",
        files={"file": ("sample.wav", b"RIFFfakewavdata", "audio/wav")},
    )
    body = resp.json()

    assert body["code"] == 41004
    assert body["code"] != 41002  # 不得再与「图片过大」撞码
    # 异常细节只进日志：百度 SDK 的报错可能带密钥片段，不能进响应体
    assert "sk-should-not-leak" not in resp.text


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
    # 缺少 rawText 属于请求体校验失败，由全局处理器统一成
    # HTTP 400 + 业务码 40001（PARAM_INVALID），明细在 data.errors。
    # 注意与上面 test_asr_empty_file 的区别：那条是路由层主动
    # `fail(code=40001)`，属于业务判定，不经参数校验；
    # 因此它同样返回 40001，但 HTTP 状态仍是 200（见文件末尾说明）。
    resp = client.post("/api/v1/voice/format", json={})
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 40001


# ===========================================================================
# 一个尚未统一的约定：模块 1 的失败响应，HTTP 状态码仍是 200
# ===========================================================================
# 本文件的 test_asr_empty_file 只断言 body["code"]，没有断言 resp.status_code，
# 是因为模块 1 的路由层用 `return fail(...)`（core/response.py 的兼容层）返回
# dict，FastAPI 按默认 200 输出 —— 业务码ok、HTTP 状态码不 ok。
#
# 而模块 2 的失败走 `raise BusinessError(...)`，由全局异常处理器接管，
# 会返回真实状态码（如 41001 → HTTP 400）。
#
# 于是同一个后端里存在两种失败风格：
#     POST /api/v1/image/analyze  失败 → HTTP 400 + code 41001
#     POST /api/v1/voice/asr      失败 → HTTP 200 + code 40001
#
# 这属于合并说明文档 §7.1-1「HTTP 状态码约定」的待拍板项：
# 集成组已决定采用「真实状态码」（§3.2），但兼容层为了让模块 1/2 的既有代码
# 零改动可用，保留了 fail() 返回 dict 的行为，因此尚未收敛。
#
# 若后续决定统一为真实状态码，改动点在 core/response.py 的 fail() 调用方式
# （改为抛异常或返回带状态的 Response），本文件的断言需随之补上 status_code。
