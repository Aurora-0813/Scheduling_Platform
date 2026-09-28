"""
图片存储服务（摄像头空间感知模块）
====================================================================

职责：
    1. 校验上传文件（大小 / MIME / 魔数），挡住垃圾与恶意输入
    2. 安全落盘（uuid 文件名 + 字符白名单清洗，杜绝路径穿越）
    3. 生成可访问 URL 与模型可读的 data URL

安全考虑（§9.2 数据安全）：
    - 绝不使用用户提供的原始文件名，防止 "../../etc/passwd" 式路径穿越
    - 文件名再过一遍字符白名单（防御纵深：即使 uuid 被污染也逃不出目录）
    - 限制大小，且**流式读取时即中断**，避免一次性读 100MB 把 2G 内存打爆
    - 校验文件魔数（magic bytes），防止把 .exe 改名成 .jpg 上传
    - 以「魔数探测结果」而非「客户端声明的 Content-Type」为准 —— 后者可伪造

性能考虑（§12.1：2核2G 的小机器）：
    - 读写文件用 aiofiles 异步 IO，不阻塞事件循环（§3.4 全异步要求）
"""

import base64
import logging
import re
import uuid
from datetime import datetime

import aiofiles
from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import BusinessError

logger = logging.getLogger("app.image_storage")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 支持的 MIME → 落盘扩展名
_MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

# 分块读取的块大小（64KB）。用固定大小分块而非一次性 read()，
# 是为了能在累计大小超限时立刻中断，不必先把整个文件读进内存。
_CHUNK_SIZE = 64 * 1024

# 文件名安全字符白名单：只允许字母、数字、下划线、短横线。
# 点号、斜杠、反斜杠、冒号等一律剔除 —— 它们都是路径穿越与隐藏文件的载体。
# 这是防御纵深：文件名本来就由服务端用 uuid 生成，正常不可能含危险字符，
# 但多一道清洗，代价近乎为零，收益是「即使上游被污染也绝对逃不出目录」。
_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9_-]")

# 错误码（与设计文档 §4.5 错误码表一致）
_CODE_UNSUPPORTED_TYPE = 41001
_CODE_FILE_TOO_LARGE = 41002


class ImageValidationError(BusinessError):
    """
    图片校验失败异常。

    继承 core.exceptions.BusinessError，因此**不需要**在路由层写 try/except ——
    core.exceptions 里注册的全局处理器会自动把它转成统一响应体。
    """


# ---------------------------------------------------------------------------
# 魔数探测
# ---------------------------------------------------------------------------


def _detect_mime(raw: bytes) -> str | None:
    """
    根据文件头魔数判断图片真实类型。

    参数：
        raw : bytes 文件开头的字节（至少前 12 字节）

    返回：
        "image/jpeg" / "image/png" / "image/webp"；无法识别返回 None

    说明：
        魔数是文件的「真实身份」。jpg 永远是 FF D8 FF 开头，png 永远是
        89 50 4E 47 0D 0A 1A 0A，webp 则是 RIFF????WEBP（第 8~12 字节固定为 WEBP）。
        攻击者把 .exe 改名成 .jpg 上传时，魔数对不上，会被这里拦下。
    """
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    # WEBP 需要同时满足：RIFF 开头 + 第 8~12 字节为 WEBP
    if len(raw) >= 12 and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


# ---------------------------------------------------------------------------
# 校验与读取
# ---------------------------------------------------------------------------


async def read_and_validate_image(file: UploadFile) -> tuple[bytes, str]:
    """
    读取并校验上传的图片。

    参数：
        file : UploadFile  FastAPI 注入的上传文件对象

    返回：
        (图片原始字节, 探测出的真实 MIME)，例如 (b"\\xff\\xd8...", "image/jpeg")

    抛出：
        ImageValidationError(41001) —— 类型不支持 / 魔数对不上 / 内容为空
        ImageValidationError(41002) —— 超过 IMAGE_MAX_SIZE_MB

    执行步骤：
        1. 用客户端声明的 Content-Type 做初筛（快速失败，省得白读文件）
        2. 分块读取并累计大小，一旦超限**立刻抛错**，不读完再判断
        3. 读完后用魔数探测真实类型，返回探测结果作为权威 MIME
    """
    # ---- 第 1 步：声明的 Content-Type 初筛 ----
    # 这个值可被客户端伪造，所以只用来「快速排除明显不对的」，不作为最终依据
    declared = (file.content_type or "").lower().split(";")[0].strip()
    if declared not in _MIME_TO_EXT:
        raise ImageValidationError(
            code=_CODE_UNSUPPORTED_TYPE,
            message="图片格式不支持，请上传 JPG / PNG / WEBP 格式的图片",
        )

    # ---- 第 2 步：分块读取 + 实时大小限制 ----
    max_bytes = settings.IMAGE_MAX_SIZE_MB * 1024 * 1024
    chunks: list[bytes] = []
    total = 0

    while True:
        chunk = await file.read(_CHUNK_SIZE)  # UploadFile.read 是异步的，不会阻塞事件循环
        if not chunk:
            break  # 读到文件末尾
        total += len(chunk)
        if total > max_bytes:
            # 关键：立刻中断，不再继续读 —— 恶意大文件打不垮内存
            raise ImageValidationError(
                code=_CODE_FILE_TOO_LARGE,
                message=f"图片过大，请压缩到 {settings.IMAGE_MAX_SIZE_MB}MB 以内再上传",
            )
        chunks.append(chunk)

    raw = b"".join(chunks)

    # ---- 第 3 步：内容非空校验 ----
    if not raw:
        raise ImageValidationError(
            code=_CODE_UNSUPPORTED_TYPE,
            message="上传的图片内容为空，请重新选择文件",
        )

    # ---- 第 4 步：魔数探测（权威类型判定）----
    detected = _detect_mime(raw)
    if detected is None:
        raise ImageValidationError(
            code=_CODE_UNSUPPORTED_TYPE,
            message="图片内容与格式不符，请重新上传 JPG / PNG / WEBP 图片",
        )

    # 声明类型与真实类型不一致时，以真实类型为准并记一条日志。
    # 之所以不直接拒绝：部分客户端会把 image/jpeg 写成 image/jpg 之类，
    # 既然魔数已经证明它确实是图片，就没必要为难用户。
    if detected != declared:
        logger.warning("图片 Content-Type 声明为 %s，实际魔数为 %s，以实际为准", declared, detected)

    return raw, detected


