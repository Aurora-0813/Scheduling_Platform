"""
模块 6：AI 智能巡检 —— Prompt 模板

与 `image_prompt.py` 同一套写法：System 里写死判断规则，Human 是「文本块 + 图片块」的多模态消息。
图片走 **base64 data URL 内联**，不给 URL —— 多模态模型需要能直接读到像素，
而我们的 uploads 目录是内网地址，外部模型 API 访问不到（理由同 image_prompt）。

为什么把「完好 / 损坏 / 缺失配件 / 无法识别」四个取值钉在 Prompt 里
----------------------------------------------------------------
`deviceStatus` 直接决定**要不要建维修工单**。若不限定取值，模型可能返回
「轻微损坏」「基本正常」这类自由文本，业务层就只能靠字符串包含判断 ——
那是「同一件事在两个地方各判一次」，改一处漏一处。所以取值写进 Prompt，
并在 service 层用白名单兜底（模型不听话时判为「无法识别」，**不建工单**）。
"""

from langchain_core.messages import HumanMessage, SystemMessage

__all__ = [
    "INSPECT_SYSTEM_PROMPT",
    "HANDLE_VERIFY_SYSTEM_PROMPT",
    "build_inspect_messages",
    "build_handle_verify_messages",
]


INSPECT_SYSTEM_PROMPT = """你是资深设备巡检专家。请仔细观察这张设备巡检照片，完成三件事：
1. 客观描述画面中设备的实际状况：外观、部件、铭牌、仪表读数，
   以及有无锈蚀、破损、渗漏、变形、异物、指示灯异常等
2. 判断该设备的状况，填入 deviceStatus
3. 写一份巡检报告填入 report；若判定异常，再给 repairSuggestion

deviceStatus 只能取以下四个值之一，**不要自创措辞**：
- 完好       画面中设备外观与指示正常，未发现异常
- 损坏       有明显损坏，如破损、变形、渗漏、指示灯异常、无输出
- 缺失配件   设备本体正常，但缺少必要配件（如缺线缆、缺支架、缺镜头盖）
- 无法识别   照片空白、严重模糊、完全遮挡，或画面里根本没有可辨认的设备

严格要求：
- 只输出结构化字段，不要输出额外的解释文字，不要用 markdown 代码块包裹
- deviceName / deviceType 认不出就填 null，**不要编造**具体的编号或型号
- deviceName 写**画面里看得见的**名字，不要凭猜测补上品牌或型号：
  只看得出一台无人机、看不出牌子时写 `无人机`，**不要**写成 `大疆无人机` ——
  补出来的品牌会对不上台账里的设备名，系统就找不到该更新哪台设备的状态
- **画面里不一定是「设备」**：巡检范围还包括固定设施（电路、插座、门把手等），
  它们**不在设备台账里**。这类请在 deviceName 里写通用名，并**优先从这份清单里选**
  （统一命名才能按设施统计）：
  配电箱、电路、插座、开关、照明灯具、空调、出风口、水管、水龙头、消防栓、
  灭火器、门、门把手、门锁、窗、玻璃、墙面、地面、天花板、楼梯、扶手、
  标识牌、垃圾桶、窗帘。
  台账里的设备（如「投影仪01」）则照原样写编号。
- locationHint 填画面里能看出的**具体位置**（如「3楼走廊东侧」「会议室门口」）；
  看不出就填 null，**不要编造**
- deviceStatus 为 完好 或 无法识别 时，repairSuggestion 必须留空字符串
- report 300 字以内，repairSuggestion 100 字以内，都不要分点编号
- 只依据**画面里看得见的东西**下结论；看不清就说看不清，不要脑补内部故障"""


