"""
摄像头空间感知 —— 核心业务服务
====================================================================

本文件是整个模块的大脑，编排完整链路：

    校验图片 → 落盘 → 查候选场地 → 调模型 → 容错解析 → 业务边界校验 → 组响应

规范依据：
    §7.3  业务逻辑放 services/ 目录
    §4.3  所有数据写入必须经过业务服务层校验（本模块**只读不写**）
    §9.3  大模型输出必须做业务边界校验，防止 AI 幻觉
    §10.2 必须覆盖两类降级：非 JSON 降级、外部 API 失败降级
    §13   风险表：大模型幻觉 / API 超时 / JSON 格式错乱

关键设计（详见设计文档 §3）：
    D1  不使用 create_agent，采用「单轮多模态调用」——
        感知任务没有工具可调、没有多步推理，用 Agent 只会拖慢并破坏 JSON 契约。
    D2  模型只做候选匹配，后端用数据库权威数据覆盖 —— 防幻觉的核心。
    D4  三级降级，任何一环挂掉都不返回 500。
    【本项目明确不引入向量库 / RAG】候选场地是 space_resource 小表的全量查询，
    不存在 embedding、检索或召回环节。
"""

import json
import logging
import re
from datetime import date, datetime, time, timedelta
from typing import TypeVar

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompts.image_prompt import (
    build_sketch_analyze_messages,
    build_space_analyze_messages,
)
from app.core.config import settings
from app.core.exceptions import BusinessError
from app.models.reservation import ReserveOrder
from app.models.resource import SpaceResource
from app.schemas.image import (
    AvailableSlot,
    DeviceHint,
    SketchAnalyzeData,
    SketchRecognition,
    SpaceAnalyzeData,
    SpaceCandidate,
    SpaceRecognition,
)
from app.services.image_storage import (
    read_and_validate_image,
    save_image,
    to_data_url,
)

logger = logging.getLogger("app.image_service")

# 泛型参数：识别结果模型的类型（SpaceRecognition / SketchRecognition）
RecognitionT = TypeVar("RecognitionT", bound=BaseModel)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 订单状态：1待确认 2已确认 3已取消 4已完成（§6.3 第 6 张表）
# 「待确认」与「已确认」都会占用场地时段；已取消、已完成不占用。
_ORDER_ACTIVE_STATUS = (1, 2)

# 兜底追问文案模板（模型没给 question 时使用）
_FALLBACK_SPACE_QUESTION = "识别到可能是 {name}，置信度 {pct}%，是否正确？"
_FALLBACK_SPACE_QUESTION_NO_MATCH = (
    "没能识别出这是哪个场地，可以从下面的列表里选一个，或者改用文字描述需求。"
)
_FALLBACK_SKETCH_QUESTION = "草图解读置信度较低（{pct}%），能否补充一句场地用途或大概人数？"

# 解析彻底失败时的引导语（§10.2 要求的降级提示）
_SPACE_PARSE_FAILED_HINT = (
    "照片识别没能完成，可以重拍一张更清晰的照片（对准门牌或场地全景），"
    "或者直接改用文字描述你的需求。"
)
_SKETCH_PARSE_FAILED_HINT = "草图没能读懂，可以画得更清楚一些，或者直接用文字描述场地要求。"

# 错误码
_CODE_RECOGNITION_FAILED = 41003


class ImageRecognitionError(BusinessError):
    """
    图像识别失败（模型超时 / 网络错误 / 服务不可用）。

    继承 BusinessError，因此由 core.exceptions 的全局处理器自动转成统一响应体，
    路由层不需要为它写任何 try/except。
    """


# ===========================================================================
# 对外入口 1：现场拍照识别空间
# ===========================================================================


