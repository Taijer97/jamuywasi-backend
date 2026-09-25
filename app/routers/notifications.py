from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_required_user
from app.core.notifications import serialize
from app.models.all_models import Notification, User

router = APIRouter(prefix="/notifications", tags=["Notificaciones"])


@router.get("")
async def list_notifications(
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_required_user),
):
    res = await db.execute(
        select(Notification).where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc()).limit(limit)
    )
    unread = (await db.execute(
        select(func.count(Notification.id)).where(Notification.user_id == user.id, Notification.is_read == False)  # noqa: E712
    )).scalar() or 0
    return {"items": [serialize(n) for n in res.scalars().all()], "unread": unread}


@router.post("/{notification_id}/read")
async def mark_read(notification_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_required_user)):
    n = await db.get(Notification, notification_id)
    if not n or n.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notificación no encontrada")
    if not n.is_read:
        n.is_read = True
        n.read_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.commit()
    return {"ok": True}


@router.post("/read-all")
async def mark_all_read(db: AsyncSession = Depends(get_db), user: User = Depends(get_required_user)):
    await db.execute(
        update(Notification).where(Notification.user_id == user.id, Notification.is_read == False)  # noqa: E712
        .values(is_read=True, read_at=datetime.now(timezone.utc).replace(tzinfo=None))
    )
    await db.commit()
    return {"ok": True}
