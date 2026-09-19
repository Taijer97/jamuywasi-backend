from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, or_, and_, desc, asc
from app.core.database import get_db
from app.core.cache import catalog_cache
from app.models.all_models import Product, Store, User
from app.schemas.all_schemas import ProductOut, ProductCreate, ProductUpdate
from app.core.deps import get_required_user
from app.core.websocket_manager import ws_manager

router = APIRouter(prefix="/products", tags=["Productos & Catálogo"])

@router.get("", response_model=List[ProductOut])
async def list_products(
    search: Optional[str] = None,
    store_ids: Optional[List[str]] = Query(None),
    category: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    only_in_stock: bool = False,
    only_on_sale: bool = False,
    sort_by: str = Query("views", pattern="^(views|price_asc|price_desc|recent)$"),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """Catálogo multitienda con soporte de búsqueda, filtros avanzados y ordenamiento con caché en memoria"""
    is_default_query = not search and not store_ids and not category and min_price is None and max_price is None and not only_in_stock and not only_on_sale and offset == 0
    cache_key = f"products:default:{sort_by}:{limit}" if is_default_query else None

    if cache_key:
        cached = catalog_cache.get(cache_key)
        if cached is not None:
            return cached

    stmt = select(Product, Store.name.label("store_name"), Store.logo.label("store_logo"))\
        .join(Store, Store.id == Product.store_id)\
        .where(Store.is_active == True)

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
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

    if search and search.strip():
        term = search.strip()[:60].lower()
        s = f"%{term}%"
        stmt = stmt.where(
            or_(
                Product.name.ilike(s),
                Product.description.ilike(s),
                Product.category.ilike(s),
            )
        )

    if store_ids:
        stmt = stmt.where(Product.store_id.in_(store_ids))

    if category and category != "all":
        stmt = stmt.where(Product.category == category)

    if min_price is not None:
        stmt = stmt.where(Product.price >= min_price)

    if max_price is not None:
        stmt = stmt.where(Product.price <= max_price)

    if only_in_stock:
        stmt = stmt.where(Product.in_stock == True)

    if only_on_sale:
        stmt = stmt.where(
            and_(
                Product.compare_at_price.is_not(None),
                Product.compare_at_price > Product.price
            )
        )

    # Sorting
    if sort_by == "views":
        stmt = stmt.order_by(desc(Product.views_count))
    elif sort_by == "price_asc":
        stmt = stmt.order_by(asc(Product.price))
    elif sort_by == "price_desc":
        stmt = stmt.order_by(desc(Product.price))
    elif sort_by == "recent":
        stmt = stmt.order_by(desc(Product.created_at))

    stmt = stmt.offset(offset).limit(limit)
    res = await db.execute(stmt)

    products_out = []
    for prod, s_name, s_logo in res.all():
        p_dict = {c.name: getattr(prod, c.name) for c in prod.__table__.columns}
        p_dict["store_name"] = s_name
        p_dict["store_logo"] = s_logo
        products_out.append(ProductOut(**p_dict))

    if cache_key:
        catalog_cache.set(cache_key, products_out, ttl_seconds=30)

    return products_out

@router.get("/my-products", response_model=List[ProductOut])
async def get_my_products(
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db)
):
    """Devuelve todos los productos de las tiendas del comerciante autenticado, sin importar el estado de suscripción."""
    stmt_stores = select(Store.id).where(or_(Store.owner_id == current_user.id, Store.id == current_user.store_id))
    user_store_ids = (await db.execute(stmt_stores)).scalars().all()
    if not user_store_ids:
        return []

    stmt = select(Product, Store.name.label("store_name"), Store.logo.label("store_logo"))\
        .join(Store, Store.id == Product.store_id)\
        .where(Product.store_id.in_(user_store_ids))\
        .order_by(desc(Product.created_at))
    
    res = await db.execute(stmt)
    products_out = []
    for prod, s_name, s_logo in res.all():
        p_dict = {c.name: getattr(prod, c.name) for c in prod.__table__.columns}
        p_dict["store_name"] = s_name
        p_dict["store_logo"] = s_logo
        products_out.append(ProductOut(**p_dict))
    return products_out

