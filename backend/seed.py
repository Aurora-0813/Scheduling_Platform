"""造演示数据：场地 / 设备 / 示例预约（字段对齐 §6.3）。"""
import asyncio
from datetime import datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select

from app import models  # noqa: F401  确保模型注册
from app.core.database import AsyncSessionLocal, Base, async_engine
from app.models import DeviceResource, ReserveOrder, SpaceResource


async def seed() -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        if (await db.execute(select(SpaceResource))).scalars().first() is None:
            db.add_all(
                [
                    SpaceResource(
                        space_name="会议室A",
                        space_type=1,
                        location="3F",
                        capacity=10,
                        budget=Decimal("0.00"),
                        open_start_time=time(8, 0),
                        open_end_time=time(22, 0),
                        status=1,
                    ),
                    SpaceResource(
                        space_name="报告厅",
                        space_type=2,
                        location="1F",
                        capacity=100,
                        budget=Decimal("500.00"),
                        open_start_time=time(8, 0),
                        open_end_time=time(22, 0),
                        status=1,
                    ),
                    SpaceResource(
                        space_name="研讨室B",
                        space_type=1,
                        location="4F",
                        capacity=6,
                        budget=Decimal("0.00"),
                        open_start_time=time(9, 0),
                        open_end_time=time(21, 0),
                        status=1,
                    ),
                ]
            )
        if (await db.execute(select(DeviceResource))).scalars().first() is None:
            db.add_all(
                [
                    DeviceResource(
                        device_name="投影仪",
                        device_type="投影",
                        device_status=1,
                        total_count=1,
                        available_count=1,
                    ),
                    DeviceResource(
                        device_name="音响系统",
                        device_type="音频",
                        device_status=1,
                        total_count=1,
                        available_count=1,
                    ),
                ]
            )
        await db.commit()

        if (await db.execute(select(ReserveOrder))).scalars().first() is None:
            now = datetime.now()
            demo = ReserveOrder(
                user_id=1,
                space_id=1,
                device_ids=[1],
                start_time=now + timedelta(days=2, hours=9),
                end_time=now + timedelta(days=2, hours=10),
                order_status=1,  # 待确认
                agent_request="",
                agent_trace=[],
            )
            db.add(demo)
            await db.commit()

        print("seed 完成：场地/设备/示例预约已就绪")


if __name__ == "__main__":
    asyncio.run(seed())
