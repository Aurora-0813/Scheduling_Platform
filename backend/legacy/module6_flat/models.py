from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from database import Base
from datetime import datetime

# 设备表
class Device(Base):
    __tablename__ = "device"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    location = Column(String(100))
    status = Column(String(20), default="正常") # 正常/故障/维修中
    stock_num = Column(Integer, default=1)
    create_time = Column(DateTime, default=datetime.now)

# 巡检记录表
class InspectionRecord(Base):
    __tablename__ = "inspection_record"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer)
    img_path = Column(String(255)) # 上传图片保存路径
    ai_result = Column(Text) # AI识别返回的结果
    report_content = Column(Text) # 巡检报告
    is_abnormal = Column(Boolean, default=False) # 是否异常
    create_time = Column(DateTime, default=datetime.now)

# 维修工单表
class RepairOrder(Base):
    __tablename__ = "repair_order"
    id = Column(Integer, primary_key=True, index=True)
    inspection_id = Column(Integer)
    device_id = Column(Integer)
    order_content = Column(Text)
    status = Column(String(20), default="待维修") # 待维修/维修中/已完成
    create_time = Column(DateTime, default=datetime.now)