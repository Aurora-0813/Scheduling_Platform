"""
多模态大模型客户端（摄像头空间感知模块）
====================================================================

职责：
    1. 集中构造「视觉理解」用的 ChatOpenAI 实例（走 OpenAI 兼容协议）
    2. 模型名 / 端点 / 密钥全部从 .env 读取（§3.5 规范），切换供应商零代码改动
    3. 以 FastAPI 依赖的形式暴露，便于测试时用假模型整体替换（§10.2 规范）

为什么单独抽一个文件：
    - 若将来其它模块（如模块 6 AI 智能巡检）也要用视觉模型，
      直接复用 get_vision_llm() 即可，避免每个模块各建一套客户端
    - 单例复用 httpx 连接池，2核2G 的 ECS 上能省下反复握手的开销

规范依据：
    §3.3  FastAPI 端点必须 async def，调用 ainvoke() / astream()，禁止同步 invoke()
    §3.5  模型名称与 API 版本在 .env 中集中配置
    §9.3  Agent 只能通过 Tool 调用 services/ 层访问业务数据（本模块不含 Tool，直接调用）
    本项目明确不引入向量库 / RAG，模型调用为「单轮多模态推理」，无检索环节。
"""
import logging

from functools import lru_cache

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.core.exceptions import BusinessError

logger = logging.getLogger(__name__)

# 模型配置缺失时的错误码（与 §4.5 错误码表保持一致：属于「识别服务不可用」）
_CODE_MODEL_UNAVAILABLE = 41003


@lru_cache(maxsize=1)
def get_vision_llm() -> BaseChatModel:
    """
    构造并缓存全局唯一的视觉多模态模型实例。

    返回：
        BaseChatModel：支持 image_url 内容块的多模态对话模型，
                       通过 await llm.ainvoke(messages) 异步调用

    抛出：
        BusinessError(41003) —— .env 里没配 VISION_MODEL_NAME / VISION_API_KEY
                                 或缺少对应的 Python 依赖包

    使用 lru_cache 做单例的原因：
        ChatOpenAI 内部维护 httpx 连接池，每次请求都 new 一个实例会
        反复建连 / 断连，在低配云服务器上是明显的性能浪费。

    ⚠️ 关于 timeout 参数：
        部分 langchain-openai 版本里该参数名为 request_timeout，
        若启动时报 TypeError: unexpected keyword argument 'timeout'，
        把下面这行改成 request_timeout=settings.LLM_TIMEOUT 即可，语义完全一致。
    """
    # ---- 前置检查：配置缺失时给出人话提示，而不是让底层抛一个看不懂的 KeyError ----
    if not settings.VISION_MODEL_NAME or not settings.VISION_API_KEY:
        raise BusinessError(
            code=_CODE_MODEL_UNAVAILABLE,
            message=(
                "视觉识别模型未配置，请在 backend/.env 中填写 "
                "VISION_MODEL_NAME 与 VISION_API_KEY 后重启服务"
            ),
        )

    try:
        return ChatOpenAI(
            model=settings.VISION_MODEL_NAME,  # 如 qwen-vl-max，从 .env 读
            api_key=settings.VISION_API_KEY,  # 密钥，从 .env 读，绝不硬编码（§9.2）
            base_url=settings.VISION_API_BASE,  # OpenAI 兼容端点
            temperature=0.1,  # 感知任务要「确定性」，温度压到最低，减少模型发挥
            timeout=settings.LLM_TIMEOUT,  # 单次调用超时（秒）
            max_retries=settings.LLM_MAX_RETRIES,  # SDK 自动重试；仍失败由 service 层降级
        )
    except ImportError as exc:
        # 依赖没装全（如缺 langchain-openai）时给一句能照做的提示
        raise BusinessError(
            code=_CODE_MODEL_UNAVAILABLE,
            message="视觉识别依赖缺失，请执行 pip install -r requirements.txt 后重试",
        ) from exc


def reset_vision_llm_cache() -> None:
    """
    清空 get_vision_llm 的缓存。

    使用场景：
        1. 单元测试里改完配置后需要重新构造客户端
        2. 将来若支持「运行时热切换模型」，切换后调用本函数让新配置生效
    """
    get_vision_llm.cache_clear()


# ===========================================================================
# 文本 LLM（模块 7）—— 通知生成 / 信息抽取
# 与上文 get_vision_llm 并列：视觉与文本是两条独立链路，各有各的模型配置。
# 注意：主干另有 services/format_service.py 的 DEEPSEEK_* 文本链路，
#       与本段的 LLM_* 是【同类不同路】，本次不动它（见勘误 E18）。
# ===========================================================================
# 假 LLM 的默认响应：一条合法的通知文案 JSON
FAKE_NOTIFY_JSON = (
    '{"title": "【预约提醒】您的预约即将开始", '
    '"content": "您好，您在 A栋3楼展厅 的预约即将开始，请提前 10 分钟到场布置。'
    '如需调整，请在预约记录中发起变更。"}'
)


def build_fake_llm(
    responses: list[str] | None = None,
    *,
    sleep: float | None = None,
) -> BaseChatModel:
    """
    假 LLM 夹具。文档 10.2 要求「Agent 层测试使用假 LLM 夹具，保证离线可跑」。

    :param responses: 依次返回的内容，缺省为一条合法通知 JSON
    :param sleep: 每次调用阻塞的秒数，用于测试超时降级分支
    """
    from langchain_core.language_models.fake_chat_models import (
        FakeMessagesListChatModel,
    )
    from langchain_core.messages import AIMessage

    payloads = responses or [FAKE_NOTIFY_JSON]
    # 多备几份，避免夹具在连续多次调用时耗尽响应
    return FakeMessagesListChatModel(
        responses=[AIMessage(content=text) for text in payloads] * 3,
        sleep=sleep,
    )


def build_llm(*, temperature: float = 0.4, timeout: float | None = None) -> BaseChatModel:
    """
    构造文本大模型客户端（模块 7 的通知生成 / 信息抽取）。

    AI_ENABLED=False 或 AI_USE_FAKE_LLM=True 时返回假 LLM，
    调用方（notify_chain）会因 AI_ENABLED 判断直接走模板，不会真的调用它。
    """
    if settings.AI_USE_FAKE_LLM or not settings.AI_ENABLED:
        logger.info(
            "使用假 LLM 夹具（AI_ENABLED=%s, AI_USE_FAKE_LLM=%s）",
            settings.AI_ENABLED,
            settings.AI_USE_FAKE_LLM,
        )
        return build_fake_llm()

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.LLM_MODEL_NAME,
        # 未配置 Key 时给个占位值，让构造成功、调用失败，
        # 从而落到统一的降级链路，而不是在构造期抛出难懂的异常
        api_key=settings.LLM_API_KEY or "NOT_CONFIGURED",
        base_url=settings.LLM_BASE_URL,
        timeout=timeout or settings.LLM_TIMEOUT,     # ← C2 并名后的结果
        max_retries=1,
        temperature=temperature,
    )
