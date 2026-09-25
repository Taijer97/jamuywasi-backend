from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.core.database import get_db
from app.models.all_models import Order, Store, User
from app.schemas.all_schemas import OrderCreate, OrderOut
from app.core.deps import get_required_user
from app.core.websocket_manager import ws_manager
from app.core.notifications import notify, store_owner_ids
from app.core.rate_limit import rate_limit
from app.core.order_pricing import effective_unit_price, is_combination_available
from app.models.all_models import Product
import re
import secrets

router = APIRouter(prefix="/orders", tags=["Pedidos WhatsApp"])

VALID_ORDER_STATUSES = {"pending_whatsapp", "confirmed", "preparing", "delivered", "cancelled"}
ORDER_NUMBER_RE = re.compile(r"^PED-[A-Z0-9]{4,12}$")


async def _unique_order_number(db: AsyncSession, requested: Optional[str]) -> str:
    """Usa el número que ya vio el cliente en WhatsApp si es válido y libre; si no, genera uno único."""
    candidate = (requested or "").strip().upper()
    for _ in range(10):
        if candidate and ORDER_NUMBER_RE.match(candidate):
            taken = (await db.execute(select(Order.id).where(Order.order_number == candidate))).first()
            if not taken:
                return candidate
        candidate = "PED-" + secrets.token_hex(3).upper()
    raise HTTPException(status_code=500, detail="No se pudo generar el número de pedido.")

@router.post("", response_model=OrderOut, dependencies=[Depends(rate_limit("orders", 20, 600))])
async def create_order(data: OrderCreate, db: AsyncSession = Depends(get_db)):
    # Verify store exists
    s_stmt = select(Store).where(Store.id == data.store_id)
    store = (await db.execute(s_stmt)).scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")

    if not store.is_active:
        raise HTTPException(status_code=400, detail="Esta tienda no está recibiendo pedidos en este momento.")

    delivery_type = data.delivery_type if data.delivery_type in ("delivery", "pickup") else "delivery"

    # --- Recalcular precios en el servidor ---
    product_ids = {str(it.get("productId") or it.get("product_id") or "") for it in data.items}
    res = await db.execute(select(Product).where(Product.id.in_(product_ids), Product.store_id == store.id))
    products = {p.id: p for p in res.scalars().all()}

    clean_items = []
    subtotal = 0.0
    for it in data.items:
        pid = str(it.get("productId") or it.get("product_id") or "")
        product = products.get(pid)
        if not product:
            raise HTTPException(status_code=400, detail="Uno de los productos ya no está disponible en esta tienda.")
        try:
            qty = int(it.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty < 1 or qty > 999:
            raise HTTPException(status_code=400, detail=f"Cantidad no válida para {product.name}.")
        selected = it.get("selectedVariants") or {}
        if not isinstance(selected, dict):
            selected = {}
        selected = {str(k)[:100]: str(v)[:100] for k, v in selected.items()}
        if not product.in_stock or not is_combination_available(product, selected):
            raise HTTPException(status_code=400, detail=f"{product.name} está agotado.")
        unit = round(effective_unit_price(product, selected), 2)
        line = round(unit * qty, 2)
        subtotal += line
        clean_items.append({
            "productId": product.id,
            "productName": product.name,
            "price": unit,
            "quantity": qty,
            "selectedVariants": selected,
            "subtotal": line,
            "imageUrl": product.image_url,
        })

    subtotal = round(subtotal, 2)
    threshold = store.free_delivery_threshold or 0
    is_free = delivery_type == "pickup" or subtotal >= threshold
    delivery_fee = 0.0 if is_free else round(float(store.delivery_fee or 0), 2)
    total = round(subtotal + delivery_fee, 2)

    notes = (data.notes or "").strip()
    if abs(float(data.total or 0) - total) > 0.01:
        notes = (notes + "\n" if notes else "") + (
            f"[Aviso del sistema: el cliente vio un total de {float(data.total or 0):.2f} "
            f"pero el total real con los precios actuales es {total:.2f}. Confírmalo antes de cobrar.]"
        )

    order_num = await _unique_order_number(db, data.order_number)

    new_order = Order(
        order_number=order_num,
        store_id=data.store_id,
        customer_name=data.customer_name,
        customer_dni=data.customer_dni,
        customer_phone=data.customer_phone,
        customer_address=data.customer_address or "",
        notes=notes,
        delivery_type=delivery_type,
        payment_method=data.payment_method,
        items=clean_items,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        total=total,
        status="pending_whatsapp",
        whatsapp_message_sent=data.whatsapp_message_sent or "",
    )
    db.add(new_order)
    await db.commit()
    await db.refresh(new_order)
    out = OrderOut.from_orm(new_order)
    await ws_manager.broadcast({
        "type": "ORDER_CREATED",
        "data": out.dict()
    })
    # Notificación para el/los dueños de la tienda
    symbol = store.currency_symbol or "S/"
    owners = await store_owner_ids(db, store.id)
    units = sum(int(i["quantity"]) for i in clean_items)
    await notify(owners, "ORDER_NEW", f"Nuevo pedido {new_order.order_number}",
                 f"{new_order.customer_name} · {symbol} {new_order.total:.2f} · {units} {'unidad' if units == 1 else 'unidades'}",
                 {"view": "merchant", "tab": "orders", "targetId": new_order.id}, store.id)
    return new_order

@router.get("", response_model=List[OrderOut])
async def list_all_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user)
):
    if current_user.role == "superadmin":
        stmt = select(Order).order_by(desc(Order.created_at))
    else:
        stmt = (
            select(Order)
            .join(Store, Order.store_id == Store.id)
            .where((Store.owner_id == current_user.id) | (Order.store_id == current_user.store_id))
            .order_by(desc(Order.created_at))
        )
    orders = (await db.execute(stmt)).scalars().all()
    return orders

@router.get("/store/{store_id}", response_model=List[OrderOut])
async def list_store_orders(
    store_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user)
):
    stmt_st = select(Store).where(Store.id == store_id)
    target_st = (await db.execute(stmt_st)).scalar_one_or_none()
    if current_user.role != "superadmin" and current_user.store_id != store_id and (not target_st or target_st.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="No tienes permisos para ver pedidos de esta tienda.")

    stmt = select(Order).where(Order.store_id == store_id).order_by(desc(Order.created_at))
    orders = (await db.execute(stmt)).scalars().all()
    return orders

@router.patch("/{order_id}/status")
async def update_order_status(
    order_id: str,
    status: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user)
):
    stmt = select(Order).where(Order.id == order_id)
    if status not in VALID_ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="Estado de pedido no válido.")

    order = (await db.execute(stmt)).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    stmt_st = select(Store).where(Store.id == order.store_id)
    target_st = (await db.execute(stmt_st)).scalar_one_or_none()
    if current_user.role != "superadmin" and current_user.store_id != order.store_id and (not target_st or target_st.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="No puedes modificar pedidos de otra tienda.")

    order_store_id = order.store_id
    order.status = status
    await db.commit()
    await ws_manager.broadcast({
        "type": "ORDER_UPDATED",
        "data": {"id": order_id, "store_id": order_store_id, "status": status}
    })
    return {"status": "ok", "order_id": order_id, "new_status": status}