async def analyze_space_image(
    db: AsyncSession,
    file,
    llm: BaseChatModel,
) -> SpaceAnalyzeData:
    """
    现场拍照 → 识别空间 → 返回带置信度与追问判定结果。

    参数：
        db   : AsyncSession   数据库会话（由 get_db 依赖注入）
        file : UploadFile     FastAPI 上传文件对象
        llm  : BaseChatModel  多模态模型（由 get_vision_llm 依赖注入；
                              测试时可用假模型整体替换，见 tests/conftest.py）

    返回：
        SpaceAnalyzeData  完整识别结果

    抛出：
        ImageValidationError  图片不合法（41001 / 41002）
        ImageRecognitionError 模型调用失败（41003）

    执行流程（对应设计文档 §3 的 D2 / D4）：
        ┌─ ① 校验图片             失败 → 41001 / 41002
        ├─ ② 落盘（失败不阻断）
        ├─ ③ 查候选场地（数据库权威数据）
        ├─ ④ 调多模态模型          失败 / 超时 → 41003
        ├─ ⑤ 容错解析              失败 → 降级：自然语言引导
        ├─ ⑥ 业务边界校验          幻觉 → 丢弃 spaceId
        └─ ⑦ 组装响应（含追问判定）
    """
    # ---- ① 校验图片（格式 / 大小 / 魔数）----
    # 校验失败会抛 ImageValidationError，由全局异常处理器转成 41001 / 41002
    raw, mime = await read_and_validate_image(file)

    # ---- ② 落盘，拿可访问 URL（失败不阻断，见 D6）----
    image_url = await save_image(raw, mime)

    # ---- ③ 查询候选场地：数据库才是唯一事实来源（D2）----
    candidates = await list_active_space_candidates(db)

    # ---- ④ 调用多模态模型 ----
    data_url = to_data_url(raw, mime)
    messages = build_space_analyze_messages(
        image_data_url=data_url,
        candidates=[c.model_dump() for c in candidates],
        threshold=settings.IMAGE_CONFIDENCE_THRESHOLD,
    )
    parsed, _raw_reply = await _recognize(llm, messages, SpaceRecognition)

    # ---- ⑤ 解析彻底失败 → 第 1 级降级：不报错，返回自然语言引导（§10.2）----
    if parsed is None:
        logger.info("空间识别解析失败，已降级为自然语言引导")
        return SpaceAnalyzeData(
            spaceId=None,
            spaceName=None,
            confidence=0.0,
            needConfirm=True,
            question=_SPACE_PARSE_FAILED_HINT,
            rawText=None,
            candidates=candidates,  # 给候选，让用户可以直接手动选
            availableTime=[],
            devices=[],
            imageUrl=image_url,
        )

    # ---- ⑥ 业务边界校验：模型说了不算，数据库说了算（D2 的核心）----
    matched = _match_candidate(parsed, candidates)

    # 6.1 置信度归一化与校准
    confidence = _clamp01(parsed.confidence)
    if matched is None:
        # 场地都没匹配上，模型自评的 0.99 毫无意义 —— 必须归零，
        # 否则前端会显示「99% 置信度但没识别出场地」这种自相矛盾的结果
        confidence = 0.0
    elif confidence == 0.0 and parsed.spaceId is not None:
        # 模型确实选了场地却忘了给置信度：给一个保守值，逼出人工确认
        confidence = 0.5

    # 6.2 追问判定：两条触发条件取「或」
    #     a) 没匹配到任何场地
    #     b) 置信度低于阈值
    need_confirm = (matched is None) or (confidence < settings.IMAGE_CONFIDENCE_THRESHOLD)

    # 6.3 追问文案：优先用模型生成的（§4.4：AI 主动生成追问文案），
    #     模型漏填时用后端模板兜底
    question = None
    if need_confirm:
        question = (parsed.question or "").strip() or _make_space_question(matched, confidence)

    # ---- ⑦ 组装响应 ----
    # 场地的权威信息一律取自数据库，不采用模型输出（模型可能把「展厅」写成「展览厅」）
    available_time: list[AvailableSlot] = []
    if matched is not None and settings.IMAGE_ENABLE_AVAILABLE_SLOTS:
        available_time = await _safe_list_available_slots(db, matched.spaceId)

    return SpaceAnalyzeData(
        spaceId=matched.spaceId if matched else None,
        spaceName=matched.spaceName if matched else None,  # ← 数据库值，不是模型值
        confidence=confidence,
        needConfirm=need_confirm,
        question=question,
        rawText=parsed.rawText,
        # 只在需要用户确认时才回传候选列表，命中时可以省掉这部分载荷
        candidates=candidates if need_confirm else [],
        availableTime=available_time,
        devices=_to_device_hints(parsed.deviceHints),
        imageUrl=image_url,
    )


# ===========================================================================
# 对外入口 2：手绘草图识别
# ===========================================================================


