from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_superadmin_user
from app.core.view_dedup import register_view
from app.models.all_models import Store, User, VisitStat

router = APIRouter(prefix="/analytics", tags=["Analíticas"])


async def _increment_visit(db: AsyncSession, scope: str, store_id: Optional[str]) -> None:
    today = datetime.now(timezone.utc).date()
    conditions = [VisitStat.day == today, VisitStat.scope == scope]
    conditions.append(VisitStat.store_id.is_(None) if store_id is None else VisitStat.store_id == store_id)
    row = (await db.execute(select(VisitStat).where(*conditions))).scalar_one_or_none()
    if row:
        row.visits = (row.visits or 0) + 1
    else:
        db.add(VisitStat(day=today, scope=scope, store_id=store_id, visits=1))
    try:
        await db.commit()
    except IntegrityError:
        # Carrera muy improbable (un solo worker por convención del proyecto): otro request
        # ya creó la fila de hoy; se reintenta como actualización.
        await db.rollback()
        row = (await db.execute(select(VisitStat).where(*conditions))).scalar_one_or_none()
        if row:
            row.visits = (row.visits or 0) + 1
            await db.commit()


@router.post("/landing-visit")
async def track_landing_visit(request: Request, db: AsyncSession = Depends(get_db)):
    """Registra una visita a la página principal de la plataforma (antes de elegir tienda)."""
    is_new = await register_view(request, "landing")
    if is_new:
        await _increment_visit(db, "landing", None)
    return {"status": "ok", "counted": is_new}


@router.post("/store-visit/{store_id}")
async def track_store_visit(store_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Registra una visita al catálogo público de una tienda."""
    is_new = await register_view(request, f"store:{store_id}")
    if is_new:
        await _increment_visit(db, "store", store_id)
    return {"status": "ok", "counted": is_new}


@router.get("/dashboard")
async def get_visits_dashboard(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_superadmin_user),
):
    """Panel de SuperAdmin: total y tendencia de visitas a la landing y a las tiendas."""
    today = datetime.now(timezone.utc).date()
    since = today - timedelta(days=max(1, days) - 1)

    landing_total = (await db.execute(
        select(func.coalesce(func.sum(VisitStat.visits), 0)).where(VisitStat.scope == "landing")
    )).scalar_one()
    store_total = (await db.execute(
        select(func.coalesce(func.sum(VisitStat.visits), 0)).where(VisitStat.scope == "store")
    )).scalar_one()

    landing_rows = (await db.execute(
        select(VisitStat.day, VisitStat.visits)
        .where(VisitStat.scope == "landing", VisitStat.day >= since)
        .order_by(VisitStat.day)
    )).all()
    store_rows = (await db.execute(
        select(VisitStat.day, func.sum(VisitStat.visits))
        .where(VisitStat.scope == "store", VisitStat.day >= since)
        .group_by(VisitStat.day)
        .order_by(VisitStat.day)
    )).all()

    top_rows = (await db.execute(
        select(VisitStat.store_id, Store.name, func.sum(VisitStat.visits).label("visits"))
        .join(Store, Store.id == VisitStat.store_id)
        .where(VisitStat.scope == "store")
        .group_by(VisitStat.store_id, Store.name)
        .order_by(func.sum(VisitStat.visits).desc())
        .limit(10)
    )).all()

    landing_today = next((v for d, v in landing_rows if d == today), 0)
    store_today = (await db.execute(
        select(func.coalesce(func.sum(VisitStat.visits), 0)).where(
            VisitStat.scope == "store", VisitStat.day == today
        )
    )).scalar_one()

    def _iso(d: date) -> str:
        return d.isoformat() if isinstance(d, date) else str(d)

    return {
        "landing": {
            "total": int(landing_total),
            "today": int(landing_today),
            "trend": [{"date": _iso(d), "visits": int(v)} for d, v in landing_rows],
        },
        "stores": {
            "total": int(store_total),
            "today": int(store_today),
            "trend": [{"date": _iso(d), "visits": int(v)} for d, v in store_rows],
            "topStores": [
                {"storeId": sid, "storeName": name, "visits": int(v)} for sid, name, v in top_rows
            ],
        },
    }
