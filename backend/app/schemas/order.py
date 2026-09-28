"""预约订单请求模型（§5.3 模块3，camelCase；身份一律从 JWT 解析 §5.1）。

本文件只描述**传输契约**：字段名、类型、默认值。业务规则（时间能不能解析、
开始是否早于结束、场地/设备存不存在）一律不在这里判，见下方说明。
"""
from pydantic import BaseModel


class OrderCreate(BaseModel):
    """POST /api/v1/orders/create 请求体。

    ⚠️ **时间校验刻意不放在本模型里**（此前有过一版 `@model_validator`，已移除）。
    两个原因：

    1. **消息会被吞掉。** 校验器抛 `ValueError` 后，团队的异常处理器按
       `_VALIDATION_MESSAGES[type]` 取通用文案（`value_error` -> `取值不合法`），
       校验器里写的中文（「开始时间必须早于结束时间」「时间格式应为
       YYYY-MM-DD HH:mm:ss」）**不会出现在响应里**。前端只能显示一句无信息量的
       「参数校验未通过：body 取值不合法」，而这两条恰恰是用户最需要看到的原因。
    2. **两处校验会漂移。** 同一套时间规则同时写在模型和 `order_service` 里，
       改一处漏一处就是线上不一致；而 Agent 的 `lock_resources` Tool 直接调
       `order_service.create_order`（§4.3），**根本不经过本模型** —— 模型里的
       那份校验对 Agent 路径完全无效。

    因此校验只在 `order_service` 里做一次，失败以 `conflictType="invalid_param"`
    返回，由 `api/orders.py` 翻译成 `400` / `40001`。
    """

    spaceId: int
    deviceIds: list[int] = []
    startTime: str
    endTime: str
    agentRequest: str = ""     # 用户原始需求（Agent 创建时填入）
    agentTrace: list = []      # AI 思考过程追踪（JSON 数组）
