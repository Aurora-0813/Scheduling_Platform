"""Tool 1/5：`query_spaces` —— 按容量与类型检索可用场地。

对应主文档 5.3 模块 4 冻结签名：
    async def query_spaces(capacity: int, space_type: int, start_time: str, end_time: str) -> dict

**签名不得改动**——阶段 3 的桩、阶段 7 的用例都以它为基准（阶段 4 §3.1）。
"""
from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.tools._common import fail, parse_time
from app.services import query_spaces as _query_spaces_service

__all__ = ["query_spaces", "QuerySpacesArgs"]

#: `space_type` 的 INT 字典（主文档 6.3 表 4）。
#: 这份对照表**同时**出现在 Prompt 里（阶段 5.1）——模型的自然语言是「展厅」，
#: Tool 收的是 `2`，不给对照表就指望模型猜数字，场景 A/B 会大面积失败。
SPACE_TYPE_LABELS = {1: "会议室", 2: "展厅", 3: "多功能厅", 4: "户外场地"}


class QuerySpacesArgs(BaseModel):
    """`query_spaces` 的入参 schema。由 Pydantic 校验，模型填错时错误信息会回到模型侧。"""

    capacity: int = Field(..., gt=0, le=10000, description="所需容量下限（人数），必须为正整数")
    space_type: int = Field(
        ..., ge=1, le=4,
        description="场地类型：1=会议室 2=展厅 3=多功能厅 4=户外场地",
    )
    start_time: str = Field(..., description="需求开始时间，格式 YYYY-MM-DD HH:mm:ss")
    end_time: str = Field(..., description="需求结束时间，格式 YYYY-MM-DD HH:mm:ss")


@tool("query_spaces", args_schema=QuerySpacesArgs)
async def query_spaces(capacity: int, space_type: int, start_time: str, end_time: str) -> dict:
    """查询满足容量与类型要求的可用场地。

    什么时候用：需要为用户需求挑选场地时，先调这个工具拿到候选场地，再从中选。
    不要凭空编造场地——本工具返回的是数据库里的真实资源，没查到就是没有。

    Args:
        capacity: 所需容量下限（人数）。例如需求「40 人」就传 40，返回的都是能坐下 40 人的场地。
        space_type: 场地类型编号。**必须传数字**：1=会议室 2=展厅 3=多功能厅 4=户外场地。
        start_time: 需求开始时间，格式 `YYYY-MM-DD HH:mm:ss`。
        end_time: 需求结束时间，格式 `YYYY-MM-DD HH:mm:ss`，必须晚于 start_time。

    Returns:
        {"ok": true, "count": 2, "spaces": [
            {"id": 4, "spaceName": "A栋3楼展厅", "spaceType": 2, "capacity": 50,
             "location": "A栋3楼", "budget": 800.0, "openStartTime": "09:00:00",
             "openEndTime": "21:00:00", "status": 1}]}
        参数不合法时返回 {"ok": false, "reason": "...", "count": 0, "spaces": []}，
        **不抛异常**——请据 reason 修正参数后重试，或改问用户。
    """
    # ---- 参数校验：模型给的数字不保证合理，先挡一道 ----
    if capacity <= 0:
        return fail(
            f"capacity 必须为正整数，收到 {capacity}。请按用户口述的实际人数重传。",
            count=0, spaces=[],
        )
    if space_type not in SPACE_TYPE_LABELS:
        return fail(
            f"space_type 必须是 1~4 之一（1会议室 2展厅 3多功能厅 4户外场地），"
            f"收到 {space_type}。",
            count=0, spaces=[],
        )

    start_dt = parse_time(start_time)
    end_dt = parse_time(end_time)
    if start_dt is None or end_dt is None:
        return fail(
            f"时间格式无法解析：start_time={start_time!r}、end_time={end_time!r}，"
            "期望 YYYY-MM-DD HH:mm:ss。",
            count=0, spaces=[],
        )
    if end_dt <= start_dt:
        return fail(
            f"结束时间({end_time})不晚于开始时间({start_time})，时段倒置。请修正后重试。",
            count=0, spaces=[],
        )

    # ---- 经 service 层查询：Tool 不直接碰库（主文档 3.4 / 7.4 / 9.3）----
    result = await _query_spaces_service(
        capacity=capacity,
        space_type=space_type,
        start_time=start_time,
        end_time=end_time,
    )
    return {
        "ok": True,
        "count": result.get("count", 0),
        "spaces": result.get("spaces", []),
        "spaceTypeLabel": SPACE_TYPE_LABELS[space_type],
    }
