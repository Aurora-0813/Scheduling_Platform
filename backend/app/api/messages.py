"""消息通知：未读数 / 列表 / 单条已读 / 全部已读 / 日程提醒扫描。

- GET /api/v1/messages/unread 为契约接口；其余为模块内补充（通知接收）。
"""
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.exceptions import MessageNotFoundError
from ..core.response import ok
from ..core.utils import format_time
from ..models import NotifyMessage
from ..services.message_service import reminder_scan
from .deps import CurrentUser, get_current_user

router = APIRouter(prefix="/messages", tags=["messages"])


def _message_out(m: NotifyMessage) -> dict:
    return {
        "messageId": m.id,
        "receiverId": m.receiver_id,
        "notifyType": m.notify_type,
        "orderId": m.order_id,
        "title": m.title or "",
        "content": m.content or "",
        "isRead": bool(m.is_read),
        "createTime": format_time(m.create_time),
    }


@router.get("/unread")
async def unread_count(
    current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(func.count())
        .select_from(NotifyMessage)
        .where(NotifyMessage.receiver_id == current.id, NotifyMessage.is_read == 0)
    )
    count = result.scalar() or 0
    return ok({"count": count})


@router.get("")
async def list_messages(
    skip: int = 0,
    limit: int = 20,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    limit = max(1, min(limit, 100))  # 分页上限，防超大 limit 拉全表
    skip = max(0, skip)
    result = await db.execute(
        select(NotifyMessage)
        .where(NotifyMessage.receiver_id == current.id)
        .order_by(NotifyMessage.create_time.desc())
        .offset(skip)
        .limit(limit)
    )
    msgs = result.scalars().all()
    return ok([_message_out(m) for m in msgs])


@router.put("/{messageId}/read")
async def read_message(
    messageId: int,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    msg = await db.get(NotifyMessage, messageId)
    if not msg or msg.receiver_id != current.id:
        # 不存在与非本人同一处理：区分了就等于承认「这条存在，只是不是你的」，
        # 可据此枚举全库消息。与 orders.py::_get_owned_order 同口径（§5.1）。
        # 用业务异常而不是 HTTPException：后者的 detail 会被统一异常处理器的
        # 通用文案覆盖掉（404 -> 「接口或资源不存在」），原因就丢了。
        raise MessageNotFoundError("通知不存在")
    msg.is_read = 1
    await db.commit()
    await db.refresh(msg)
    return ok(_message_out(msg), "已标记为已读")


@router.put("/read-all")
async def read_all(
    current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await db.execute(
        update(NotifyMessage)
        .where(NotifyMessage.receiver_id == current.id, NotifyMessage.is_read == 0)
        .values(is_read=1)
    )
    await db.commit()
    return ok(None, "已全部标记为已读")


@router.post("/remind")
async def remind(
    background_tasks: BackgroundTasks,
    remind_hours: int = 1,
    db: AsyncSession = Depends(get_db),
):
    """触发一次日程提醒扫描（演示/定时任务入口）。"""
    count = await reminder_scan(db, background_tasks, remind_hours)
    return ok({"reminders": count})
