"""
摄像头空间感知模块 —— Prompt 模板
====================================================================

按 §7.4「Prompt 模板集中管理，便于迭代」放在 agent/prompts/ 下。

两个模板：
    build_space_analyze_messages()  → 现场拍照识别空间 / 门牌
    build_sketch_analyze_messages() → 手绘草图识别

设计原则（每一条都对应一个具体规范）：
    1. 强约束 JSON 输出 —— §13：Prompt 强制约束输出格式。
       虽然首选路径用 with_structured_output 由 JSON Schema 兜底，
       但本模块保留了「手工解析」这条降级路径（见 image_service._recognize），
       那条路径完全依赖 Prompt 里的格式说明，所以这里**必须**写清楚字段。
    2. 候选约束 spaceId —— §9.3：防止大模型编造不存在的场地。
       模型只能做「选择题」，不能做「填空题」。
    3. 置信度自评 —— §4.4 模块 2：识别结果附带 AI 置信度评分。
    4. 追问文案由模型生成 —— §4.4：置信度低于阈值时 AI 主动生成追问文案。
       后端另有一份模板兜底，防止模型漏填。

关于参考示例（few-shot）：
    刻意**不**在 Prompt 里放「示例照片对应的答案」。
    因为视觉任务的参考示例必须以图片形式给出，纯文本示例帮不上忙还会占用上下文。
    识别准确率靠「候选列表 + 门牌文字优先」的策略保证。
"""

from langchain_core.messages import HumanMessage, SystemMessage

# ===========================================================================
# 模板 1：现场拍照识别空间
# ===========================================================================

_SPACE_SYSTEM_TEMPLATE = """你是「智能空间调度平台」的空间感知助手。你的唯一任务是：\
观察用户拍摄的现场照片，判断这是候选列表中的哪个场地，\
并抽取照片中可见的关键信息。

【候选场地列表】（你必须、且只能从这里选择，严禁编造列表之外的场地）
{candidate_lines}

【判断依据（按优先级从高到低）】
1. 门牌文字、房间编号、标识牌 —— 这是最可靠、最优先的证据
2. 空间形态：座位排布方式、舞台/讲台、大屏、层高、采光
3. 可见设备：投影幕布、音响、显示屏、会议终端
4. 候选列表中若有名称与照片中的文字高度吻合的，直接选它

【输出字段说明】
- spaceId：从候选列表中选出的场地 id（整数）。一个都不像就填 null。**绝对不要编造 id**。
- spaceName：所选场地的名称，必须与候选列表中的写法逐字一致。选不出填 null。
- rawText：照片中识别到的门牌号/标识牌文字原文。没有文字填 null。
- deviceHints：照片中**肉眼可见**的设备类型名称字符串数组，例如 ["投影仪","音响"]。看不出来填 []。
- confidence：你对 spaceId 判断的置信度，0 到 1 之间的小数（**不是百分数**），诚实自评。
- question：若 confidence 低于 {threshold}，生成一句向用户确认的中文追问，
  格式参考「识别到可能是 XXX，置信度 XX%，是否正确？」；否则填 null。

【纪律】
- 拿不准就把 confidence 调低，**绝对不要猜**。低置信度完全可以接受，编造场地不可接受。
- spaceId 与 spaceName 要么同时给出，要么同时为 null。
- 只输出结构化字段，不要输出额外的解释文字。"""


def build_space_analyze_messages(
    image_data_url: str,
    candidates: list[dict],
    threshold: float,
) -> list:
    """
    构造「现场拍照识别空间」的对话消息列表。

    参数：
        image_data_url : str
            图片的 data URL，形如 "data:image/jpeg;base64,/9j/4AAQ..."。
            之所以转 base64 内联而不是给 URL：多模态模型需要能直接读到像素，
            而我们的 uploads 目录是内网地址，外部模型 API 根本访问不到。

        candidates : list[dict]
            候选场地列表，每项含 spaceId / spaceName / spaceType / location / capacity。
            **由后端从 space_resource 实时查出**，不是模型生成的，也不是向量检索来的
            （本项目不引入向量库/RAG，候选集就是一张小表的全量查询）。

        threshold : float
            置信度阈值。注入 Prompt 让模型知道「低于多少需要追问」，
            与后端判定使用同一个配置值，保证前后端行为一致。

    返回：
        list[BaseMessage]：可直接喂给 ChatOpenAI.ainvoke()
    """
    # 把候选列表渲染成「人类可读、模型好解析」的文本行
    # 兜底：一个候选都没有时明确告诉模型，避免它「强行选一个」
    if candidates:
        candidate_lines = "\n".join(
            f"- id={c['spaceId']} | 名称={c['spaceName']} | 类型={c['spaceType']} "
            f"| 位置={c.get('location') or '未知'} | 容量={c.get('capacity') or '未知'}人"
            for c in candidates
        )
    else:
        candidate_lines = "（当前系统中没有可用场地，你应当把 spaceId 与 spaceName 都填 null）"

    system_prompt = _SPACE_SYSTEM_TEMPLATE.format(
        candidate_lines=candidate_lines,
        threshold=threshold,
    )

    # 多模态消息：content 是一个「内容块」列表，文本块与图片块混排。
    # 这是 OpenAI 兼容协议的通用写法，langchain-openai 会原样透传给模型。
    return [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=[
                {"type": "text", "text": "请分析这张现场照片，按要求给出识别结果。"},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ]
        ),
    ]


# ===========================================================================
# 模板 2：手绘草图识别
# ===========================================================================

_SKETCH_SYSTEM_TEMPLATE = """你是「智能空间调度平台」的草图解读助手。\
用户会给你一张**手绘的空间布局草图**\
（可能是座位排布、区域划分、动线示意），你需要把它翻译成结构化的空间需求。

【输出字段说明】
- capacity：根据图中座位/椅子/分区数量预估的容纳人数（正整数）。图中没有可数的座位信息填 null。
- layout：用一句中文描述布局形式，例如「圆桌围坐，中间留空作展示区」「剧院式排布，前方设讲台」。
- requirements：从草图推断出的场地约束关键词字符串数组，
  例如 ["需要投影","需要围坐讨论","需要独立出入口"]。图中出现的文字标注应直接采纳。
- confidence：整体解读置信度，0 到 1 之间的小数（**不是百分数**），诚实自评。
- question：若 confidence 低于 {threshold}，生成一句向用户确认的中文追问；否则填 null。

【解读要点】
- 数图形的数量和排布方式来估人数，**不要凭空给数字**
- 图上的文字标注（如「投影」「白板」「入口」）要直接采纳进 requirements
- 模糊不清的地方不要把 confidence 撑高，宁可让用户补充一句

【纪律】
- 看不清就填 null 或空数组，**不要编造**
- 只输出结构化字段，不要输出额外的解释文字。"""


def build_sketch_analyze_messages(image_data_url: str, threshold: float) -> list:
    """
    构造「手绘草图识别」的对话消息列表。

    参数：
        image_data_url : str   图片 data URL（说明同模板 1）
        threshold      : float 置信度阈值

    返回：
        list[BaseMessage]：可直接喂给 ChatOpenAI.ainvoke()

    与模板 1 的区别：
        草图识别不需要候选列表 —— 它解读的是「需求」而不是「身份」，
        所以 Prompt 更短，且不做任何数据库校验（草图上本来就没有真实场地）。
    """
    return [
        SystemMessage(content=_SKETCH_SYSTEM_TEMPLATE.format(threshold=threshold)),
        HumanMessage(
            content=[
                {"type": "text", "text": "请解读这张手绘布局草图，按要求给出解读结果。"},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ]
        ),
    ]