async def analyze_sketch_image(
    db: AsyncSession,
    file,
    llm: BaseChatModel,
) -> SketchAnalyzeData:
    """
    手绘草图 → 解读布局与需求 → 返回带置信度的结果。

    参数 / 抛出：同 analyze_space_image

    与空间识别的差异：
        - 不需要查候选场地（草图解读的是「需求」，没有对应的真实场地）
        - 不做数据库记录校验，只做**数值合法性**校验（如人数不能是 -5）
        - db 参数保留是为了接口形态统一与将来扩展，当前实现未使用
    """
    # ---- ① 校验图片 ----
    raw, mime = await read_and_validate_image(file)

    # ---- ② 落盘 ----
    image_url = await save_image(raw, mime)

    # ---- ③ 调模型 ----
    data_url = to_data_url(raw, mime)
    messages = build_sketch_analyze_messages(
        image_data_url=data_url,
        threshold=settings.IMAGE_CONFIDENCE_THRESHOLD,
    )
    parsed, _raw_reply = await _recognize(llm, messages, SketchRecognition)

    # ---- ④ 解析失败 → 降级（§10.2）----
    if parsed is None:
        logger.info("草图识别解析失败，已降级为自然语言引导")
        return SketchAnalyzeData(
            capacity=None,
            layout=None,
            requirements=[],
            confidence=0.0,
            needConfirm=True,
            question=_SKETCH_PARSE_FAILED_HINT,
            imageUrl=image_url,
        )

    # ---- ⑤ 数值合法性校验（§9.3：大模型输出必须做业务边界校验）----
    # 模型偶尔会给出 -5 或 999999 这种离谱值 —— 视为无效置空，而不是直接报错，
    # 用户只关心「这个数能不能用」，报错反而会打断流程。
    capacity = parsed.capacity
    if capacity is not None and not (1 <= capacity <= 10000):
        logger.info("草图识别人数 %s 超出合理范围，已置空", capacity)
        capacity = None

    # requirements 清洗：去空白、丢非字符串、去重、限长、限制条数。
    # 不加限制的话，模型可能吐出 200 条关键词，把响应体和前端 UI 都撑坏。
    requirements = _clean_str_list(parsed.requirements, max_items=10, max_len=64)

    # layout 描述限长，防止异常输出撑爆字段
    layout = (parsed.layout or "").strip()[:512] or None

    # ---- ⑥ 语义空结果判定 ----
    # 模型可能返回一个「结构合法但内容全空」的对象（例如 {} ，或所有字段都是 null）。
    # 这种结果对用户毫无价值；若它还带着高 confidence 就更糟 ——
    # 前端会显示一个「90% 置信度但什么都没识别出来」的自相矛盾结果。
    # 因此只要三个核心字段全空，就按「没读懂」处理，走降级分支。
    # （这一步在 schema 层做不了：Pydantic 只管字段类型，管不了「内容是否有意义」）
    if capacity is None and layout is None and not requirements:
        logger.info(
            "草图识别结果语义为空（capacity / layout / requirements 均无内容），按解析失败处理"
        )
        return SketchAnalyzeData(
            capacity=None,
            layout=None,
            requirements=[],
            confidence=0.0,  # 模型自评的置信度在此情境下没有意义，归零
            needConfirm=True,
            question=_SKETCH_PARSE_FAILED_HINT,
            imageUrl=image_url,
        )

    confidence = _clamp01(parsed.confidence)
    need_confirm = confidence < settings.IMAGE_CONFIDENCE_THRESHOLD

    question = None
    if need_confirm:
        question = (parsed.question or "").strip() or _FALLBACK_SKETCH_QUESTION.format(
            pct=int(round(confidence * 100))
        )

    return SketchAnalyzeData(
        capacity=capacity,
        layout=layout,
        requirements=requirements,
        confidence=confidence,
        needConfirm=need_confirm,
        question=question,
        imageUrl=image_url,
    )


# ===========================================================================
# 模型调用：双策略
# ===========================================================================


