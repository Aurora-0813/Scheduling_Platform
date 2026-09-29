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

__all__ = ["INSPECT_SYSTEM_PROMPT", "build_inspect_messages"]


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

