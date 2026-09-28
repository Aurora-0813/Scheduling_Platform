from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ==================== 设备 ====================
class DeviceCreate(BaseModel):
    """新增设备时前端传的字段"""
    # min_length=1：Field(...) 只保证"必须有这个字段"，空字符串照样能通过，
    # 补上长度下限才能挡住 name=""
    name: str = Field(..., min_length=1, description="设备名称", max_length=100)
    location: Optional[str] = Field(None, description="设备位置", max_length=100)
    # 用 Literal 收死枚举范围，status 乱填会在入参校验阶段就被 422 拦下
    status: Literal["正常", "故障", "维修中"] = Field("正常", description="状态：正常/故障/维修中")
    stock_num: int = Field(1, description="库存数量", ge=0)


class DeviceUpdate(BaseModel):
    """修改设备：字段全部可选，只传要改的字段"""
    name: Optional[str] = Field(None, min_length=1, description="设备名称", max_length=100)
    location: Optional[str] = Field(None, description="设备位置", max_length=100)
    status: Optional[Literal["正常", "故障", "维修中"]] = Field(None, description="状态：正常/故障/维修中")
    stock_num: Optional[int] = Field(None, description="库存数量", ge=0)


class Device(BaseModel):
    """返回给前端的设备数据"""
    id: int
    name: str
    location: Optional[str] = None
    status: Optional[str] = None
    stock_num: Optional[int] = None
    create_time: Optional[datetime] = None

    # SQLAlchemy对象不是dict，必须开这个才能直接转成模型
    model_config = ConfigDict(from_attributes=True)


# ==================== 巡检记录 ====================
class InspectionRecord(BaseModel):
    """返回给前端的巡检记录数据"""
    id: int
    device_id: Optional[int] = None
    img_path: Optional[str] = Field(None, description="图片访问路径，如 /static/xxx.jpg")
    ai_result: Optional[str] = Field(None, description="AI识别结果")
    report_content: Optional[str] = Field(None, description="巡检报告")
    is_abnormal: Optional[bool] = Field(False, description="是否异常")
    create_time: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==================== AI 识别 ====================
class InspectionAnalysisRequest(BaseModel):
    """AI识别入参"""
    record_id: int = Field(..., description="巡检记录ID", ge=1)


class InspectionAnalysisResult(BaseModel):
    """AI识别结果"""
    record_id: int
    device_id: Optional[int] = None
    is_abnormal: bool = Field(..., description="是否异常")
    ai_result: str = Field(..., description="AI对图片的识别结果")
    report_content: str = Field(..., description="生成的巡检报告")
    # 判定为异常时自动生成的维修工单ID；未判定异常时为 null
    repair_order_id: Optional[int] = Field(None, description="自动生成的维修工单ID，无则为null")


# ==================== 维修工单 ====================
class RepairOrderCreate(BaseModel):
    """手动创建工单时前端传的字段"""
    inspection_id: Optional[int] = Field(None, description="关联的巡检记录ID", ge=1)
    device_id: Optional[int] = Field(None, description="关联的设备ID", ge=1)
    order_content: str = Field(..., min_length=1, description="工单内容", max_length=2000)
    status: Literal["待维修", "维修中", "已完成"] = Field("待维修", description="工单状态")


class RepairOrderUpdate(BaseModel):
    """修改工单：目前只允许改状态"""
    status: Literal["待维修", "维修中", "已完成"] = Field(..., description="工单状态")


class RepairOrder(BaseModel):
    """返回给前端的工单数据"""
    id: int
    inspection_id: Optional[int] = None
    device_id: Optional[int] = None
    order_content: Optional[str] = None
    status: Optional[str] = None
    create_time: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
