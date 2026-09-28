"""
测试公共夹具（模块 2 摄像头空间感知 · 模块 4 核心调度 Agent）
====================================================================

规范依据 §10.2：
    「Agent 层测试使用假 LLM 夹具（FakeMessagesListChatModel 或自定义 Stub），
      保证离线可跑；真实 API 只做一次冒烟验证。」

本文件提供的夹具：

    模块 2 摄像头空间感知
        fake_jpeg / fake_png      —— 构造合法图片字节（含正确魔数）
        make_upload_file          —— 把字节包装成 FastAPI 的 UploadFile
        fake_llm                  —— 按剧本回复的假模型（**不支持** bind_tools）
        structured_llm            —— 支持 with_structured_output 的假模型
        failing_llm               —— 一调用就抛异常的假模型（模拟超时/网络故障）
        temp_upload_dir           —— 把图片落盘目录重定向到临时目录，避免污染仓库

    模块 4 核心调度 Agent
        agent_fake_llm            —— 实现 bind_tools 的 StubChatModel，供 create_agent 用
        db_session                —— 测试库会话（连 smart_scheduler_test，用例后回滚）

⚠️ 两个假 LLM 夹具的名字必须区分开，它们的契约正好相反：

    fake_llm        故意**不**支持 bind_tools。image_service 据此走「策略 B 降级」
                    分支（普通 ainvoke + 手工 JSON 解析），换成支持 bind_tools 的
                    模型会让 test_image_service 里那批用例失去意义。

    agent_fake_llm  必须支持 bind_tools。create_agent 组装时会调
                    model.bind_tools(tools)，而实测 langchain-core 1.6.4 下
                    FakeMessagesListChatModel 与 GenericFakeChatModel 都没实现它，
                    直接抛 NotImplementedError。验证脚本见 tests/smoke_fake_llm.py。

设计原则：
    **所有单元测试都不连数据库、不联网。**
    数据库查询通过 monkeypatch 替换成固定数据，模型调用通过假模型替换。
    真正的数据库联调放在接口级测试里，使用独立测试库 smart_scheduler_test
    （只有 db_session 这一个夹具会真的连库，且用例结束后回滚）。

    模块 7 冲突预警与通知
        now / rule_config                 —— 固定时间基准与规则阈值配置
        spaces / devices / users          —— 规则引擎快照（纯内存对象，不碰库）
        make_order / make_context         —— 订单快照与规则上下文的构造器
        fake_llm_json / fake_llm_prose / fake_llm_broken
                                          —— 分别返回合法 JSON / 自然语言 / 破损 JSON，
                                             对应通知链三级降级的前两级与兜底
        slow_llm / raising_llm / empty_llm / multimodal_llm
                                          —— 覆盖超时 / 异常 / 空响应 / 分段 content 四个降级分支
"""
from __future__ import annotations

import io
import json
import struct
import zlib
from datetime import datetime, timedelta

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from app.services.rules.base import (
    ConflictRuleConfig,
    DeviceView,
    OrderView,
    RuleContext,
    SpaceView,
    UserView,
)

# 固定时间基准，让所有规则测试可复现
NOW = datetime(2026, 9, 25, 10, 0)


# ===========================================================================
# 图片字节构造（模块 2）
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
# 假模型（模块 2 摄像头空间感知）
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

        （模块 4 的 Agent 侧需要的是「支持 bind_tools」的假模型，
          那是 agent_fake_llm，不要和这个混用。）
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
# 目录与环境（模块 2）
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


# ===========================================================================
# 假模型（模块 4 核心调度 Agent）
# ===========================================================================


class StubChatModel(BaseChatModel):
    """
    自实现 bind_tools 的假聊天模型，供 create_agent 组装使用。

    为什么不用现成的 FakeMessagesListChatModel / GenericFakeChatModel：
        create_agent 组装时会调 model.bind_tools(tools)，
        而实测 langchain-core 1.6.4 下这两个现成夹具都没有实现 bind_tools，
        直接抛 NotImplementedError，后面所有用例都会变成「假绿」。
        冒烟验证见 tests/smoke_fake_llm.py。

    用法：
        StubChatModel(responses=[tool_call_message, AIMessage(content="已找到方案")])
    """

    responses: list[AIMessage] = []
    _cursor: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "stub-chat-model"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003 - 对齐父类签名
        """create_agent 必需。基类默认实现直接抛 NotImplementedError。"""
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        # 每次调用往下走一条剧本；越界后停在最后一条（便于观察是否被重复调用）
        idx = min(self._cursor, len(self.responses) - 1)
        self._cursor += 1
        return ChatResult(generations=[ChatGeneration(message=self.responses[idx])])


