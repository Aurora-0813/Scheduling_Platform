"""语音输入模块 —— API 路由层（模块 1）。

职责（§7.3：路由层、服务层、数据层分离）：
    路由层只做三件事：参数注入、调用服务、包装统一响应体。

接口：
    POST /api/v1/voice/asr     录音上传 -> 语音转文字
    POST /api/v1/voice/format  口语文本清洗 + 关键词提取

说明：
    两个接口都挂 get_current_user 鉴权闸门（与模块 2 一致）；
    AUTH_BYPASS=true 时可跳过 Token 直接调测。
"""

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.deps import CurrentUser, get_current_user
from app.core.error_codes import ErrorCode
from app.core.logging import get_logger
from app.core.response import ApiResponse, fail, success
from app.schemas.voice import AsrResult, FormatRequest, FormatResult
from app.services.asr_service import SUPPORTED_FORMATS, speech_to_text
from app.services.format_service import format_spoken_text

logger = get_logger(__name__)

# 合并说明：本行原为 prefix="/api/v1/voice"，原因同 app/api/v1/image.py，
# 对齐项目约定后改为相对前缀 "/voice"。
router = APIRouter(prefix="/voice", tags=["语音输入（模块 1）"])


@router.post(
    "/asr",
    response_model=ApiResponse[AsrResult],
    summary="语音转文字",
    response_description="返回识别出的文本",
)
async def asr(
    file: UploadFile = File(..., description="音频文件（wav/pcm/amr/m4a，16k 单声道）"),
    current_user: CurrentUser = Depends(get_current_user),
):
    """小程序上传录音 -> 百度 ASR -> 返回文字。"""
    audio = await file.read()
    if not audio:
        # 空文件属于「参数不合法」，用全局段 40001（PARAM_INVALID），
        # 不再用裸码 400 —— 裸码与全局分段约定不一致，前端拿不到可查的码表。
        return fail(code=ErrorCode.PARAM_INVALID, message="音频文件为空")

    ext = (file.filename or "wav").rsplit(".", 1)[-1].lower()
    audio_format = ext if ext in SUPPORTED_FORMATS else "wav"

    try:
        text = await speech_to_text(audio, audio_format=audio_format)
        return success(data={"text": text})
    except Exception:
        # 用 41004 ASR_FAILED，而非 41002（那是 IMAGE_TOO_LARGE）：
        # 借用图片过大的码会让前端提示「请压缩图片」，与语音场景完全对不上。
        #
        # 异常细节只进日志，不进响应体：百度 SDK 的报错里可能带上
        # API Key / Secret Key 片段或内部 URL（exceptions.py 顶部约定）。
        logger.exception("语音识别失败: %s", file.filename)
        return fail(code=ErrorCode.ASR_FAILED)


@router.post(
    "/format",
    response_model=ApiResponse[FormatResult],
    summary="口语格式化与关键词提取",
    response_description="返回书面语与关键词",
)
async def format_text(
    req: FormatRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """口语文本 -> DeepSeek 清洗 -> 书面语 + 关键词（失败自动降级原文）。"""
    data = await format_spoken_text(req.rawText)
    return success(data=data)
