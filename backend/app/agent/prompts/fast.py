"""单次调用快速模式的 Prompt（与多轮版并存）。

与 scheduler.py 的 SCHEDULER_PROMPT 的本质差别：**候选资源已经全部列在 Prompt 里**，
模型不再「决定去查什么」，只做一道选择题 —— 所以只有一次模型往返。

为什么不合并进 scheduler.py：那两份的读者不同 —— 一份教模型「怎么用工具去查」，
本份把查好的候选直接摆出来。混在一起会让两边都变糊涂。

注意 _format_now 是 scheduler.py 的模块级函数，此处直接复用，不再复制一份中文星期表
（那份表与主文档「相对时间换算规则」是同一份口径，复制会产生两处漂移）。
"""

from __future__ import annotations

import json
from datetime import datetime

from app.agent.prompts.scheduler import _format_now

__all__ = ["build_fast_prompt"]

#: 不用 f-string：下方 JSON 示例里有大量字面花括号，f-string 会把它们当占位符解析。
#: 统一走 str.replace，占位符只用命名花括号 {spaces} / {devices} / {current_time} / {text}。
_FAST_PROMPT = """你是「智能空间与设备综合调度平台」的调度 AI。

下面已经把系统里**全部可用的场地与设备**列给你了。你的任务：从这些候选里
挑出最合适的一组，直接输出方案。**绝对不要编造候选之外的 ID。**

# 一、选择规则

1. **只能用下方列出的场地 ID 与设备 ID**，候选之外的 ID 一律无效。
2. **容量**：场地容量必须 ≥ 用户人数；在满足的前提下**优先选容量最接近的**（避免浪费）。
3. **场地类型对照**：1=会议室 2=展厅 3=多功能厅 4=户外场地。
4. **设备**：用户提到的设备从【候选设备】里选 ID；不需要就传 []。
   某类型没有候选 = 当前借不到，在 reason 里说明并给替代建议。
5. **时间**：必须换算成 YYYY-MM-DD HH:mm:ss 绝对格式。
6. **无可行方案时**（例如没有容量够的场地）：plan 传 null，
   在 reason 里说明原因并给出至少 3 条可操作的修改建议。

# 二、输出格式

**只输出一个 JSON 对象**，不要解释文字、不要 markdown 代码块：

{
  "plan": {"spaceId": 1, "spaceName": "A栋201会议室", "deviceIds": [1],
           "startTime": "2026-10-13 15:00:00", "endTime": "2026-10-13 16:00:00",
           "reason": "为什么这么选；做过降级/替代的必须写明"},
  "backupPlan": null,
  "reason": "整体一句话说明"
}

# 三、候选场地

{spaces}

# 四、候选设备

{devices}

# 五、当前时间

{current_time}

# 六、用户需求

{text}
"""


def build_fast_prompt(
    *,
    text: str,
    spaces: list[dict],
    devices: list[dict],
    image_context: dict | None = None,
    now: datetime | None = None,
) -> str:
    """渲染快速模式 Prompt：把全部候选资源一次性交给模型。

    参数：
        text          : 用户原始需求（**不预抽取**，原样交给模型，避免规则抽取漏字段）
        spaces        : 全部可用场地（services.space_service.list_available_spaces）
        devices       : 全部可借用设备（services.device_service.list_available_devices）
        image_context : 模块 2 传来的图像上下文，作为补充证据拼在需求之后
        now           : 当前时刻，测试可注入；默认系统时间
    """
    spaces_json = json.dumps(spaces, ensure_ascii=False)
    devices_json = json.dumps(devices, ensure_ascii=False)

    # 用 chr(10) 而不是转义序列：本文件是跨平台维护的，显式换行更不容易被
    # 「反斜杠数量」这类肉眼难查的问题破坏。
    extra = ""
    if image_context:
        nl = chr(10)
        extra = (
            nl + nl
            + "[来自摄像头/草图的图像解析上下文，作为补充证据参考，"
            "可能与文字描述冲突，以文字描述为准并指出冲突]"
            + nl
            + json.dumps(image_context, ensure_ascii=False)
        )

    return (
        _FAST_PROMPT.replace("{spaces}", spaces_json)
        .replace("{devices}", devices_json)
        .replace("{current_time}", _format_now(now or datetime.now()))
        .replace("{text}", f"{text}{extra}")
    )