async def _recognize(
    llm: BaseChatModel,
    messages: list,
    schema: type[RecognitionT],
) -> tuple[RecognitionT | None, str]:
    """
    「调用模型 → 拿结构化结果」的统一入口，内置两条策略。

    策略 A（首选，LangChain 地道写法）：
        llm.with_structured_output(schema, include_raw=True)
        底层仍是**一次** ainvoke —— 它把 Pydantic schema 翻译成 JSON Schema /
        function-calling 协议交给模型，再把返回结果解析成 Pydantic 对象。
        好处：格式由协议层保证，无需手工解析；include_raw 还能同时拿到原始文本。

    策略 B（兜底）：
        普通 ainvoke + 手工 JSON 容错解析。
        用于模型不支持 tool calling / json_schema 的情况（部分视觉模型如此），
        或配置里显式关闭了策略 A 时。

    参数：
        llm      : BaseChatModel                 模型实例
        messages : list                          由 prompt 构造函数生成的消息列表
        schema   : type[BaseModel]               目标识别结果模型

    返回：
        (parsed_or_None, raw_text)
        parsed 为 None 表示「没能得到合法结构」，调用方需走降级分支
        raw_text 是模型返回的原始文本，便于排查与展示

    抛出：
        ImageRecognitionError(41003) —— 模型侧彻底不可用（超时 / 网络 / 服务端错误）
    """
    raw_text = ""

    # ------------------------------------------------------------------
    # 策略 A：with_structured_output
    # ------------------------------------------------------------------
    if settings.VISION_STRUCTURED_OUTPUT:
        try:
            structured = llm.with_structured_output(schema, include_raw=True)
            result = await structured.ainvoke(messages)
            parsed, raw_text = _unpack_structured(result)

            if parsed is not None:
                return parsed, raw_text

            # parsed 为 None 但拿到了原始文本：尝试从中抢救出 JSON。
            # 例如模型没走 function calling，而是把 JSON 写在了正文里。
            salvaged = _validate_json_text(raw_text, schema)
            if salvaged is not None:
                return salvaged, raw_text

            # 抢救也失败：把原始文本交回上层做降级展示。
            # 这里刻意**不再发第二次请求** —— 同样的 Prompt 再问一遍大概率还是同样的结果，
            # 白白多花一次调用的钱和延迟。
            return None, raw_text
        except Exception:
            # 走到这里通常是「该模型/供应商不支持结构化输出」，
            # 例如 BaseChatModel 默认的 bind_tools 抛 NotImplementedError。
            # 静默降级到策略 B 重试一次；若 B 也失败，异常会在下面被转成 41003。
            logger.info("结构化输出不可用，降级到手工解析策略", exc_info=True)

    # ------------------------------------------------------------------
    # 策略 B：普通调用 + 手工 JSON 容错解析
    # ------------------------------------------------------------------
    try:
        resp = await llm.ainvoke(messages)
    except Exception as exc:
        # 这里是「最后一道网」：任何模型侧异常都转成业务异常，
        # 由全局异常处理器统一输出 41003，绝不让 500 裸奔到前端（§13 风险应对）
        logger.exception("调用多模态模型失败")
        raise ImageRecognitionError(
            code=_CODE_RECOGNITION_FAILED,
            message="图像识别服务暂时不可用，请重试或改用文字描述需求",
        ) from exc

    raw_text = _normalize_message_text(resp.content)
    parsed = _validate_json_text(raw_text, schema)
    return parsed, raw_text


def _unpack_structured(result) -> tuple[BaseModel | None, str]:
    """
    拆解 with_structured_output(include_raw=True) 的返回值。

    参数：
        result : 通常是 dict，形如
                 {"raw": AIMessage, "parsed": 模型对象或 None, "parsing_error": 异常或 None}
                 少数实现可能直接返回模型对象，这里一并兼容。

    返回：
        (parsed_or_None, raw_text)

    说明：
        include_raw=True 是本模块降级设计的关键：
        即使结构化解析失败，我们仍然拿得到模型的原始文本，
        可以把它当作降级提示的一部分，而不是「什么都没拿到」。
    """
    if isinstance(result, dict):
        parsed = result.get("parsed")
        raw_msg = result.get("raw")
        raw_text = _normalize_message_text(getattr(raw_msg, "content", "")) if raw_msg else ""
        return parsed, raw_text
    # 非 dict：直接当成解析好的对象
    return result, ""


