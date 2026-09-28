"""
Mock 示例数据

**为什么键名直接写 camelCase**
本文件里的都是**普通 dict**，不经过 Pydantic 模型，因此 `alias_generator`
不会生效 —— `jsonable_encoder` 只重命名「模型字段」，不会动 dict 的键。
写成 `space_id` 就会原样返回给前端，与 `docs/api.md` 约定的 camelCase 冲突。
所以这里必须手写 camelCase，改字段名时也要两边一起改。

**数据的来源与限制**
示例值与 `docs/seed.sql` 的种子数据**刻意保持同构**（同样的场地名、设备名、
订单号量级），这样前端拿 Mock 调通的页面，切到真实接口时不会因为字段形态
差异而崩。

但它们终究是**写死的常量**，不随请求变化，也不能增删改：
`POST /mock/resources/spaces` 返回的是「假设新增成功」的样子，数据库里
并没有真的多一条。因此 Mock 只用于**前端/小程序先行开发**，
不能用于验收与联调 —— 联调必须打真实接口（见 `docs/deploy.md`）。

命名规范：模块名 + 用途，例如 `SPACE_ANALYZE`。改数据时请在
`docs/api.md` 的 Mock 一节同步更新说明。
"""

from __future__ import annotations

__all__ = [
    "VOICE_ASR",
    "VOICE_FORMAT",
    "IMAGE_ANALYZE",
    "IMAGE_SKETCH",
    "ORDER_CREATED",
    "ORDERS_MY",
    "MESSAGES_UNREAD",
    "AGENT_SCHEDULE",
    "SPACES",
    "SPACE_CREATED",
    "DEVICES",
    "DEVICE_UPDATED",
    "INSPECT_SUBMIT",
    "TICKETS",
    "TICKET_UPDATED",
    "CONFLICTS",
    "NOTIFY",
    "DASHBOARD_STATS",
    "DASHBOARD_REPORT",
]

# ==========================================================================
# 模块 1：语音输入
# ==========================================================================
VOICE_ASR: dict = {
    "text": "帮我把明天下午两点的三号会议室订两小时，再带一台投影仪",
}

VOICE_FORMAT: dict = {
    "formattedText": "预约三号会议室，时间：明天 14:00-16:00，需要设备：投影仪",
    "keywords": ["三号会议室", "明天 14:00", "投影仪", "2 小时"],
}

# ==========================================================================
# 模块 2：摄像头空间感知
# ==========================================================================
IMAGE_ANALYZE: dict = {
    "type": "space",
    "spaceId": 101,
    "spaceName": "三号会议室",
    "confidence": 0.92,
    "availableTime": ["2026-09-28 14:00:00 - 16:00:00", "2026-09-28 19:00:00 - 21:00:00"],
    "devices": [
        {"id": 1, "name": "投影仪 A", "type": "投影仪", "status": 1},
        {"id": 2, "name": "白板 B", "type": "白板", "status": 1},
    ],
}

IMAGE_SKETCH: dict = {
    "type": "sketch",
    "capacity": 30,
    "layout": "矩形空间，正面靠墙布置讲台与投影幕布，纵向 6 排 × 5 列桌椅",
    "requirements": ["需要投影仪", "需要扩音设备", "要求靠窗采光"],
    "confidence": 0.85,
}

# ==========================================================================
# 模块 3：移动端预约与通知
# ==========================================================================
ORDER_CREATED: dict = {
    "orderId": 1001,
    "orderNo": "RS20260928001",
    "spaceId": 101,
    "spaceName": "三号会议室",
    "deviceIds": [1, 2],
    "startTime": "2026-09-28 14:00:00",
    "endTime": "2026-09-28 16:00:00",
    "status": 1,
    "statusText": "已确认",
}

ORDERS_MY: dict = {
    "page": 1,
    "pageSize": 10,
    "total": 2,
    "list": [ORDER_CREATED],
}

MESSAGES_UNREAD: dict = {
    "total": 1,
    "list": [
        {
            "id": 501,
            "type": "预约成功",
            "title": "预约成功通知",
            "content": "您的「三号会议室」预约已确认，时间 2026-09-28 14:00-16:00。",
            "isRead": False,
            "createTime": "2026-09-27 15:04:05",
        }
    ],
}

# ==========================================================================
# 模块 4：核心调度 Agent
# ==========================================================================
AGENT_SCHEDULE: dict = {
    "plan": {
        "spaceId": 101,
        "spaceName": "三号会议室",
        "deviceIds": [1, 2],
        "startTime": "2026-09-28 14:00:00",
        "endTime": "2026-09-28 16:00:00",
        "reason": "容量 30 人满足 20 人需求，投影仪与白板可用且无时间冲突",
    },
    "backupPlan": {
        "spaceId": 102,
        "spaceName": "四号会议室",
        "deviceIds": [3],
        "startTime": "2026-09-28 15:00:00",
        "endTime": "2026-09-28 17:00:00",
        "reason": "主方案被占用时的次优选择，容量 20 人，需自带投影仪",
    },
    "trace": [
        {"step": 1, "result": "识别意图：预约会议室", "timestamp": "2026-09-27 15:04:05"},
        {"step": 2, "result": "查询可用场地：命中 2 个候选", "timestamp": "2026-09-27 15:04:06"},
        {"step": 3, "result": "查询可用设备：投影仪 A、白板 B", "timestamp": "2026-09-27 15:04:06"},
        {"step": 4, "result": "生成主方案与备选方案", "timestamp": "2026-09-27 15:04:07"},
    ],
    # 走的是「需要人工确认」的分支，前端据此弹确认框
    "needConfirm": True,
}

