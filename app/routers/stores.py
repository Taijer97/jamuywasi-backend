import json
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from app.core.utc_json import mark_utc
from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, delete
from app.core.database import get_db, AsyncSessionLocal
from app.core.cache import catalog_cache
from app.models.all_models import Store, Product, User, PromotionalBanner, Notification
from app.schemas.all_schemas import StoreOut, StoreCreate, StoreUpdate
from app.core.deps import get_required_user, get_superadmin_user, get_current_user
from app.core.websocket_manager import ws_manager

router = APIRouter(prefix="/stores", tags=["Tiendas"])

@router.get("", response_model=List[StoreOut])
async def list_stores(
    include_all: bool = False,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Lista tiendas:
    - Para SuperAdmin con include_all=True: devuelve todas las tiendas (para gestión y aprobación).
    - Para clientes públicos y usuarios normales: filtra estrictamente tiendas activas y aprobadas.
    - Las consultas públicas utilizan caché en memoria de 30 segundos para soportar alta concurrencia.
    """
    is_superadmin = current_user is not None and current_user.role == "superadmin"
    is_public = not (is_superadmin and include_all)
    
    if is_public:
        async def compute() -> bytes:
            # Sesión propia (puede terminar después de esta petición) y JSON ya armado:
            # las visitas siguientes no vuelven a convertir cientos de tiendas.
            async with AsyncSessionLocal() as own_db:
                items = await _query_stores(own_db, True)
            return json.dumps(mark_utc(jsonable_encoder(items)), ensure_ascii=False, separators=(",", ":")).encode()
        body = await catalog_cache.get_or_compute("stores:public_list", compute, 30)
        return Response(content=body, media_type="application/json")
    return await _query_stores(db, False)


async def _query_stores(db: AsyncSession, is_public: bool) -> List[StoreOut]:
    stmt = select(
        Store,
        func.count(Product.id).label("product_count")
    ).outerjoin(Product, (Product.store_id == Store.id) & (Product.in_stock == True))

    if is_public:
        # Excluir tiendas inactivas
        stmt = stmt.where(Store.is_active == True)
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        # Excluir tiendas cuyo comerciante esté pendiente de aprobación, suspendido, o vencido
        subq_unapproved = (
            select(User.store_id)
            .where(
                User.store_id.isnot(None),
                User.role == "merchant",
                or_(
                    User.status.in_(["pending_approval", "suspended"]),
                    User.subscription_status.in_(["past_due", "canceled", "pending_approval"]),
                    (User.subscription_period_end.isnot(None)) & (User.subscription_period_end < now_utc)
                )
            )
        )
        stmt = stmt.where(Store.id.not_in(subq_unapproved))

    stmt = stmt.group_by(Store.id).order_by(Store.created_at.desc())
    
    res = await db.execute(stmt)
    stores_out = []
    for store, count in res.all():
        store_dict = {c.name: getattr(store, c.name) for c in store.__table__.columns}
        store_dict["products_count"] = count or 0
        stores_out.append(StoreOut(**store_dict))

    return stores_out


PLAN_STORE_LIMITS = {
    "starter": 1,
    "pro": 2,
    "business": 3
}

@router.get("/my-stores", response_model=List[StoreOut])
async def get_my_stores(
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db)
):
    """Devuelve todas las tiendas que pertenecen al usuario autenticado."""
    stmt = (
        select(Store, func.count(Product.id).label("product_count"))
        .outerjoin(Product, (Product.store_id == Store.id) & (Product.in_stock == True))
        .where(or_(Store.owner_id == current_user.id, Store.id == current_user.store_id))
        .group_by(Store.id)
        .order_by(Store.created_at.asc())
    )
    res = await db.execute(stmt)
    stores_out = []
    for store, count in res.all():
        store_dict = {c.name: getattr(store, c.name) for c in store.__table__.columns}
        store_dict["products_count"] = count or 0
        stores_out.append(StoreOut(**store_dict))
    return stores_out

@router.post("", response_model=StoreOut, status_code=status.HTTP_201_CREATED)
async def create_store(
    data: StoreCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db)
):
    """Crea una nueva tienda para el usuario comerciante según los límites de su plan."""
    import re
    import time

    target_user = current_user
    if current_user.role == "superadmin" and data.owner_id:
        target_stmt = select(User).where(User.id == data.owner_id)
        found_target = (await db.execute(target_stmt)).scalars().first()
        if found_target:
            target_user = found_target

    count_stmt = select(func.count(Store.id)).where(or_(Store.owner_id == target_user.id, Store.id == target_user.store_id))
    current_count = (await db.execute(count_stmt)).scalar() or 0

    user_plan = target_user.subscription_plan or "starter"
    max_stores = PLAN_STORE_LIMITS.get(user_plan, 1)

    if current_user.role != "superadmin" and current_count >= max_stores:
        raise HTTPException(
            status_code=400,
            detail=f"Tu plan actual ({user_plan}) permite un máximo de {max_stores} tienda(s). Has alcanzado el límite. Actualiza a un plan superior para crear más tiendas."
        )

    store_name = data.name.strip()
    slug = data.slug.strip() if data.slug else re.sub(r"[^\w\s-]", "", store_name.lower()).strip().replace(" ", "-")
    
    slug_check = await db.execute(select(Store).where(Store.slug == slug))
    if slug_check.scalar_one_or_none():
        slug = f"{slug}-{int(time.time())}"

    store_data = data.dict(exclude_unset=True)
    store_data["name"] = store_name
    store_data["slug"] = slug
    store_data["owner_id"] = target_user.id

    is_active = (
        target_user.status == "active" and
        target_user.subscription_status not in ["past_due", "canceled", "pending_approval"]
    )
    store_data["is_active"] = is_active

    new_store = Store(**store_data)
    db.add(new_store)
    
    # Si el usuario no tenía store_id principal, asignárselo
    if not target_user.store_id or target_user.store_id == "all":
        target_user.store_id = new_store.id

    await db.commit()
    await db.refresh(new_store)
    catalog_cache.invalidate()

    store_dict = {c.name: getattr(new_store, c.name) for c in new_store.__table__.columns}
    store_dict["products_count"] = 0
    await ws_manager.broadcast({
        "type": "STORE_CREATED",
        "data": store_dict
    })
    return StoreOut(**store_dict)

@router.get("/{slug_or_id}", response_model=StoreOut)
async def get_store(
    slug_or_id: str,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Store).where((Store.id == slug_or_id) | (Store.slug == slug_or_id))
    store = (await db.execute(stmt)).scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    
    is_superadmin = current_user is not None and current_user.role == "superadmin"
    is_owner = current_user is not None and (current_user.store_id == store.id or store.owner_id == current_user.id)

    if not is_superadmin and not is_owner:
        if not store.is_active:
            raise HTTPException(status_code=404, detail="Tienda no disponible")
        
        # Validar vigencia de suscripción del comerciante dueño
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        user_stmt = select(User).where(User.store_id == store.id, User.role == "merchant")
        store_owner = (await db.execute(user_stmt)).scalars().first()
        if store_owner:
            period_end = store_owner.subscription_period_end
            if period_end and period_end.tzinfo is not None:
                period_end = period_end.astimezone(timezone.utc).replace(tzinfo=None)
            if (
                store_owner.status in ["pending_approval", "suspended"] or
                store_owner.subscription_status in ["past_due", "canceled", "pending_approval"] or
                (period_end and period_end < now_utc)
            ):
                raise HTTPException(status_code=404, detail="Tienda no disponible (Suscripción vencida o en proceso de activación)")

    count_stmt = select(func.count(Product.id)).where(Product.store_id == store.id, Product.in_stock == True)
    count = (await db.execute(count_stmt)).scalar() or 0
    
    store_dict = {c.name: getattr(store, c.name) for c in store.__table__.columns}
    store_dict["products_count"] = count
    return StoreOut(**store_dict)

@router.put("/{store_id}", response_model=StoreOut)
async def update_store_profile(
    store_id: str,
    data: StoreUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user)
):
    stmt = select(Store).where(Store.id == store_id)
    store = (await db.execute(stmt)).scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")

    if current_user.role != "superadmin" and current_user.store_id != store_id and store.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes permisos para modificar esta tienda.")

    update_data = data.dict(exclude_unset=True)
    # SEGURIDAD: solo el superadmin puede activar/desactivar tiendas o cambiar su dueño
    if current_user.role != "superadmin":
        update_data.pop("is_active", None)
        update_data.pop("owner_id", None)
    for field, value in update_data.items():
        setattr(store, field, value)

    await db.commit()
    await db.refresh(store)
    catalog_cache.invalidate()

    store_dict = {c.name: getattr(store, c.name) for c in store.__table__.columns}
    await ws_manager.broadcast({
        "type": "STORE_UPDATED",
        "data": store_dict
    })
    return store

@router.delete("/{store_id}")
async def delete_store(
    store_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_superadmin_user)
):
    """Permite al SuperAdmin eliminar una tienda y sus registros asociados."""
    stmt = select(Store).where(Store.id == store_id)
    store = (await db.execute(stmt)).scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")

    # Limpiar banners asociados a la tienda
    await db.execute(delete(PromotionalBanner).where(PromotionalBanner.store_id == store_id))
    # Limpiar notificaciones asociadas a la tienda
    await db.execute(delete(Notification).where(Notification.store_id == store_id))
    
    # Desvincular usuarios que tengan esta tienda asignada como su store_id
    user_stmt = select(User).where(User.store_id == store_id)
    linked_users = (await db.execute(user_stmt)).scalars().all()
    for u in linked_users:
        u.store_id = None

    await db.delete(store)
    await db.commit()
    catalog_cache.invalidate()

    await ws_manager.broadcast({
        "type": "STORE_DELETED",
        "data": {"id": store_id}
    })
    return {"message": "Tienda eliminada exitosamente"}
