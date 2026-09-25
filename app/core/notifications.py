"""Notificaciones internas (campanita) para comerciantes y superadmins.

- Se guardan en la tabla `notifications` (una fila por destinatario, con leído/no leído).
- Se envían al instante por WebSocket SOLO a sus destinatarios (evento NOTIFICATION_NEW).
- Un proceso en segundo plano revisa cada hora los planes por vencer (3 días antes) y vencidos.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.core.websocket_manager import ws_manager
from app.models.all_models import Notification, User, Store

logger = logging.getLogger("jamuywasi.notifications")

EXPIRING_DAYS = 3            # aviso "tu plan vence en 3 días"
CHECK_EVERY_SECONDS = 3600   # revisión de vencimientos cada hora


def _iso_utc(dt) -> Optional[str]:
    """MySQL/SQLite devuelven fechas sin zona; se guardan en UTC, así que se marca explícitamente."""
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def serialize(n: Notification) -> dict:
    return {
        "id": n.id,
        "type": n.type,
        "title": n.title,
        "message": n.message or "",
        "link": n.link or {},
        "store_id": n.store_id,
        "is_read": bool(n.is_read),
        "created_at": _iso_utc(n.created_at),
    }


async def superadmin_ids(db) -> List[str]:
    res = await db.execute(select(User.id).where(User.role == "superadmin", User.status != "suspended"))
    return [r[0] for r in res.all()]


async def store_owner_ids(db, store_id: str) -> List[str]:
    store = await db.get(Store, store_id)
    ids = set()
    if store and store.owner_id:
        ids.add(store.owner_id)
    res = await db.execute(select(User.id).where(User.store_id == store_id, User.role == "merchant"))
    ids.update(r[0] for r in res.all())
    return list(ids)


async def notify(
    user_ids: Iterable[str],
    type: str,
    title: str,
    message: str = "",
    link: Optional[dict] = None,
    store_id: Optional[str] = None,
    dedupe_key: Optional[str] = None,
    to_superadmins: bool = False,
) -> int:
    """Crea la notificación para cada destinatario y la envía por WebSocket.
    Usa su propia sesión de BD: nunca rompe la operación principal (pedido, registro, pago)."""
    try:
        async with AsyncSessionLocal() as db:
            ids = set(u for u in user_ids if u)
            if to_superadmins:
                ids.update(await superadmin_ids(db))
            created: List[Notification] = []
            for uid in ids:
                if dedupe_key:
                    exists = (await db.execute(
                        select(Notification.id).where(Notification.user_id == uid, Notification.dedupe_key == dedupe_key)
                    )).first()
                    if exists:
                        continue
                n = Notification(user_id=uid, type=type, title=title[:160], message=(message or "")[:400],
                                 link=link or {}, store_id=store_id, dedupe_key=dedupe_key)
                db.add(n)
                created.append(n)
            if not created:
                return 0
            try:
                await db.commit()
            except IntegrityError:  # otro proceso creó el mismo recordatorio a la vez
                await db.rollback()
                return 0
            for n in created:
                await ws_manager.send_to_users([n.user_id], {"type": "NOTIFICATION_NEW", "data": serialize(n)})
            return len(created)
    except Exception as e:  # una notificación fallida jamás debe romper la acción del usuario
        logger.warning("No se pudo crear la notificación %s: %s", type, e)
        return 0


async def check_subscriptions_once() -> None:
    """Planes que vencen en <= 3 días y planes vencidos (una sola vez por período)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(User).where(
            User.role == "merchant",
            User.subscription_period_end.isnot(None),
            User.status != "pending_approval",
            or_(User.subscription_status.is_(None), User.subscription_status.notin_(["canceled", "pending_approval"])),
        ))
        merchants = res.scalars().all()

    for m in merchants:
        end = m.subscription_period_end
        if end.tzinfo is not None:
            end = end.astimezone(timezone.utc).replace(tzinfo=None)
        end_label = end.strftime("%d/%m/%Y")
        period = end.strftime("%Y%m%d")
        link = {"view": "merchant", "tab": "subscription"}
        if now < end <= now + timedelta(days=EXPIRING_DAYS):
            days = max(1, round((end - now).total_seconds() / 86400))
            await notify([m.id], "PLAN_EXPIRING",
                         f"Tu plan vence en {days} día{'s' if days != 1 else ''}",
                         f"Renueva antes del {end_label} para que tu tienda siga publicada y recibiendo pedidos.",
                         link, m.store_id, dedupe_key=f"plan_expiring:{period}")
        elif end <= now:
            await notify([m.id], "PLAN_EXPIRED", "Tu plan venció",
                         f"Tu plan venció el {end_label}. Tu tienda dejó de mostrarse al público hasta que renueves.",
                         link, m.store_id, dedupe_key=f"plan_expired:{period}")
            await notify([], "MERCHANT_PLAN_EXPIRED", f"Plan vencido: {m.name}",
                         f"El plan de {m.name} venció el {end_label}. Su tienda ya no es visible.",
                         {"view": "superadmin", "adminTab": "users", "targetId": m.id}, m.store_id,
                         dedupe_key=f"merchant_expired:{m.id}:{period}", to_superadmins=True)


async def subscription_watcher() -> None:
    """Tarea en segundo plano (se inicia con la API)."""
    await asyncio.sleep(20)  # dejar arrancar la app
    while True:
        try:
            # Con varios procesos del backend, solo uno hace la revisión en cada vuelta
            from app.core import redis_bus
            if await redis_bus.acquire_lock("subscription_watcher", CHECK_EVERY_SECONDS - 60):
                await check_subscriptions_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Revisión de vencimientos falló: %s", e)
        await asyncio.sleep(CHECK_EVERY_SECONDS)
