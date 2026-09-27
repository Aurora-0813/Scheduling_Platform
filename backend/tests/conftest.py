"""
测试公共夹具（摄像头空间感知模块）
====================================================================

规范依据 §10.2：
    「Agent 层测试使用假 LLM 夹具（FakeMessagesListChatModel 或自定义 Stub），
      保证离线可跑；真实 API 只做一次冒烟验证。」

本文件提供的夹具：
    fake_jpeg / fake_png      —— 构造合法图片字节（含正确魔数）
    make_upload_file          —— 把字节包装成 FastAPI 的 UploadFile
    fake_llm                  —— 按剧本回复的假模型（不支持结构化输出）
    structured_llm            —— 支持 with_structured_output 的假模型
    failing_llm               —— 一调用就抛异常的假模型（模拟超时/网络故障）
    temp_upload_dir           —— 把图片落盘目录重定向到临时目录，避免污染仓库

设计原则：
    **所有单元测试都不连数据库、不联网。**
    数据库查询通过 monkeypatch 替换成固定数据，模型调用通过假模型替换。
    真正的数据库联调放在接口级测试里，使用独立测试库 smart_scheduler_test。
"""
import io
import json
import struct
import zlib

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

# ===========================================================================
# 图片字节构造
# ===========================================================================


def build_png(width: int = 8, height: int = 8, rgb: tuple = (120, 160, 200)) -> bytes:
    """
    生成一张**真正合法**的 PNG 图片字节。

    参数：
        width  : int  宽（像素）
        height : int  高（像素）
        rgb    : tuple 填充色

    返回：
        bytes  可以直接被 Pillow / 浏览器正常打开的 PNG

    为什么不用现成的图片文件：
        测试资源尽量用代码生成，避免往仓库里塞二进制文件（§7.1 禁止无用文件），
        也让「图片尺寸」这类参数可以在测试里任意调整。

    结构说明：
        PNG = 8 字节签名 + 若干 chunk（IHDR / IDAT / IEND），
        每个 chunk = 长度(4B) + 类型(4B) + 数据 + CRC32(4B)
    """
    signature = b"\x89PNG\r\n\x1a\n"

    # IHDR：宽、高、位深 8、颜色类型 2（真彩色 RGB）、压缩/滤波/隔行均为 0
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

    # 每行数据前导一个字节的滤波类型（0 = None），随后是 width 个 RGB 像素
    raw_rows = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    idat = zlib.compress(raw_rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        """组装一个 PNG chunk，末尾附上 CRC32 校验码"""
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    return signature + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


@pytest.fixture
def fake_jpeg() -> bytes:
    """
    构造一段**魔数正确**的类 JPEG 字节。

    说明：
        这里不构造完整合法的 JPEG —— 因为本模块从头到尾**不解码图片**，
        只是把它 base64 后丢给大模型（测试里模型也是假的）。
        流水线真正校验的只有文件头魔数 FF D8 FF，所以带上正确的文件头即可。

        需要完整合法图片时请用 build_png()。
    """
    return b"\xff\xd8\xff\xe0" + b"\x00" * 512


@pytest.fixture
def fake_png() -> bytes:
    """一张真正合法的 PNG（8x8 像素），用于需要经得起解码的场景"""
    return build_png()


@pytest.fixture
def make_upload_file():
    """
    把裸字节包装成 FastAPI 的 UploadFile，供服务层直接调用。

    用法：
        file = make_upload_file(content=b"...", filename="site.jpg")
        data = await analyze_space_image(db=None, file=file, llm=fake_llm([...]))

    参数：
        content      : bytes | None  图片字节；None 表示用默认的假 JPEG
        filename     : str           文件名（测试路径穿越时传 "../../evil.jpg"）
        content_type : str           客户端声明的 MIME
    """

    def _make(
        content: bytes | None = None,
        filename: str = "site.jpg",
        content_type: str = "image/jpeg",
    ):
        from fastapi import UploadFile

        raw = content if content is not None else (b"\xff\xd8\xff\xe0" + b"\x00" * 512)
        return UploadFile(
            file=io.BytesIO(raw),
            filename=filename,
            # UploadFile 从 headers 里读 content-type，这里用最小的 headers dict 构造
            headers={"content-type": content_type},
        )

    return _make


# ===========================================================================
# 假模型
# ===========================================================================


@pytest.fixture
def fake_llm():
    """
    构造「按剧本回复」的假多模态模型。

    用法：
        llm = fake_llm(['{"spaceId": 101, "confidence": 0.92}'])
        data = await analyze_space_image(db=None, file=..., llm=llm)

    说明：
        FakeMessagesListChatModel 每次调用按顺序吐出一条预设回复，
        因此可以精确模拟「模型返回非 JSON」「返回 markdown 包裹」等各种剧本。

    ⚠️ 重要：这条路径实际走的是 image_service._recognize 的**策略 B**
        （普通 ainvoke + 手工 JSON 解析）。
        因为 FakeMessagesListChatModel 没有实现 bind_tools，
        调用 with_structured_output 会抛 NotImplementedError，
        被 _recognize 捕获后自动降级到策略 B。

        这恰好也验证了一个重要事实：**假模型天然无法覆盖策略 A**。
        策略 A 的行为由下面的 structured_llm 夹具单独覆盖。
    """

    def _make(responses: list) -> FakeMessagesListChatModel:
        return FakeMessagesListChatModel(
            responses=[
                AIMessage(content=r) if isinstance(r, str) else r for r in responses
            ]
        )

    return _make


@pytest.fixture
def structured_llm():
    """
    构造一个支持 with_structured_output 的假模型，用于覆盖**策略 A**。

    说明：
        刻意不继承 BaseChatModel —— 那样需要实现 _generate、
        还得让 bind_tools 真的产出符合协议的输出，成本远高于收益。
        这里用鸭子类型（duck typing）只实现被调用的两个方法，
        专注验证「_unpack_structured 拆包 + 策略 A 优先」这段逻辑。

    用法：
        llm = structured_llm({"spaceId": 101, "confidence": 0.92})
        llm = structured_llm(None, raw_text="我认不出这张图")   # 模拟解析失败但有原始文本
    """

    def _make(payload, raw_text: str = ""):
        class _StructuredStub:
            def with_structured_output(self, schema, include_raw: bool = False, **kwargs):
                class _Runner:
                    async def ainvoke(self, messages, **kwargs):
                        # 模拟 LangChain with_structured_output(include_raw=True) 的返回结构
                        raw = AIMessage(
                            content=raw_text or (
                                "" if payload is None else json.dumps(payload, ensure_ascii=False)
                            )
                        )
                        try:
                            parsed = schema.model_validate(payload) if payload is not None else None
                        except Exception as exc:
                            return {"raw": raw, "parsed": None, "parsing_error": exc}
                        return {"raw": raw, "parsed": parsed, "parsing_error": None}

                return _Runner()

        return _StructuredStub()

    return _make


@pytest.fixture
def failing_llm():
    """
    构造一调用就抛异常的假模型，用于模拟模型超时 / 网络故障。

    用法：
        monkeypatch.setattr(settings, "VISION_STRUCTURED_OUTPUT", False)
        with pytest.raises(ImageRecognitionError) as exc:
            await analyze_space_image(db=None, file=..., llm=failing_llm(TimeoutError()))
        assert exc.value.code == 41003

    说明：
        默认跳过结构化输出分支（VISION_STRUCTURED_OUTPUT=False），
        让异常直接从 ainvoke 抛出，精确命中「策略 B 失败」这条路径。
    """

    def _make(exc: Exception | None = None):
        class _FailingStub:
            async def ainvoke(self, messages, **kwargs):
                raise exc or TimeoutError("simulated model timeout")

            def with_structured_output(self, schema, **kwargs):
                # 让策略 A 也走同样的失败路径，保证异常最终被转成 41003
                return self

        return _FailingStub()

    return _make


# ===========================================================================
# 目录与环境
# ===========================================================================


@pytest.fixture
def temp_upload_dir(tmp_path, monkeypatch):
    """
    把图片落盘目录重定向到 pytest 的临时目录。

    用法：
        def test_save(temp_upload_dir, fake_png): ...

    说明：
        直接把 IMAGE_UPLOAD_DIR 设成**绝对路径**即可生效 ——
        settings.image_upload_path 内部是 `backend_dir / IMAGE_UPLOAD_DIR`，
        而 pathlib 在右侧为绝对路径时会直接采用右侧，不会做拼接。
        这样测试既不用改代码，也不会往仓库的 uploads/ 里写垃圾文件。
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "IMAGE_UPLOAD_DIR", str(tmp_path))
    return tmp_path