# ---------------------------------------------------------------------------
# 编码与落盘
# ---------------------------------------------------------------------------


def to_data_url(raw: bytes, mime: str) -> str:
    """
    把图片字节转成 data URL，供多模态模型读取。

    参数：
        raw  : bytes 图片原始字节
        mime : str   探测出的真实 MIME，如 "image/jpeg"

    返回：
        str，形如 "data:image/jpeg;base64,/9j/4AAQSkZJRg..."

    说明：
        之所以内联 base64 而不是传 URL —— 我们的 uploads 目录是内网地址，
        公有大模型 API 根本访问不到，必须把像素直接送过去。
    """
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _safe_stem(stem: str) -> str:
    """
    清洗文件名主体，只保留白名单字符。

    参数：
        stem : str  原始文件名主体（正常情况是 uuid4().hex）

    返回：
        清洗后的安全主体；若清洗后为空则重新生成一个 uuid

    示例：
        "9f3c1b2e..."      → "9f3c1b2e..."（不变）
        "..\\..\\evil"     → "evil"           （穿越符被剔除）
        "../../../"        → 重新生成的 uuid   （全被剔除后兜底）
    """
    safe = _UNSAFE_NAME_CHARS.sub("", stem or "")
    return safe or uuid.uuid4().hex


async def save_image(raw: bytes, mime: str) -> str | None:
    """
    把图片落盘，返回可访问 URL。

    参数：
        raw  : bytes 图片字节
        mime : str   探测出的真实 MIME

    返回：
        str  —— 成功，形如 "/uploads/20260924/9f3c....jpg"
        None —— 落盘失败（磁盘满 / 权限不足）

    为什么失败**不抛异常**：
        落盘只是为了演示回放与答辩溯源（设计决策 D6），属于附加价值。
        磁盘问题不应该让「识别」这个主功能跟着失败 ——
        调用方拿到 None 把 imageUrl 置空即可，前端流程完全不受影响。

    路径规则：
        {IMAGE_UPLOAD_DIR}/{YYYYMMDD}/{uuid4().hex}{ext}
        按日期分目录，避免单目录文件过多导致文件系统查找性能下降。
    """
    try:
        ext = _MIME_TO_EXT[mime]  # ".jpg" / ".png" / ".webp"，由服务端常量决定
        day = datetime.now().strftime("%Y%m%d")  # 按天分目录
        filename = f"{_safe_stem(uuid.uuid4().hex)}{ext}"  # 随机名 + 字符清洗 → 杜绝路径穿越与重名

        # settings.image_upload_path 已经是绝对路径，且会自动创建目录。
        # 用绝对路径而非 Path("uploads")，是为了保证从任何工作目录启动
        # （backend/、仓库根、IDE 默认目录）图片都落在同一个位置。
        target_dir = settings.image_upload_path / day
        target_dir.mkdir(parents=True, exist_ok=True)

        # 异步写盘，不阻塞事件循环（§3.4）
        async with aiofiles.open(target_dir / filename, "wb") as f:
            await f.write(raw)

        # 返回「对外前缀 + 相对路径」，由 main.py 挂载的 StaticFiles 提供访问
        return f"{settings.IMAGE_STORAGE_BASE_URL}/{day}/{filename}"

    except Exception:
        # 这里用宽泛的 Exception 是刻意的：磁盘/权限类异常五花八门，
        # 而本函数对它们的态度完全一致 —— 记录日志，返回 None，不影响主流程。
        logger.exception("图片落盘失败，已降级为不保存图片")
        return None
