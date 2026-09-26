"""消息生成 + 落库 + WebSocket 推送（模块3：通知接收与日程提醒）。

推送采用「尽力而为」策略：落库与推送分离，推送失败不影响落库，用户可列表补看。
"""
from datetime import datetime, timedelta

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.utils import format_time
from ..models import NotifyMessage, ReserveOrder
from ..state_machine import OrderStatus
from ..websocket import manager


async def create_message(
    db: AsyncSession,
    receiver_id: int,
    title: str,
    content: str,
    notify_type: int = 1,  # 1预约提醒 2变更致歉 3故障告警（§6.3）
    order_id: int | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> NotifyMessage:
    """写 notify_message 表，并通过后台任务向目标用户实时推送。"""
    msg = NotifyMessage(
        receiver_id=receiver_id,
        notify_type=notify_type,
        order_id=order_id,
        title=title,
        content=content,
        is_read=0,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    if background_tasks is not None:
        payload = {
            "messageId": msg.id,
            "receiverId": msg.receiver_id,
            "notifyType": msg.notify_type,
            "orderId": msg.order_id,
            "title": msg.title,
            "content": msg.content,
            "isRead": False,
            "createTime": format_time(msg.create_time),
        }
        background_tasks.add_task(manager.send_to_user, receiver_id, payload)

    return msg


async def reminder_scan(
    db: AsyncSession,
    background_tasks: BackgroundTasks | None = None,
    within_hours: int = 1,
) -> int:
    """扫描即将开始的「已确认」预约，生成日程提醒。"""
    now = datetime.now()
    window_end = now + timedelta(hours=within_hours)
    result = await db.execute(
        select(ReserveOrder).where(
            ReserveOrder.order_status == OrderStatus.CONFIRMED.value,
            ReserveOrder.start_time >= now,
            ReserveOrder.start_time <= window_end,
        )
    )
    upcoming = result.scalars().all()
    for o in upcoming:
        await create_message(
            db,
            o.user_id,
            "日程提醒",
            f"您的预约 #{o.id} 即将开始",
            notify_type=1,
            order_id=o.id,
            background_tasks=background_tasks,
        )
    return len(upcoming)