def build_inspect_messages(*, image_data_url: str, space_name: str | None = None) -> list:
    """
    构造「巡检照片分析」的对话消息列表。

    参数：
        image_data_url : str
            图片的 data URL，形如 "data:image/jpeg;base64,/9j/4AAQ..."。
        space_name : str | None
            这张照片是在哪个场地拍的（来自 `space_resource.space_name`，
            **由后端查出后注入，不是模型生成的**）。给模型一个位置上下文，
            能让 report 里出现「A栋3楼展厅的投影仪」而不是干巴巴的「一台投影仪」。

    返回：
        list[BaseMessage]：可直接喂给 ChatOpenAI.ainvoke()
    """
    where = f"拍摄地点：{space_name}。" if space_name else "拍摄地点：未提供。"
    user_text = f"{where}请分析这张巡检照片，按要求给出结构化结论。"

    # 多模态消息：content 是「内容块」列表，文本块与图片块混排 ——
    # OpenAI 兼容协议的通用写法，langchain-openai 会原样透传给模型。
    return [
        SystemMessage(content=INSPECT_SYSTEM_PROMPT),
        HumanMessage(
            content=[
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ]
        ),
    ]


# ===========================================================================
# 维修完成后核验（模块 6 追加）
# ===========================================================================
HANDLE_VERIFY_SYSTEM_PROMPT = """你是资深设备维修验收专家。维修人员刚完成维修并拍下了这张照片，
请核验设备是否已恢复正常。

请完成两件事：
1. 客观描述画面中设备**现在**的状况：外观、部件是否齐全、指示灯是否正常、有无残留破损或渗漏
2. 判断该设备当前的状况，填入 deviceStatus；把核验说明填入 report

deviceStatus 只能取以下四个值之一，**不要自创措辞**：
- 完好       画面中设备外观与指示正常，未发现异常 —— 视为**维修成功**
- 损坏       仍有明显损坏，如破损、变形、渗漏、指示灯异常、无输出 —— 视为**维修未成功**
- 缺失配件   设备本体正常，但仍缺少必要配件（如缺线缆、缺支架、缺镜头盖）—— 视为**维修未成功**
- 无法识别   照片空白、严重模糊、完全遮挡，或画面里根本没有可辨认的设备

严格要求：
- 只输出结构化字段，不要输出额外的解释文字，不要用 markdown 代码块包裹
- deviceName 认不出就填 null，**不要编造**具体的编号或型号
- report 200 字以内，不要分点编号；未通过时要说清**还差什么**，便于维修人员返工
- 只依据**画面里看得见的东西**下结论；看不清就填 无法识别，不要为了「让流程通过」而放宽标准
- 不要因为照片里有维修工具、包装盒等无关物品就判定异常，只看设备本体"""


def build_handle_verify_messages(
    *,
    image_data_url: str,
    space_name: str | None = None,
    device_name: str | None = None,
    original_problem: str | None = None,
) -> list:
    """
    构造「维修后核验」的对话消息列表。

    参数：
        image_data_url : str
            处理后照片的 data URL（同 build_inspect_messages，内联 base64）。
        space_name : str | None
            拍摄地点，由后端查出后注入，不是模型生成的。
        device_name : str | None
            这台设备是什么。来自原巡检记录里模型认出的 deviceName，
            **可能为 None**（当初就没认出来），此时不写进上下文。
        original_problem : str | None
            原巡检报告，用来说明「当初坏在哪」。给模型一个**对照基准**，
            它才知道该重点看什么（如原报告说「指示灯不亮」，就该重点看指示灯）。

    为什么把原巡检报告放进 Prompt
    ----------------------------
    只给一张「修好之后」的照片，模型只能判断「现在看起来正不正常」，
    无法回答「原来那个问题解决了没有」。附上原报告，核验才有针对性。
    「无法判断原问题是否解决」时按 Prompt 要求回落为 无法识别，不放水。

    返回：
        list[BaseMessage]：可直接喂给 ChatOpenAI.ainvoke()
    """
    parts: list[str] = []
    if space_name:
        parts.append(f"拍摄地点：{space_name}。")
    if device_name:
        parts.append(f"设备名称：{device_name}。")
    if original_problem:
        # 截断：原巡检报告上限 300 字，这里再收一道，避免 Prompt 被个别长报告撑大
        parts.append(f"维修前的巡检结论：{original_problem[:300]}")
    context = "".join(parts) or "未提供维修前的上下文。"

    user_text = f"{context}\n请核验这张维修后的照片，按要求给出结构化结论。"

    return [
        SystemMessage(content=HANDLE_VERIFY_SYSTEM_PROMPT),
        HumanMessage(
            content=[
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ]
        ),
    ]