@pytest.fixture
def agent_fake_llm():
    """
    构造供 create_agent 使用的假模型（**支持** bind_tools）。

    用法：
        model = agent_fake_llm([tool_call_msg, AIMessage(content="已找到方案")])
        agent = create_agent(model, tools=[query_spaces], system_prompt="你是调度助手")

    参数：
        responses : list  按顺序返回的消息；传 str 会自动包成 AIMessage

    说明：
        典型剧本是「第一条带 tool_calls，第二条给最终答复」，
        对应 create_agent 的「调工具 → 再总结」两轮。
        需要覆盖模型直接给答复、不调工具的场景时，只传一条即可。
    """

    def _make(responses: list) -> StubChatModel:
        return StubChatModel(
            responses=[
                AIMessage(content=r) if isinstance(r, str) else r for r in responses
            ]
        )

    return _make


# ===========================================================================
# 数据库（模块 4 核心调度 Agent）
# ===========================================================================

TEST_DB_NAME = "smart_scheduler_test"


@pytest.fixture
async def db_session():
    """
    测试库会话夹具：连测试库，用例结束后回滚，不留痕。

    做法：
        1. 把 settings.database_url 里的库名换成 TEST_DB_NAME；
        2. 单开一个 poolclass=NullPool 的引擎（用完即断，不跨用例复用连接）；
        3. 在外层事务里开 Session，并设 join_transaction_mode="create_savepoint" ——
           用例里 session.commit() 只是打一个 SAVEPOINT，不会真的提交；
        4. 用例结束后回滚外层事务，所有写入一并消失。

    为什么不用项目里的 async_engine：
        那个引擎连的是开发库 smart_scheduler_dev，且绑定关系在模块导入时就固化了。
        测试必须连独立测试库，否则一次 commit 就把开发库写脏了。

    用法：
        async def test_create_reservation(db_session):
            db_session.add(Reservation(...))
            await db_session.commit()   # 只是 SAVEPOINT，不会落到真实库里
            ...

    前置条件：
        测试库 smart_scheduler_test 已存在且表结构已建好（见 docs/database.md），
        且 SSH 隧道已起。连不上时这里直接 skip 而不是 fail ——
        让纯离线用例照常跑，不被环境问题拖累。
    """
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import settings

    url = settings.database_url.replace(f"/{settings.DB_NAME}", f"/{TEST_DB_NAME}")
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        try:
            conn = await engine.connect()
        except (SQLAlchemyError, OSError) as exc:
            pytest.skip(f"连不上测试库 {TEST_DB_NAME}（多半是 SSH 隧道没起）：{exc}")

        try:
            trans = await conn.begin()
            try:
                session = AsyncSession(
                    bind=conn,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                )
                try:
                    yield session
                finally:
                    await session.close()
            finally:
                await trans.rollback()
        finally:
            await conn.close()
    finally:
        await engine.dispose()


# ===========================================================================
# 模块 7 冲突预警与通知（feat 侧夹具，原样保留）
# ===========================================================================


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def rule_config() -> ConflictRuleConfig:
    """固定阈值，让测试不依赖 .env"""
    return ConflictRuleConfig()


@pytest.fixture
def spaces() -> dict[int, SpaceView]:
    return {
        1: SpaceView(id=1, space_name="A栋301会议室", space_type=1, capacity=20),
        2: SpaceView(id=2, space_name="A栋3楼展厅", space_type=2, capacity=40),
        3: SpaceView(id=3, space_name="B栋多功能厅", space_type=3, capacity=80),
    }


@pytest.fixture
def devices() -> dict[int, DeviceView]:
    return {
        1: DeviceView(id=1, device_name="投影仪-1", device_type="投影仪"),
        2: DeviceView(id=2, device_name="无人机-1", device_type="无人机"),
        3: DeviceView(id=3, device_name="音响-1", device_type="音响"),
    }


@pytest.fixture
def users() -> dict[int, UserView]:
    return {
        1: UserView(id=1, username="张三", role_id=1, role_name="普通使用者"),
        2: UserView(id=2, username="李管理", role_id=2, role_name="资源管理员"),
    }


