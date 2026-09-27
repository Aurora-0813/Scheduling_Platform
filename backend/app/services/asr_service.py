"""百度智能云 · 短语音识别标准版 服务（模块 1 语音输入）。

流程：API Key/Secret 换 access_token（带缓存） -> 音频 base64 编码后发给识别接口。
接口文档：百度智能云「语音识别_短语音识别标准版」。
"""

import base64
import time
import uuid

import httpx

from app.core.config import settings

TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
ASR_URL = "https://vop.baidu.com/server_api"

# 百度短语音识别标准版支持的格式（mp3 不支持，实测返回 param format invalid）
SUPPORTED_FORMATS = {"pcm", "wav", "amr", "m4a"}

# token 内存缓存（有效期约 30 天，提前 5 分钟视为过期）
_token_cache: dict = {"token": "", "expire_at": 0.0}


async def get_access_token() -> str:
    """用 API Key / Secret Key 换取 access_token，带缓存。"""
    if _token_cache["token"] and time.time() < _token_cache["expire_at"]:
        return _token_cache["token"]

    params = {
        "grant_type": "client_credentials",
        "client_id": settings.BAIDU_API_KEY,
        "client_secret": settings.BAIDU_SECRET_KEY,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(TOKEN_URL, params=params)
        data = resp.json()

    if "access_token" not in data:
        raise RuntimeError(f"百度 token 获取失败：{data}")

    _token_cache["token"] = data["access_token"]
    _token_cache["expire_at"] = time.time() + int(data.get("expires_in", 2592000)) - 300
    return _token_cache["token"]


async def speech_to_text(audio_bytes: bytes, audio_format: str = "wav") -> str:
    """把音频识别成文字。

    Args:
        audio_bytes: 音频二进制内容
        audio_format: pcm / wav / amr / m4a（小程序录音为 wav，16k 单声道）
    """
    if audio_format not in SUPPORTED_FORMATS:
        audio_format = "wav"

    token = await get_access_token()
    payload = {
        "format": audio_format,
        "rate": settings.ASR_RATE,
        "channel": 1,
        "cuid": f"voice-{uuid.uuid4().hex[:16]}",
        "dev_pid": settings.ASR_MODEL_PID,
        "token": token,
        "speech": base64.b64encode(audio_bytes).decode("utf-8"),
        "len": len(audio_bytes),
    }

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(ASR_URL, json=payload)
        data = resp.json()

    err_no = data.get("err_no", -1)
    if err_no != 0:
        raise RuntimeError(f"语音识别失败（err_no={err_no}）：{data.get('err_msg')}")

    result = data.get("result", [])
    return result[0] if result else ""
