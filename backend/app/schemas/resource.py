"""
模块 5：资源与设备管理 —— 写接口的请求模型

命名约定（§6.2）：API 传输字段一律 camelCase，因此这里**直接用 camelCase** 作字段名
（理由同 `schemas/image.py`：不做 alias 转换，代码即文档）。

⚠️ **为什么字段名与 `frontend/src/views/Resources.vue` 原来发的不一样**
------------------------------------------------------------------
前端最初是照 `app/api/v1/mock_data.py` 的 `SPACES` 写的，发的是
`{name, type:"会议室", capacity, location, status}` —— 那是 **Mock 的字段名与类型**
（`name` 而非 `spaceName`、`type` 给中文字符串而非整数）。

真实表 `space_resource` 的字段是 `space_name` / `space_type`(整数 1~4) / `capacity` / …，
且**规范名以真实接口为准**（也是 `docs/api.md` 的口径）。因此这里按真实字段建模，
并发请求体由前端同步改成规范名 —— 与 `frontend/src/utils/normalize.js` 的读侧保持一致。
"""

from datetime import time as dt_time

from pydantic import BaseModel, Field

__all__ = ["SpaceCreate", "DeviceUpdate"]


class SpaceCreate(BaseModel):
    """`POST /api/v1/resources/spaces` 请求体。"""

    spaceName: str = Field(..., min_length=1, max_length=128, description="场地名称")
    spaceType: int = Field(
        ..., ge=1, le=4, description="场地类型：1 会议室 / 2 展厅 / 3 多功能厅 / 4 户外场地"
    )
    capacity: int = Field(..., ge=1, le=100000, description="容纳人数")
    location: str | None = Field(None, max_length=255, description="位置")
    #: 预算。可空 —— 表上 `budget` 就是 nullable，设备不计费，很多场地不填。
    budget: float | None = Field(None, ge=0, description="预算")
    #: 开放时段。省略时落 NULL，看板的分母会按 `OPEN_HOURS_FALLBACK`（14h）兜底 ——
    #: 这是既有口径（见 dashboard_service._open_hours），不是这里的特例。
    openStartTime: dt_time | None = Field(None, description="开放起始时间 HH:MM:SS")
    openEndTime: dt_time | None = Field(None, description="开放结束时间 HH:MM:SS")
    status: int = Field(1, ge=0, le=1, description="可用状态：1 可用 / 0 停用")


class DeviceUpdate(BaseModel):
    """`PUT /api/v1/resources/devices/{deviceId}` 请求体。

    只开放**状态**一项：界面上的操作就是「改设备状态」。
    总量/可用数属于台账口径（`available_count` 是静态上限，见
    `docs/spec/done/README.md` 附录的 available_count 口径），不从这里改。
    """

    deviceStatus: int = Field(..., ge=1, le=3, description="设备状态：1 完好 / 2 损坏 / 3 缺失配件")