# ==========================================================================
# 模块 5：资源与设备管理
# ==========================================================================
SPACES: dict = {
    "page": 1,
    "pageSize": 10,
    "total": 2,
    "list": [
        {
            "id": 101,
            "name": "三号会议室",
            "type": "会议室",
            "capacity": 30,
            "location": "A 栋 3 层",
            "status": 1,
            "statusText": "可用",
        },
        {
            "id": 102,
            "name": "四号会议室",
            "type": "会议室",
            "capacity": 20,
            "location": "A 栋 3 层",
            "status": 1,
            "statusText": "可用",
        },
    ],
}

SPACE_CREATED: dict = {
    "id": 999,
    "name": "（Mock）新建场地",
    "type": "会议室",
    "capacity": 10,
    "location": "B 栋 1 层",
    "status": 1,
}

DEVICES: dict = {
    "page": 1,
    "pageSize": 10,
    "total": 2,
    "list": [
        {
            "id": 1,
            "name": "投影仪 A",
            "type": "投影仪",
            "spaceId": 101,
            "status": 1,
            "statusText": "正常",
        },
        {
            "id": 2,
            "name": "白板 B",
            "type": "白板",
            "spaceId": 101,
            "status": 1,
            "statusText": "正常",
        },
    ],
}

DEVICE_UPDATED: dict = {
    "id": 1,
    "name": "投影仪 A",
    "type": "投影仪",
    "spaceId": 101,
    "status": 2,
    "statusText": "维修中",
}

# ==========================================================================
# 模块 6：AI 智能巡检
# ==========================================================================
INSPECT_SUBMIT: dict = {
    "deviceStatus": "损坏",
    "report": "巡检照片显示投影仪指示灯为红色常亮，画面无输出，判定为灯泡损坏。",
    "repairSuggestion": "更换投影仪灯泡（型号 ET-LAL510），预计耗时 30 分钟。",
    "ticketId": 202,
}

TICKETS: dict = {
    "page": 1,
    "pageSize": 10,
    "total": 1,
    "list": [
        {
            "id": 202,
            "spaceId": 101,
            "deviceId": 1,
            "deviceStatus": "损坏",
            "status": 1,
            "statusText": "待处理",
            "report": "投影仪指示灯红灯常亮，无画面输出。",
            "createTime": "2026-09-27 15:04:05",
        }
    ],
}

TICKET_UPDATED: dict = {
    "id": 202,
    "status": 3,
    "statusText": "已完成",
    "handlerId": 1,
    "handleTime": "2026-09-27 16:20:00",
}

# ==========================================================================
# 模块 7：AI 冲突预警与智能通知
# ==========================================================================
CONFLICTS: list = [
    {
        "conflictType": "软冲突",
        "orderIds": [1001, 1002],
        # 字符串在代码里换行拼接，前端拿到的是一个完整句子（没有换行符）
        "suggestion": (
            "两笔预约均需「投影仪 A」且在 15:00-16:00 重叠，"
            "建议将订单 1002 改约至 16:00 后，或改用「投影仪 C」。"
        ),
    }
]

NOTIFY: dict = {
    "title": "预约时间变更致歉",
    "content": (
        "您好，因场地临时检修，您预约的「三号会议室」时间需调整至 16:00-18:00，"
        "由此带来的不便我们深表歉意。如有疑问请回复本消息。"
    ),
}

# ==========================================================================
# 模块 8：AI 数据洞察面板
# ==========================================================================
DASHBOARD_STATS: dict = {
    "spaceUsageRate": 85.5,
    "deviceIdleRate": 20.1,
    "peakHours": [
        {"hour": 10, "count": 12},
        {"hour": 14, "count": 18},
        {"hour": 16, "count": 15},
    ],
    "faultFrequency": [
        {"deviceType": "投影仪", "count": 5},
        {"deviceType": "白板", "count": 1},
    ],
}

DASHBOARD_REPORT: dict = {
    "suggestions": [
        {
            "finding": "三号会议室 14:00-16:00 时段使用率连续 3 周超过 90%",
            "evidence": "近 3 周该时段预约 42 次，其中 38 次为已确认状态，冲突预警 4 次",
            "suggestion": "建议将 14:00 的常规例会分流至四号会议室，或增加一处同容量场地",
        }
    ],
    # 指向文件服务的导出地址。Mock 阶段给的是占位路径，
    # 前端不要假设它能下载到真实文件。
    "exportUrl": "/api/v1/mock/dashboard/report/export",
}