def _normalize_message_text(content) -> str:
    """
    把模型返回的 content 归一化成纯字符串。

    背景：
        多数 OpenAI 兼容服务返回的 content 是字符串，
        但部分服务（或启用多模态输出时）会返回**内容块列表**，
        形如 [{"type": "text", "text": "..."}]。
        不处理的话，后面的 json.loads 收到 list 会直接 TypeError。

    参数：
        content : str | list | 其它   AIMessage.content 的原始值

    返回：
        str  拼接后的纯文本
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                # 只取 text 类型的块，忽略 image_url 等其它类型的块
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content or "")


def _extract_json(text: str) -> dict | None:
    """
    容错解析大模型返回的 JSON（§10.2 硬性要求的降级用例之一）。

    依次尝试三种策略，任一成功即返回：
        1. 直接 json.loads            —— 模型完全听话的情况
        2. 剥离 ```json ... ``` 围栏后解析 —— 模型习惯性加了 markdown 代码块
        3. 正则截取第一个 { 到最后一个 } 后解析 —— 模型在 JSON 前后夹带了寒暄语

    参数：
        text : str 模型返回的原始文本

    返回：
        dict  —— 解析成功
        None  —— 三种策略全部失败，调用方须走降级分支

    注意：
        本函数**只保证格式**，不保证字段内容正确。
        字段级容错交给 Pydantic，内容真实性校验交给调用方的数据库二次校验。
    """
    if not text:
        return None

    # 策略 1：直接解析
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    # 策略 2：剥离 markdown 代码块围栏（```json ... ``` 或 ``` ... ```）
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        try:
            obj = json.loads(fenced.group(1))
            return obj if isinstance(obj, dict) else None
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    # 策略 3：截取最外层花括号
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    return None


def _validate_json_text(text: str, schema: type[RecognitionT]) -> RecognitionT | None:
    """
    「文本 → 容错解析 JSON → Pydantic 校验」的组合动作。

    参数：
        text   : str             模型返回的原始文本
        schema : type[BaseModel] 目标模型

    返回：
        校验通过的对象；任一步失败返回 None

    说明：
        Pydantic 校验失败（如 confidence 给了字符串）不算致命 ——
        由于 schema 里所有字段都有默认值，绝大多数「部分字段异常」
        会被 Pydantic 自己兜住，走到这里返回 None 的基本是
        「返回的根本不是我们期望的那个对象结构」。
    """
    payload = _extract_json(text)
    if payload is None:
        return None
    try:
        return schema.model_validate(payload)
    except ValidationError:
        return None


# ===========================================================================
# 业务边界校验辅助
# ===========================================================================


def _match_candidate(
    parsed: SpaceRecognition,
    candidates: list[SpaceCandidate],
) -> SpaceCandidate | None:
    """
    把模型输出匹配到真实候选场地，**这是防幻觉的核心函数**（D2）。

    匹配顺序（从严到宽，只有唯一命中才采纳）：
        1. spaceId 直接命中候选集合          —— 最可靠
        2. spaceName 与候选名称**完全一致**   —— 模型可能只填了名称没填 id
        3. 名称互相包含且候选中**唯一**命中    —— 如模型输出「3楼展厅」，库里是「A栋3楼展厅」

    参数：
        parsed     : SpaceRecognition   模型输出
        candidates : list[SpaceCandidate] 数据库查出的候选场地

    返回：
        命中的 SpaceCandidate；一个都没命中返回 None

    为什么第 3 步要求「唯一命中」：
        若「A栋3楼展厅」与「B栋3楼展厅」都包含「3楼展厅」，
        选谁都可能是错的 —— 与其赌一把，不如返回 None 交给用户确认。
    """
    # ---- 第 1 步：按 id 命中 ----
    if parsed.spaceId is not None:
        for c in candidates:
            if c.spaceId == parsed.spaceId:
                return c
        # 命中不了 → 这就是幻觉。丢弃模型给的 id，绝不放行（§9.3 / §13）
        logger.warning("模型返回了不存在的 spaceId=%s，已丢弃（疑似幻觉）", parsed.spaceId)

    # ---- 第 2 步：按名称完全一致 ----
    name = (parsed.spaceName or "").strip()
    if not name:
        return None

    for c in candidates:
        if c.spaceName == name:
            return c

    # ---- 第 3 步：名称互相包含，且候选中唯一命中 ----
    fuzzy = [c for c in candidates if name in c.spaceName or c.spaceName in name]
    if len(fuzzy) == 1:
        return fuzzy[0]
    if len(fuzzy) > 1:
        logger.info("名称「%s」模糊匹配到 %d 个候选，存在歧义，交给用户确认", name, len(fuzzy))

    return None


def _clamp01(value) -> float:
    """
    把置信度裁剪到 [0, 1] 并转成 float。

    参数：
        value : 任意（模型可能返回 int、float、str、None）

    返回：
        float，一定落在 [0.0, 1.0]

    为什么要处理百分数：
        模型偶尔会把 0.85 写成 85。直接透传会让 Pydantic 的 ge=0/le=1 校验失败，
        进而导致整个请求 500 —— 一个格式小问题不该毁掉整次调用。
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        return 0.0

    if 1.0 < num <= 100.0:
        num = num / 100.0  # 85 → 0.85

    return max(0.0, min(1.0, num))


