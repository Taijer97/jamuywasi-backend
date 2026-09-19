from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.cache import catalog_cache
from app.models.all_models import PromotionalBanner, User
from app.schemas.all_schemas import (
    PromotionalBannerOut,
    PromotionalBannerCreate,
    PromotionalBannerUpdate
)
from app.core.deps import get_superadmin_user
from app.core.websocket_manager import ws_manager

router = APIRouter(prefix="/banners", tags=["Banners de Propaganda"])

@router.get("", response_model=List[PromotionalBannerOut])
async def list_active_banners(db: AsyncSession = Depends(get_db)):
    """Lista todos los banners activos ordenados para el carrusel de Inicio con caché en memoria"""
    cache_key = "banners:active"
    cached = catalog_cache.get(cache_key)
    if cached is not None:
        return cached

    stmt = select(PromotionalBanner).where(PromotionalBanner.is_active == True).order_by(PromotionalBanner.order.asc())
    banners = (await db.execute(stmt)).scalars().all()
    catalog_cache.set(cache_key, banners, ttl_seconds=60)
    return banners

@router.get("/all", response_model=List[PromotionalBannerOut])
async def list_all_banners_admin(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_superadmin_user)
):
    stmt = select(PromotionalBanner).order_by(PromotionalBanner.order.asc())
    banners = (await db.execute(stmt)).scalars().all()
    return banners

@router.post("", response_model=PromotionalBannerOut)
async def create_banner(
    data: PromotionalBannerCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_superadmin_user)
):
    new_banner = PromotionalBanner(**data.dict())
    db.add(new_banner)
    await db.commit()
    await db.refresh(new_banner)
    catalog_cache.invalidate("banners:")
    out = PromotionalBannerOut.from_orm(new_banner)
    await ws_manager.broadcast({
        "type": "BANNER_CREATED",
        "data": out.dict()
    })
    return new_banner

@router.put("/{banner_id}", response_model=PromotionalBannerOut)
async def update_banner(
    banner_id: str,
    data: PromotionalBannerUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_superadmin_user)
):
    stmt = select(PromotionalBanner).where(PromotionalBanner.id == banner_id)
    banner = (await db.execute(stmt)).scalar_one_or_none()
    if not banner:
        raise HTTPException(status_code=404, detail="Banner no encontrado")

    for field, value in data.dict(exclude_unset=True).items():
        setattr(banner, field, value)

    await db.commit()
    await db.refresh(banner)
    catalog_cache.invalidate("banners:")
    out = PromotionalBannerOut.from_orm(banner)
    await ws_manager.broadcast({
        "type": "BANNER_UPDATED",
        "data": out.dict()
    })
    return banner

@router.delete("/{banner_id}")
async def delete_banner(
    banner_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_superadmin_user)
):
    stmt = select(PromotionalBanner).where(PromotionalBanner.id == banner_id)
    banner = (await db.execute(stmt)).scalar_one_or_none()
    if not banner:
        raise HTTPException(status_code=404, detail="Banner no encontrado")

    await db.delete(banner)
    await db.commit()
    catalog_cache.invalidate("banners:")
    await ws_manager.broadcast({
        "type": "BANNER_DELETED",
        "data": {"id": banner_id}
    })
    return {"status": "ok", "message": "Banner eliminado"}
