"""阿里云百炼 · Qwen3-ASR-Flash 语音识别（模块 1 语音输入）。

流程：音频字节 -> base64 内联进 data URL -> 百炼**原生**端点 -> 取识别文本。

⚠️ **2026-09-30 从「百度短语音识别标准版」整体替换而来。**
旧实现要先用 API Key/Secret 换 access_token（带 30 天缓存与过期处理）再发
base64 音频；现在直接用 API Key，且**复用 Agent/看板在用的同一个百炼账号**
（`settings.ASR_API_KEY or settings.LLM_API_KEY`），因此不需要任何新凭据。

端点为什么单独配而不是拼 `LLM_BASE_URL`：
`LLM_BASE_URL` 是 OpenAI **兼容模式**的 base（`/compatible-mode/v1`），
而 ASR 走的是原生路径 `/api/v1/services/aigc/multimodal-generation/generation`。
实测把 `/audio/transcriptions` 挂在兼容模式 base 上返回 **404**（该路径不存在），
所以两者不能混用。换模型只需改 `settings.ASR_MODEL_NAME`。

对外签名与旧版**完全一致**（`speech_to_text(audio_bytes, audio_format) -> str`），
所以 `api/v1/voice.py` 一行都不用改：它仍然只负责调用与把异常翻成 41004。
"""

import base64

import httpx

from app.core.config import settings

#: 扩展名 -> data URL 的 MIME。键集合即「本模块接受哪些格式」。
#:
#: ⚠️ 其中 **只有 wav 是端到端实测过的**（小程序录音就是 16k 单声道 wav，
#: 用 TTS 合成再识别往返成功）。其余几项按百炼文档列出，未逐个验证 ——
#: 若线上报「格式不支持」，先确认这一项，不要先去怀疑录音参数。
_FORMAT_TO_MIME: dict[str, str] = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "amr": "audio/amr",
    "pcm": "audio/pcm",
}

#: 保留旧名字：`api/v1/voice.py` 用它把上传文件的扩展名规整成受支持的值。
SUPPORTED_FORMATS = set(_FORMAT_TO_MIME)

#: 识别请求超时。60 秒音频的 base64 约 2.6MB，给足上传与推理时间。
_TIMEOUT_SECONDS = 60.0


def _api_key() -> str:
    """ASR 专用 Key，未单独配置时回退到 `LLM_API_KEY`（同一个百炼账号）。"""
    return settings.ASR_API_KEY or settings.LLM_API_KEY


def _extract_text(payload: dict) -> str:
    """从百炼原生响应里取识别文本。

    响应结构（实测）::

        {"output": {"choices": [{"message": {"content": [{"text": "识别出的文字"}]}}]}}

    ⚠️ `content` 是一个**列表**，而且**可能是空列表** —— 喂纯音乐/静音时
    实测返回 `[]`（HTTP 200、`audio_tokens` 正常计数）。这不是失败，是
    「这段音频里没有人说话」，所以这里返回空串而不是抛异常，由调用方决定提示语。
    """
    try:
        content = payload["output"]["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"语音识别返回结构异常：{str(payload)[:200]}") from exc

    if isinstance(content, str):
        # 兼容少数返回纯字符串的形态，避免上游一改就崩
        return content.strip()
    if isinstance(content, list):
        parts = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("text")
        ]
        return "".join(parts).strip()
    return ""


async def speech_to_text(audio_bytes: bytes, audio_format: str = "wav") -> str:
    """把音频识别成文字。

    Args:
        audio_bytes: 音频二进制内容
        audio_format: wav / mp3 / m4a / amr / pcm（小程序录音为 wav，16k 单声道）

    Returns:
        识别出的文本；**音频里没有人声时返回空串**（不是异常）。

    Raises:
        RuntimeError: 网络失败、鉴权失败、模型不存在、返回结构异常。
            调用方（`api/v1/voice.py`）会把它翻成 `41004 ASR_FAILED`。
    """
    if not audio_bytes:
        raise RuntimeError("音频内容为空")

    fmt = audio_format if audio_format in _FORMAT_TO_MIME else "wav"
    data_url = f"data:{_FORMAT_TO_MIME[fmt]};base64,{base64.b64encode(audio_bytes).decode()}"

    body = {
        "model": settings.ASR_MODEL_NAME,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [{"audio": data_url}],
                }
            ]
        },
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                settings.ASR_API_BASE,
                headers={
                    "Authorization": f"Bearer {_api_key()}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"语音识别请求失败：{type(exc).__name__}: {exc}") from exc

    if resp.status_code != 200:
        # 百炼的错误体形如 {"code":"InvalidParameter","message":"Model not exist."}
        raise RuntimeError(f"语音识别失败（HTTP {resp.status_code}）：{resp.text[:300]}")

    try:
        payload = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"语音识别返回非 JSON：{resp.text[:200]}") from exc

    return _extract_text(payload)
