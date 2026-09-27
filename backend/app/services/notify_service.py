"""通知文案生成 service —— **桩函数**（阶段 3 任务 3-2）。

来源约定：流程文档阶段 3 §3.1「通知文案（模块 7）」｜负责人：黄嵩。
"""
from __future__ import annotations

__all__ = ["generate_notification"]

#: 中文枚举 → `notify_message.notify_type` 的 INT 字典（主文档 6.3 表 9）。
#: 字典本身只有三个值：1预约提醒 2变更致歉 3故障告警。
_NOTIFY_TYPE_BY_NAME: dict[str, int | None] = {
    "预约提醒": 1,
    "变更致歉": 2,
    "故障告警": 3,
    # 🔴 未决事项 #6：主文档 5.3 模块 7 的入参枚举里有「延期致歉」，
    # 但它**不在** 6.3 的 INT 字典内。此处置 None 显式暴露，不猜一个数字顶上：
    # 若映射到 2(变更致歉)，落库类型与前端文案会错配；若新增 4，需集成组先改字典。
    "延期致歉": None,
}

#: 缺省通知标题。
_TITLE_BY_NAME: dict[str, str] = {
    "预约提醒": "预约成功提醒",
    "变更致歉": "预约变更致歉",
    "故障告警": "设备故障告警",
}


async def generate_notification(order_info: dict) -> dict:
    """[桩] 通知文案生成：据订单信息产出标题与正文。

    TODO(黄嵩): 替换为模块 7 的真实通知生成 service，替换时只换函数体。
    签名未锁定,可能与真实 service 不一致,替换时需核对。

    参数：
        order_info: 订单信息字典。本桩识别以下键（其余忽略）：
            orderId     (int|None)  订单 ID
            receiverId  (int|None)  接收人 ID
            notifyType  (str)       中文通知类型，如 '预约提醒'
            spaceName   (str)       场地名称
            startTime   (str)       开始时间
            endTime     (str)       结束时间

    返回：
        {"ok": bool, "notifyType": int|None, "title": str|None,
         "content": str|None, "reason": str|None, "stub": True}

    ══════════════════════════════════════════════════════════════════════
    🔴 未决事项 #6（黄嵩 + 集成组，W2 初 `generate_notification` 前拍板）
    ══════════════════════════════════════════════════════════════════════
    `notify_message.notify_type` 是 INT 字典（1预约提醒 2变更致歉 3故障告警），
    但 5.3 模块 7 的 `POST /api/v1/notify/generate` 入参是中文枚举，
    **且「延期致歉」不在字典内**。两个口径不一致，不解决则通知落库类型映射错误。

    本桩的处理：中文名走到字典里有对应值时正常返回；遇到「延期致歉」这类字典外取值，
    返回 `ok=False` 并说明原因，**不擅自映射**。

    ⚠️ 本桩**不写库**：不 INSERT `notify_message`。真实实现是否落库、落哪张表，
    属模块 7 与集成组的边界，待未决 #6 一并谈定。
    返回恒带 `"stub": True`。
    """
    notify_name = order_info.get("notifyType") or "预约提醒"

    if notify_name not in _NOTIFY_TYPE_BY_NAME:
        return {
            "ok": False,
            "notifyType": None,
            "title": None,
            "content": None,
            "reason": (
                f"未知的通知类型 {notify_name!r}，"
                f"字典内仅有：{sorted(_NOTIFY_TYPE_BY_NAME)}。"
            ),
            "stub": True,
        }

    notify_type = _NOTIFY_TYPE_BY_NAME[notify_name]
    if notify_type is None:
        return {
            "ok": False,
            "notifyType": None,
            "title": None,
            "content": None,
            "reason": (
                f"通知类型 {notify_name!r} 在 6.3 的 notify_type 字典内无对应 INT 值"
                "（未决事项 #6）。需黄嵩 + 集成组先拍板：映射到既有值还是扩充字典。"
            ),
            "stub": True,
        }

    space_name = order_info.get("spaceName") or "所选场地"
    start_time = order_info.get("startTime") or "-"
    end_time = order_info.get("endTime") or "-"

    title = _TITLE_BY_NAME.get(notify_name, notify_name)
    content = (
        f"您预约的「{space_name}」已提交，时间 {start_time} ~ {end_time}。"
        if notify_type == 1
        else f"您预约的「{space_name}」（{start_time} ~ {end_time}）发生变更，特此致歉。"
    )

    return {
        "ok": True,
        "notifyType": notify_type,
        "title": title,
        "content": content,
        "reason": None,
        "stub": True,
    }
