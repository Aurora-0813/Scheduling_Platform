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

**唯一的例外**：`AGENT_SCHEDULE`（模块 4 的思考链）不写在本文件里，而是读
仓库根的 `docs/mock/agent_schedule.json` —— 那份数据要与前端、演示回放、
应急预案共用，两个副本一旦漂移不会报错，只会到演示现场才发现。详见该常量
上方的说明。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

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
# 本块**不写死数据**，改为读仓库根的 `docs/mock/agent_schedule.json`。
#
# 为什么改成读文件
# ----------------
# 这份思考链是**一处数据三处用**：
#     ① 前端屏 3 的思考链渲染
#     ② 演示的 40 秒回放（7 步，时间戳跨 39 秒、间隔不均）
#     ③ 主文档 13.1 应急预案的预置 trace
# 原先代码里另写了一份 4 步 / 间隔 1 秒的常量，与 json 的 7 步 / 39 秒各说各话。
# 这类不一致**不会报错**：两条路都能正常返回、前端也能渲染，只有到演示现场
# 才发现回放节奏和预置 trace 对不上，而那时已经没有排查时间。
# 现在 json 是唯一真源 —— 改数据只改 json，代码这边不用动，也就不会再漂移。
#
# 路径
# ----
# json 要和前端共用，因此放在**仓库根** `docs/mock/` 下（不是 `backend/docs/`）——
# 与模块 4 原实现 `mock.py` 里的 `parents[4] / "docs" / "mock"` 是同一处。
# 允许两种检出布局，取先命中的：
#     仓库布局（常态）  <repo>/docs/mock/agent_schedule.json    ← backend_dir.parent
#     后端独立布局      <backend>/docs/mock/agent_schedule.json ← backend_dir
_AGENT_SCHEDULE_RELATIVE = ("docs", "mock", "agent_schedule.json")

_AGENT_SCHEDULE_CANDIDATES = tuple(
    base.joinpath(*_AGENT_SCHEDULE_RELATIVE)
    for base in (settings.backend_dir.parent, settings.backend_dir)
)


def _resolve_agent_schedule_path() -> Path | None:
    """返回第一个存在的候选路径；都没有则 None。"""
    return next((path for path in _AGENT_SCHEDULE_CANDIDATES if path.is_file()), None)


#: 实际读到的 json 路径；None 表示候选路径都不存在（此时下方会打 ERROR 日志）。
#: 测试用它与同一个来源判断「数据到底读没读到」，避免两边各写一份路径解析。
AGENT_SCHEDULE_JSON_PATH: Path | None = _resolve_agent_schedule_path()


def _load_agent_schedule() -> dict:
    """读 mock 思考链 JSON 的 `data` 段（外层 code/message 由 ok() 统一包）。

    读不到时返回 `{}` 并打 ERROR 日志，而**不是**抛异常：本文件只服务 Mock
    接口，不该让一个演示数据文件缺失把整个应用的启动带崩。缺文件时
    `tests/api/test_agent_schedule_mock.py` 会明确失败，问题在测试阶段暴露。
    """
    if AGENT_SCHEDULE_JSON_PATH is None:
        logger.error(
            "Mock 思考链数据缺失，/mock/agent/schedule 将返回空 data；期望路径：%s",
            " 或 ".join(str(path) for path in _AGENT_SCHEDULE_CANDIDATES),
        )
        return {}

    with AGENT_SCHEDULE_JSON_PATH.open(encoding="utf-8") as fp:
        return json.load(fp)["data"]


AGENT_SCHEDULE: dict = _load_agent_schedule()

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