@pytest.fixture
def make_order(now):
    """订单快照构造器，未指定的字段走合理默认值"""

    def _make(
        order_id: int = 1,
        *,
        user_id: int = 1,
        space_id: int = 1,
        start: datetime | None = None,
        end: datetime | None = None,
        status: int = 2,
        device_ids: tuple[int, ...] = (),
        agent_request: str | None = None,
        attendee_count: int | None = None,
    ) -> OrderView:
        start_time = start if start is not None else now + timedelta(hours=2)
        end_time = end if end is not None else start_time + timedelta(hours=1)
        return OrderView(
            id=order_id,
            user_id=user_id,
            space_id=space_id,
            start_time=start_time,
            end_time=end_time,
            order_status=status,
            device_ids=device_ids,
            agent_request=agent_request,
            attendee_count=attendee_count,
        )

    return _make


@pytest.fixture
def make_context(spaces, devices, users, rule_config, now):
    """规则上下文构造器"""

    def _make(
        orders: tuple[OrderView, ...] | list[OrderView] = (),
        *,
        space_last_order_at: dict[int, datetime] | None = None,
        config: ConflictRuleConfig | None = None,
        current: datetime | None = None,
    ) -> RuleContext:
        return RuleContext(
            orders=tuple(orders),
            spaces=spaces,
            devices=devices,
            users=users,
            now=current if current is not None else now,
            config=config if config is not None else rule_config,
            space_last_order_at=space_last_order_at or {},
        )

    return _make


# ---------- 假 LLM 夹具 ----------


@pytest.fixture
def fake_llm_json():
    """返回合法 JSON 的假模型 → 应命中第一级（ai_json）"""
    from app.agent.chains.llm import build_fake_llm

    return build_fake_llm(
        ['{"title": "【预约提醒】A栋3楼展厅 14:00", "content": "AI 生成的正文内容。"}']
    )


@pytest.fixture
def fake_llm_prose():
    """返回自然语言散文的假模型 → 应命中第二级（ai_text）"""
    from app.agent.chains.llm import build_fake_llm

    return build_fake_llm(
        ["您好，您预约的场地即将开始使用，请提前十分钟到场完成布置工作，如需调整请联系资源管理员。"]
    )


@pytest.fixture
def fake_llm_broken():
    """返回破损 JSON 的假模型 → 应命中第三级（template）"""
    from app.agent.chains.llm import build_fake_llm

    return build_fake_llm(['{"title": "缺引号的正文", content: }'])


@pytest.fixture
def slow_llm():
    """
    调用会阻塞的假模型。

    配合极小的 timeout 参数，可真实走通 asyncio.wait_for 超时分支
    （而不是把超时逻辑 mock 掉），这是覆盖降级代码的关键。

    注意 FakeMessagesListChatModel 只实现了同步的 _generate（内部 time.sleep），
    异步调用走 BaseChatModel._agenerate 的默认实现 —— 把 _generate 丢进线程池。
    因此 wait_for 取消的是等待方，超时分支照常触发，但后台线程会继续睡完。
    sleep 取 0.6s 而非数秒，避免拖慢每次用例的收尾。
    """
    from app.agent.chains.llm import build_fake_llm

    return build_fake_llm(['{"title": "太慢", "content": "这条不该被用上。"}'], sleep=0.6)


@pytest.fixture
def raising_llm():
    """
    调用即抛异常的假模型 → 覆盖「外部 API 失败」降级分支。

    必须覆盖 _generate 而不是 _call：BaseChatModel 上并不存在 _call，
    覆盖它只是死代码，异常永远不会抛出。
    """
    from langchain_core.language_models.fake_chat_models import (
        FakeMessagesListChatModel,
    )
    from langchain_core.messages import AIMessage

    from app.agent.chains.llm import FAKE_NOTIFY_JSON

    class RaisingChatModel(FakeMessagesListChatModel):
        """继承假模型，让底层生成直接抛错"""

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
            raise RuntimeError("模拟外部 API 调用失败")

    return RaisingChatModel(responses=[AIMessage(content=FAKE_NOTIFY_JSON)] * 3)


@pytest.fixture
def empty_llm():
    """返回空内容的假模型 → 覆盖「空响应」降级分支"""
    from app.agent.chains.llm import build_fake_llm

    return build_fake_llm(["   "])


@pytest.fixture
def multimodal_llm():
    """
    返回分段 content 的假模型。

    langchain-openai 1.x 会把 content 返回成 [{"type": "text", ...}] 列表，
    直接 .strip() 会 AttributeError —— 这个夹具专门盯住那处回归。
    """
    from langchain_core.language_models.fake_chat_models import (
        FakeMessagesListChatModel,
    )
    from langchain_core.messages import AIMessage

    blocks = [
        {"type": "text", "text": '{"title": "分段标题", '},
        {"type": "text", "text": '"content": "分段正文内容。"}'},
    ]
    return FakeMessagesListChatModel(responses=[AIMessage(content=blocks)] * 3)
