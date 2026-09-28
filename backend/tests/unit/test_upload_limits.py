"""上传大小上限的取值归属（合并遗留项回归测试）。

背景
----
合并模块 1/2 时发现图片链路上有**两处**大小校验，却用了不同的配置项：

    app/services/image_storage.py  →  IMAGE_MAX_SIZE_MB       (5MB)
    app/utils/upload.py            →  MAX_UPLOAD_SIZE_MB      (10MB)  ← 错的一处

于是同一张 8MB 的图，走 image_storage 会被拒，走 validate_image_upload
会被放行。这类「同一个语义两处取值」的缺陷不会报错，只会在某条路径上
悄悄放宽校验，所以这里用测试把它钉死。

约定（见 app/core/config.py 的 image_max_size_bytes 属性）：
    图片链路（image_storage + validate_image_upload）→ IMAGE_MAX_SIZE_MB
    音频 / 模块 9/10 通用链路                        → MAX_UPLOAD_SIZE_MB
"""

import io

import pytest
from starlette.datastructures import UploadFile

from app.core.config import settings
from app.core.exceptions import UploadTooLargeError
from app.utils.upload import validate_audio_upload, validate_image_upload

_MB = 1024 * 1024


def _upload(size_bytes: int, content_type: str, filename: str) -> UploadFile:
    """造一个指定字节数的上传文件。

    不传 starlette 的 `size` 参数，让 app.utils.upload.get_upload_size()
    走流式计数分支 —— 顺带覆盖那条回退路径（python-multipart 0.0.12 上
    `UploadFile.size` 取不到，见该模块顶部说明）。
    """
    return UploadFile(
        file=io.BytesIO(b"\x00" * size_bytes),
        filename=filename,
        headers={"content-type": content_type},
    )


@pytest.fixture
def limits(monkeypatch):
    """把两个上限拉开距离，便于断言「用了哪一个」。"""
    monkeypatch.setattr(settings, "IMAGE_MAX_SIZE_MB", 1)
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 10)


async def test_image_upload_uses_image_limit_not_generic(limits):
    """图片校验必须用 IMAGE_MAX_SIZE_MB：2MB 的图在 1MB 上限下应被拒。

    修复前这里用的是 MAX_UPLOAD_SIZE_MB(10MB)，2MB 会被放行 —— 本用例即回归闸门。
    """
    file = _upload(2 * _MB, "image/jpeg", "big.jpg")

    with pytest.raises(UploadTooLargeError):
        await validate_image_upload(file)


async def test_image_upload_accepts_within_image_limit(limits):
    """小于 IMAGE_MAX_SIZE_MB 的图正常通过，返回 MIME 类型。"""
    file = _upload(_MB // 2, "image/png", "ok.png")

    assert await validate_image_upload(file) == "image/png"


async def test_image_upload_explicit_max_bytes_still_wins(limits):
    """显式传入的 max_bytes 优先于配置项（保持原有可覆盖语义）。"""
    file = _upload(2 * _MB, "image/jpeg", "big.jpg")

    await validate_image_upload(file, max_bytes=3 * _MB)  # 不抛即通过


async def test_audio_upload_keeps_generic_limit(limits):
    """音频仍走 MAX_UPLOAD_SIZE_MB：同样的 2MB 音频在 10MB 上限下应通过。

    防止「统一上限」被误做成「图片音频一起降到 5MB」。
    """
    file = _upload(2 * _MB, "audio/wav", "voice.wav")

    assert await validate_audio_upload(file) == "audio/wav"


async def test_audio_upload_rejects_beyond_generic_limit(limits):
    """音频超过 MAX_UPLOAD_SIZE_MB 仍要被拒。"""
    file = _upload(11 * _MB, "audio/wav", "too_long.wav")

    with pytest.raises(UploadTooLargeError):
        await validate_audio_upload(file)


async def test_empty_image_is_rejected(limits):
    """空文件按「类型非法」拒绝（沿用 validate_upload_size 的既有行为）。"""
    from app.core.exceptions import UploadTypeInvalidError

    file = _upload(0, "image/jpeg", "empty.jpg")

    with pytest.raises(UploadTypeInvalidError):
        await validate_image_upload(file)
