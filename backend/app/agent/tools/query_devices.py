"""Tool 2/5：`query_devices` —— 按类型检索**可借用**的设备。

对应主文档 5.3 模块 4 冻结签名：
    async def query_devices(device_type: str) -> dict

## 本文件最重要的一行是过滤，不是查询

阶段 4 §3.2：**只返回 `device_status=1` 且 `available_count>0` 的设备**。
这层过滤是**后端责任，不能下放给 Prompt**——「模型不该有机会看到不可用设备」。

它同时是主文档十三风险表第一条（「大模型幻觉，编造不存在的场地设备」）的技术兜底：
若把 `device_status=2`（损坏）的设备返回给模型，模型**有可能**把它排进方案，
而 Prompt 只能降低概率、不能保证；在 Tool 层滤掉则是确定性的。

⚠️ 过滤**有意放在 Tool 层而非 service 层**：阶段 3 的 `device_service.query_devices` 桩
故意返回该类型的全部设备，就是为了让 `AGENT-U-02` 有独立见证者可断言
（种子数据里 id=13 无人机02 是 `deviceStatus=2`、id=15 直播设备02 是 `availableCount=0`）。
若把过滤下沉到 service，那个用例会变成假绿——结果里永远不会有坏设备，
分不清是 Tool 真的在滤，还是数据本来就没有。
"""
from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.tools._common import fail
from app.services import query_devices as _query_devices_service

__all__ = ["query_devices", "QueryDevicesArgs"]

#: 可借用状态。`device_status` 字典见主文档 6.3 表 5：1完好 2损坏 3缺失配件。
DEVICE_STATUS_OK = 1

#: 设备类型中文名，与 `device_resource.device_type` 的存储值一致
#: （种子数据 `docs/seed.sql`：投影仪 / 音响 / 显示屏 / 无人机 / 直播设备）。
#: 写进描述里是为了让模型传**数据库里的原词**，而不是「LED屏」「音箱」这类同义词。
KNOWN_DEVICE_TYPES = ("投影仪", "音响", "显示屏", "无人机", "直播设备")


class QueryDevicesArgs(BaseModel):
    """`query_devices` 的入参 schema。"""

    device_type: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description=(
            "设备类型中文名，须与库中取值一致：投影仪 / 音响 / 显示屏 / 无人机 / 直播设备。"
            "不要传「LED屏」「音箱」这类同义词。"
        ),
    )


@tool("query_devices", args_schema=QueryDevicesArgs)
async def query_devices(device_type: str) -> dict:
    """按类型查询**当前可借用**的设备（已剔除损坏与零库存的）。

    什么时候用：需求里提到具体设备（投影、音响、显示屏、无人机、直播设备）时调用。
    返回结果里没有的设备就是**当前借不到**，请改用替代类型（例如投影仪借不到时可查「显示屏」），
    不要把结果外的 ID 写进方案。

    Args:
        device_type: 设备类型中文名，取值须为：投影仪 / 音响 / 显示屏 / 无人机 / 直播设备。

    Returns:
        {"ok": true, "count": 3, "devices": [
            {"id": 1, "deviceName": "投影仪01", "deviceType": "投影仪",
             "deviceStatus": 1, "totalCount": 1, "availableCount": 1}]}
        参数不合法时返回 {"ok": false, "reason": "...", "count": 0, "devices": []}。
        返回的 `devices` **已保证** `deviceStatus=1` 且 `availableCount>0`，可直接选用。
    """
    if not device_type or not str(device_type).strip():
        return fail("device_type 不能为空。请传入设备类型中文名。", count=0, devices=[])

    device_type = str(device_type).strip()

    result = await _query_devices_service(device_type=device_type)

    # ---- 可用性过滤：本条是阶段 4 的完成判定之一，改动前先看本文件顶部说明 ----
    devices = [
        d for d in result.get("devices", [])
        if d.get("deviceStatus") == DEVICE_STATUS_OK and (d.get("availableCount") or 0) > 0
    ]

    if not devices:
        # 区分「类型名不存在」与「存在但全不可借」——模型与用户的下一步动作不同：
        # 前者该换词重查，后者该换类型或改期。返回同一个空洞会让模型无从选择。
        raw_total = result.get("count", 0)
        if raw_total > 0:
            return fail(
                f"「{device_type}」共 {raw_total} 台，但当前**没有一台可借用**"
                "（损坏或库存为 0）。建议改用替代设备类型，或与用户确认是否接受替代。",
                count=0, devices=[],
            )
        return fail(
            f"未找到类型为「{device_type}」的设备。可用的类型为："
            f"{'、'.join(KNOWN_DEVICE_TYPES)}。请用库中原文重新查询。",
            count=0, devices=[],
        )

    return {"ok": True, "count": len(devices), "devices": devices}
