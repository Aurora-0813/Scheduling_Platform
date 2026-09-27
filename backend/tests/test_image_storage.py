"""
图片存储服务单元测试（摄像头空间感知模块）
====================================================================

覆盖设计文档 §9.1 用例清单中的 T11–T14：
    T11 图片类型非法 → 41001
    T12 图片超限     → 41002（且不读完整个文件）
    T13 伪造 content_type 被魔数拦下 → 41001
    T14 文件名含 ../ 不会逃出上传目录

所有用例均不访问网络、不连数据库，可直接离线运行。
"""
import pytest

from app.core.config import settings
from app.services import image_storage
from app.services.image_storage import (
    ImageValidationError,
    _detect_mime,
    read_and_validate_image,
    save_image,
    to_data_url,
)

# ===========================================================================
# 魔数探测
# ===========================================================================


def test_detect_mime_jpeg(fake_jpeg):
    """T13 前置：JPEG 魔数 FF D8 FF 能被正确识别"""
    assert _detect_mime(fake_jpeg) == "image/jpeg"


def test_detect_mime_png(fake_png):
    """PNG 魔数 89 50 4E 47 0D 0A 1A 0A 能被正确识别"""
    assert _detect_mime(fake_png) == "image/png"


def test_detect_mime_webp():
    """WEBP 需要 RIFF 开头且第 8~12 字节为 WEBP"""
    valid = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 16
    assert _detect_mime(valid) == "image/webp"


def test_detect_mime_webp_false_positive():
    """RIFF 开头但不是 WEBP（如 WAV/AVI）不能被误判成图片"""
    not_webp = b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"\x00" * 16
    assert _detect_mime(not_webp) is None


def test_detect_mime_rejects_executable():
    """Windows PE 可执行文件头（MZ）应被拒绝"""
    assert _detect_mime(b"MZ\x90\x00" + b"\x00" * 64) is None


# ===========================================================================
# read_and_validate_image
# ===========================================================================


async def test_validate_rejects_unsupported_content_type(make_upload_file):
    """T11：声明类型不在白名单内 → 41001，且在读文件之前就快速失败"""
    file = make_upload_file(content=b"whatever", content_type="application/pdf")

    with pytest.raises(ImageValidationError) as exc:
        await read_and_validate_image(file)

    assert exc.value.code == 41001


async def test_validate_rejects_disguised_file(make_upload_file):
    """T13：声明 image/jpeg，实际内容是文本 → 魔数校验拦下，41001"""
    file = make_upload_file(content=b"this is definitely not an image")

    with pytest.raises(ImageValidationError) as exc:
        await read_and_validate_image(file)

    assert exc.value.code == 41001


async def test_validate_rejects_empty_file(make_upload_file):
    """空文件 → 41001"""
    file = make_upload_file(content=b"")

    with pytest.raises(ImageValidationError) as exc:
        await read_and_validate_image(file)

    assert exc.value.code == 41001


async def test_validate_rejects_oversize(monkeypatch, make_upload_file):
    """T12：超过 IMAGE_MAX_SIZE_MB → 41002"""
    # 把上限压到 1MB，构造 1.5MB 的内容
    monkeypatch.setattr(settings, "IMAGE_MAX_SIZE_MB", 1)
    oversize = b"\xff\xd8\xff\xe0" + b"\x00" * (1536 * 1024)

    with pytest.raises(ImageValidationError) as exc:
        await read_and_validate_image(make_upload_file(content=oversize))

    assert exc.value.code == 41002


async def test_validate_trusts_detected_mime_over_declared(make_upload_file):
    """
    声明类型与真实内容不符时，以**魔数探测结果**为准。

    场景：客户端把 JPEG 声明成 image/png。既然魔数已证明它确实是图片，
    就没必要为难用户 —— 但后续落盘扩展名与 data URL 必须用真实类型，
    否则模型可能因为 mime 与内容不匹配而解析失败。
    """
    file = make_upload_file(
        content=b"\xff\xd8\xff\xe0" + b"\x00" * 64,
        content_type="image/png",
    )

    _raw, mime = await read_and_validate_image(file)

    assert mime == "image/jpeg"


# ===========================================================================
# to_data_url
# ===========================================================================


def test_to_data_url_format(fake_png):
    """data URL 必须是 'data:<mime>;base64,<...>' 结构"""
    url = to_data_url(fake_png, "image/png")

    assert url.startswith("data:image/png;base64,")
    # base64 段必须能解回原始字节
    import base64

    assert base64.b64decode(url.split(",", 1)[1]) == fake_png


# ===========================================================================
# save_image
# ===========================================================================


async def test_save_image_writes_file(temp_upload_dir, fake_png):
    """落盘成功：返回可访问 URL，且文件确实存在"""
    url = await save_image(fake_png, "image/png")

    assert url is not None
    assert url.startswith(f"{settings.IMAGE_STORAGE_BASE_URL}/")
    assert url.endswith(".png")

    # URL 去掉对外前缀后，应能在上传目录里找到对应文件
    relative = url[len(settings.IMAGE_STORAGE_BASE_URL) + 1:]
    saved = temp_upload_dir / relative
    assert saved.exists()
    assert saved.read_bytes() == fake_png


async def test_save_image_prevents_path_traversal(temp_upload_dir, fake_png, monkeypatch):
    """
    T14：即使文件名主体被污染成穿越路径，落盘位置仍必须在上传目录之内。

    说明：
        save_image 压根不接受调用方提供的文件名（它只接收字节与 MIME），
        文件名由服务端 uuid 生成 —— 路径穿越在**设计上就不可能发生**。
        本用例强制让 uuid 返回一段带 "../../" 的字符串，验证 _safe_stem
        的字符白名单能把危险字符彻底剔除，形成防御纵深。
    """

    class _EvilUuid:
        # 正常 uuid4().hex 只含十六进制字符，这里刻意返回一段穿越路径
        hex = "..\\..\\evil"

    monkeypatch.setattr(image_storage.uuid, "uuid4", lambda: _EvilUuid())

    url = await save_image(fake_png, "image/png")

    # 1) 返回的 URL 里不允许出现任何穿越片段
    assert url is not None
    assert ".." not in url
    assert "\\" not in url
    assert url.endswith("/evil.png")          # 穿越符被剔除，只剩安全主体

    # 2) 文件确实落在临时上传目录内，没有跑到它的上级去
    relative = url[len(settings.IMAGE_STORAGE_BASE_URL) + 1:]
    saved = (temp_upload_dir / relative).resolve()
    assert saved.is_relative_to(temp_upload_dir.resolve())
    assert saved.exists()


async def test_save_image_degrades_on_failure(temp_upload_dir, fake_png, monkeypatch):
    """
    落盘失败（磁盘满 / 权限不足）时必须降级为返回 None，**绝不抛异常**。

    这是设计决策 D6 的核心：图片保存只是附加价值，
    不能因为它失败就让整个识别请求挂掉。
    """

    def _boom(*args, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr(image_storage.aiofiles, "open", _boom)

    assert await save_image(fake_png, "image/png") is None
