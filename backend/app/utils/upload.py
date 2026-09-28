"""
上传文件校验（供模块 1 语音、模块 2 图像、模块 6 巡检照片复用）

关于 `UploadFile.size` 的兼容
-----------------------------
文档 3.6 锁定的是 `python-multipart==0.0.12`。`UploadFile.size` 属性是后续
版本（0.0.20 起经 starlette 暴露）才稳定可用的，在 0.0.12 上取不到。
本模块先尝试读 `.size`，取不到再回退为**流式计数**，两种环境都能工作，
不需要为了这个属性升级依赖。

关于「大小校验」的真实边界（重要，避免误判安全能力）
---------------------------------------------------
Starlette 在进入路由函数之前就已经把整个 multipart 请求体收完
（超过约 1MB 落临时文件）。所以本模块的校验是**业务规则**，
不是防大包攻击的手段。真正的入口级限制要靠：

- Nginx：`client_max_body_size 10m;`
- 或 ASGI 层的请求体大小中间件

部署时必须配置其一，见 docs/deploy.md。
"""

from __future__ import annotations

from typing import Any

from starlette.datastructures import UploadFile

from app.core.config import settings
from app.core.exceptions import UploadTooLargeError, UploadTypeInvalidError

__all__ = [
    "ALLOWED_IMAGE_TYPES",
    "ALLOWED_AUDIO_TYPES",
    "get_upload_size",
    "validate_upload_size",
    "validate_upload_type",
    "validate_image_upload",
    "validate_audio_upload",
]

# 图片：模块 2（现场拍照/草图）、模块 6（巡检拍照）
ALLOWED_IMAGE_TYPES: frozenset[str] = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/bmp",
    }
)

# 音频：模块 1（手机麦克风录音）
ALLOWED_AUDIO_TYPES: frozenset[str] = frozenset(
    {
        "audio/wav",
        "audio/x-wav",
        "audio/mpeg",
        "audio/mp4",
        "audio/webm",
        "audio/ogg",
        "audio/aac",
        "application/octet-stream",  # 部分小程序上传时不带准确 MIME
    }
)

_READ_CHUNK_SIZE = 1024 * 1024


async def get_upload_size(file: UploadFile) -> int:
    """
    取上传文件字节数。

    优先用 `.size`（新版本 python-multipart 提供）；取不到时按 1MB 分块读取
    计数，读完后把游标复位到起点，调用方后续仍可正常读取内容。
    """
    size = getattr(file, "size", None)
    if isinstance(size, int) and size >= 0:
        return size

    total = 0
    while True:
        chunk = await file.read(_READ_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
    await file.seek(0)
    return total


async def validate_upload_size(file: UploadFile, max_bytes: int | None = None) -> int:
    """
    校验大小，返回实际字节数。超限抛 `UploadTooLargeError`。

    `max_bytes` 缺省取配置项 `MAX_UPLOAD_SIZE_MB`（默认 10MB）。
    """
    limit = max_bytes if max_bytes is not None else settings.max_upload_size_bytes
    size = await get_upload_size(file)
    if size > limit:
        raise UploadTooLargeError(
            f"文件大小为 {size / 1024 / 1024:.1f}MB，超过上限 {limit / 1024 / 1024:.0f}MB"
        )
    if size == 0:
        raise UploadTypeInvalidError("上传文件内容为空")
    return size


def validate_upload_type(file: UploadFile, allowed: frozenset[str] | set[str]) -> str:
    """
    校验 MIME 类型，返回规范化后的类型字符串。

    注意：`content_type` 由客户端提供、可以被伪造，所以它是**格式校验**
    而非安全边界。真正需要防伪造的场景（如仅允许图片）还需解码文件头，
    见 docs/开发流程说明文档.md 的「文件上传安全」一节。
    """
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if not content_type:
        raise UploadTypeInvalidError("无法识别文件类型")
    if content_type not in allowed:
        raise UploadTypeInvalidError(
            f"不支持的文件类型：{content_type}，允许的类型为 {'、'.join(sorted(allowed))}"
        )
    return content_type


async def validate_image_upload(
    file: UploadFile,
    *,
    max_bytes: int | None = None,
    allowed: frozenset[str] | set[str] = ALLOWED_IMAGE_TYPES,
) -> str:
    """
    图片上传的完整校验（类型 + 大小），返回 MIME 类型。

    大小缺省取 `IMAGE_MAX_SIZE_MB`（5MB），**不是**通用的
    `MAX_UPLOAD_SIZE_MB`（10MB）：图片链路的另一处校验
    （`app/services/image_storage.py`）用的是前者，两处必须一致，
    否则同一张 8MB 的图会在这条链路被放行、在那条链路被拒。
    """
    content_type = validate_upload_type(file, allowed)
    limit = max_bytes if max_bytes is not None else settings.image_max_size_bytes
    await validate_upload_size(file, limit)
    return content_type


async def validate_audio_upload(
    file: UploadFile,
    *,
    max_bytes: int | None = None,
    allowed: frozenset[str] | set[str] = ALLOWED_AUDIO_TYPES,
) -> str:
    """
    音频上传的完整校验（类型 + 大小），返回 MIME 类型。

    大小缺省取通用的 `MAX_UPLOAD_SIZE_MB`（10MB）：录音是 16k 单声道，
    时长本身就比图片长；且语音链路的服务层不另做大小校验，
    不存在「两处判定不一致」的问题。
    """
    content_type = validate_upload_type(file, allowed)
    limit = max_bytes if max_bytes is not None else settings.max_upload_size_bytes
    await validate_upload_size(file, limit)
    return content_type


def safe_filename(filename: str | None, default: str = "upload") -> str:
    """
    取安全的文件名（去掉路径部分与非法字符）。

    用于落盘与日志，防止 `../../etc/passwd` 这类路径穿越。
    """
    if not filename:
        return default
    # 只取最后一段，再过滤掉路径分隔符与控制字符
    name: Any = filename.replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in str(name) if ch.isprintable() and ch not in '/\\:*?"<>|')
    name = name.strip().strip(".")
    return name or default