def _clean_str_list(items, max_items: int, max_len: int) -> list[str]:
    """
    清洗字符串数组：去空白、丢弃非字符串、去重（保序）、限长、限制条数。

    参数：
        items     : 任意            模型返回的数组
        max_items : int             最多保留多少条
        max_len   : int             单条最大长度

    返回：
        清洗后的字符串列表
    """
    if not isinstance(items, list):
        return []

    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str):
            continue
        text = item.strip()[:max_len]
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= max_items:
            break
    return result


def _make_space_question(matched: SpaceCandidate | None, confidence: float) -> str:
    """
    后端兜底追问文案（模型没生成 question 时使用）。

    规范 §4.4 要求追问文案形如：
        「识别到可能是 A 栋 3 楼展厅，置信度 65%，是否正确？」

    参数：
        matched    : 命中的候选场地；None 表示没匹配上
        confidence : 归一化后的置信度

    返回：
        一句中文追问
    """
    pct = int(round(confidence * 100))
    if matched is None:
        return _FALLBACK_SPACE_QUESTION_NO_MATCH
    return _FALLBACK_SPACE_QUESTION.format(name=matched.spaceName, pct=pct)


def _to_device_hints(device_types) -> list[DeviceHint]:
    """
    把模型返回的设备类型字符串数组转成结构化的 DeviceHint 列表。

    参数：
        device_types : 任意  模型返回的字符串数组

    返回：
        list[DeviceHint]

    ⚠️ 语义（见设计文档 §13 待确认问题 1）：
        这里返回的是「照片中**看到**的设备」，**不是**「该场地数据库里登记的配套设备」。
        原因是数据库当前没有 space_resource ↔ device_resource 的关联表，
        无法做权威校验，因此本字段仅作展示参考，**不参与任何业务决策**。
    """
    hints: list[DeviceHint] = []
    for name in _clean_str_list(device_types, max_items=10, max_len=32):
        hints.append(DeviceHint(deviceType=name, count=1, confidence=0.0))
    return hints


# ===========================================================================
# 数据库查询（只读，符合 §4.3：AI 中台只读业务数据）
# ===========================================================================