@router.get("/{product_id}", response_model=ProductOut)
async def get_product(product_id: str, db: AsyncSession = Depends(get_db)):
    stmt = select(Product, Store.name.label("store_name"), Store.logo.label("store_logo"))\
        .join(Store, Store.id == Product.store_id)\
        .where(Product.id == product_id)
    res = (await db.execute(stmt)).first()
    if not res:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    prod, s_name, s_logo = res
    p_dict = {c.name: getattr(prod, c.name) for c in prod.__table__.columns}
    p_dict["store_name"] = s_name
    p_dict["store_logo"] = s_logo
    return ProductOut(**p_dict)

@router.post("/{product_id}/visit")
async def track_product_visit(product_id: str, db: AsyncSession = Depends(get_db)):
    """Incrementa atómicamente las visitas de un producto sin bloqueo de fila"""
    stmt = (
        update(Product)
        .where(Product.id == product_id)
        .values(views_count=func.coalesce(Product.views_count, 0) + 1)
    )
    result = await db.execute(stmt)
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    await db.commit()
    return {"status": "ok"}

@router.post("", response_model=ProductOut)
async def create_product(
    data: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user)
):
    # Verify store existence and ownership
    stmt_st = select(Store).where(Store.id == data.store_id)
    target_st = (await db.execute(stmt_st)).scalar_one_or_none()
    if not target_st:
        raise HTTPException(status_code=404, detail="Tienda no encontrada.")
    if current_user.role != "superadmin" and current_user.store_id != data.store_id and target_st.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="No puedes crear productos en otra tienda.")

    slug = (data.slug or data.name).lower().strip().replace(" ", "-")
    new_product = Product(
        store_id=data.store_id,
        name=data.name,
        slug=slug,
        description=data.description or "",
        price=data.price,
        compare_at_price=data.compare_at_price,
        category=data.category or "General",
        image_url=data.image_url,
        additional_images=data.additional_images or [],
        sku=data.sku,
        in_stock=data.in_stock,
        stock_count=data.stock_count,
        is_featured=data.is_featured,
        variants=data.variants or [],
        combinations=data.combinations or [],
    )
    db.add(new_product)
    await db.commit()
    await db.refresh(new_product)

    stmt = select(Store.name, Store.logo).where(Store.id == new_product.store_id)
    s_res = (await db.execute(stmt)).first()
    s_name = s_res[0] if s_res else ""
    s_logo = s_res[1] if s_res else ""

    p_dict = {c.name: getattr(new_product, c.name) for c in new_product.__table__.columns}
    p_dict["store_name"] = s_name
    p_dict["store_logo"] = s_logo
    catalog_cache.invalidate()
    out = ProductOut(**p_dict)
    await ws_manager.broadcast({
        "type": "PRODUCT_CREATED",
        "data": out.dict()
    })
    return out

@router.put("/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: str,
    data: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user)
):
    stmt = select(Product).where(Product.id == product_id)
    product = (await db.execute(stmt)).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    stmt_st = select(Store).where(Store.id == product.store_id)
    target_st = (await db.execute(stmt_st)).scalar_one_or_none()
    if current_user.role != "superadmin" and current_user.store_id != product.store_id and (not target_st or target_st.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="No puedes modificar productos de otra tienda.")

    update_data = data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(product, field, value)

    await db.commit()
    await db.refresh(product)

    stmt = select(Store.name, Store.logo).where(Store.id == product.store_id)
    s_res = (await db.execute(stmt)).first()
    s_name = s_res[0] if s_res else ""
    s_logo = s_res[1] if s_res else ""

    p_dict = {c.name: getattr(product, c.name) for c in product.__table__.columns}
    p_dict["store_name"] = s_name
    p_dict["store_logo"] = s_logo
    catalog_cache.invalidate()
    out = ProductOut(**p_dict)
    await ws_manager.broadcast({
        "type": "PRODUCT_UPDATED",
        "data": out.dict()
    })
    return out

@router.delete("/{product_id}")
async def delete_product(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user)
):
    stmt = select(Product).where(Product.id == product_id)
    product = (await db.execute(stmt)).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    stmt_st = select(Store).where(Store.id == product.store_id)
    target_st = (await db.execute(stmt_st)).scalar_one_or_none()
    if current_user.role != "superadmin" and current_user.store_id != product.store_id and (not target_st or target_st.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="No tienes permisos para eliminar este producto.")

    prod_store_id = product.store_id
    await db.delete(product)
    await db.commit()
    catalog_cache.invalidate()
    await ws_manager.broadcast({
        "type": "PRODUCT_DELETED",
        "data": {"id": product_id, "store_id": prod_store_id}
    })
    return {"status": "ok", "message": "Producto eliminado"}
