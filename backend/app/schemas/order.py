"""预约订单请求模型（§5.3 模块3，camelCase；身份一律从 JWT 解析 §5.1）。"""
from pydantic import BaseModel, model_validator

from ..core.utils import parse_time


class OrderCreate(BaseModel):
    """POST /api/v1/orders/create 请求体。"""

    spaceId: int
    deviceIds: list[int] = []
    startTime: str
    endTime: str
    agentRequest: str = ""     # 用户原始需求（Agent 创建时填入）
    agentTrace: list = []      # AI 思考过程追踪（JSON 数组）

    @model_validator(mode="after")
    def _check_time(self):
        s = parse_time(self.startTime)  # 非法格式抛 ValueError -> 422
        e = parse_time(self.endTime)
        if s >= e:
            raise ValueError("开始时间必须早于结束时间")
        return self