async def list_active_space_candidates(
    db: AsyncSession,
    limit: int | None = None,
) -> list[SpaceCandidate]:
    """
    查询可用于识别的候选场地（status=1 的启用场地）。

    参数：
        db    : AsyncSession  数据库会话
        limit : int | None    数量上限，默认取配置 IMAGE_SPACE_CANDIDATE_LIMIT

    返回：
        list[SpaceCandidate]  候选场地列表

    说明：
        - **只查 status=1**：停用场地不参与识别，避免用户确认了一个不可预约的场地
        - 候选列表会注入 Prompt，因此必须限制条数（D3），防止 Prompt 超长
        - 按 id 升序排列，保证同样的数据每次生成同样的 Prompt，
          便于复现问题（模型对候选顺序是敏感的）
        - 本项目不引入向量库/RAG：这里就是一张小表的全量查询，无检索环节
    """
    limit = limit or settings.IMAGE_SPACE_CANDIDATE_LIMIT

    stmt = (
        select(
            SpaceResource.id,
            SpaceResource.space_name,
            SpaceResource.space_type,
            SpaceResource.location,
            SpaceResource.capacity,
        )
        .where(SpaceResource.status == 1)
        .order_by(SpaceResource.id)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()

    return [
        SpaceCandidate(
            spaceId=row.id,
            spaceName=row.space_name,
            spaceType=row.space_type,
            location=row.location,
            capacity=row.capacity,
        )
        for row in rows
    ]


async def _safe_list_available_slots(
    db: AsyncSession,
    space_id: int,
    days: int = 1,
) -> list[AvailableSlot]:
    """
    list_available_slots 的「安全包装」：任何异常都降级为空列表。

    为什么要包一层：
        空档时段是**附加信息**（帮助用户快速选时段），不是识别的核心产物。
        它依赖 reserve_order 表的查询，一旦这里出问题，
        不应该让整个识别请求失败 —— 返回空数组即可（§8 降级矩阵第 8 条）。

    参数：
        db       : AsyncSession 数据库会话
        space_id : int          场地 ID
        days     : int          计算天数，默认只算今天

    返回：
        list[AvailableSlot]，失败时为空列表
    """
    try:
        return await list_available_slots(db, space_id, days)
    except Exception:
        logger.exception("计算场地 %s 空档时段失败，已降级为空列表", space_id)
        return []


async def list_available_slots(
    db: AsyncSession,
    space_id: int,
    days: int = 1,
) -> list[AvailableSlot]:
    """
    计算场地未来 N 天的空档时段。

    算法：
        1. 取场地的开放时段 open_start_time ~ open_end_time（§6.3 第 4 张表）
        2. 查出该场地已占用订单的区间（order_status in (1, 2)）
        3. 从开放时段里扣除占用区间，剩下的就是空档

    参数：
        db       : AsyncSession  数据库会话
        space_id : int           场地 ID
        days     : int           计算天数，默认只算今天

    返回：
        list[AvailableSlot]；场地未配置开放时段则返回空列表

    ⚠️ 契约说明：
        §5.3 契约中 availableTime 的**语义未明确定义**，
        本实现按「未来 N 天剩余可约空档」设计，
        需与小程序端确认（见设计文档 §13 待确认问题 2）。
        可通过 .env 的 IMAGE_ENABLE_AVAILABLE_SLOTS=false 一键关闭，退化为空数组。
    """
    # ---- 1. 取场地开放时段 ----
    space = (
        await db.execute(
            select(
                SpaceResource.open_start_time,
                SpaceResource.open_end_time,
            ).where(SpaceResource.id == space_id)
        )
    ).first()

    # 场地不存在，或没配置开放时间 → 无从算起，返回空
    if space is None or space.open_start_time is None or space.open_end_time is None:
        return []

    open_start: time = space.open_start_time
    open_end: time = space.open_end_time

    # ---- 2. 查占用区间（只考虑会真正占用场地的状态）----
    today = date.today()
    range_start = datetime.combine(today, time.min)  # 今天 00:00:00
    range_end = range_start + timedelta(days=days)  # N 天后 00:00:00

    stmt = (
        select(ReserveOrder.start_time, ReserveOrder.end_time)
        .where(
            ReserveOrder.space_id == space_id,
            ReserveOrder.order_status.in_(_ORDER_ACTIVE_STATUS),
            # 只取与查询区间有重叠的订单：订单开始早于区间结束 且 订单结束晚于区间开始
            ReserveOrder.start_time < range_end,
            ReserveOrder.end_time > range_start,
        )
        .order_by(ReserveOrder.start_time)
    )
    busy = (await db.execute(stmt)).all()

    # ---- 3. 逐日做「区间减法」----
    slots: list[AvailableSlot] = []

    for offset in range(days):
        d = today + timedelta(days=offset)
        day_open = datetime.combine(d, open_start)  # 当天开放起点
        day_close = datetime.combine(d, open_end)  # 当天开放终点

        # cursor 表示「当前已经处理到的时间点」，初始为开放起点
        cursor = day_open
        if cursor >= day_close:
            continue  # 开放时段为空的异常配置，跳过

        for busy_start, busy_end in busy:
            # 把跨天订单按当天边界裁剪，只关心落在 [day_open, day_close] 内的部分
            s = max(busy_start, day_open)
            e = min(busy_end, day_close)

            if e <= cursor:
                continue  # 该占用段完全在当前游标之前，跳过
            if s > cursor:
                # 占用段之前还有一段空闲 → 记为一个空档
                slots.append(_make_slot(d, cursor, min(s, day_close)))

            cursor = max(cursor, e)  # 游标推进到占用段结束
            if cursor >= day_close:
                break  # 当天已被占满，不用再看后面的订单

        # 收尾：最后一个占用段结束到闭馆之间还有空档
        if cursor < day_close:
            slots.append(_make_slot(d, cursor, day_close))

    return slots


def _make_slot(d: date, start: datetime, end: datetime) -> AvailableSlot:
    """
    把一对 datetime 区间转成契约要求的 AvailableSlot（日期 + HH:mm:ss）。

    参数：
        d     : date      所属日期
        start : datetime  区间开始
        end   : datetime  区间结束

    返回：
        AvailableSlot
    """
    return AvailableSlot(
        date=d.strftime("%Y-%m-%d"),
        startTime=start.strftime("%H:%M:%S"),
        endTime=end.strftime("%H:%M:%S"),
    )
