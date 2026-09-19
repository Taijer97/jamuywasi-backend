from typing import List
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.all_models import PromoCode, User
from app.core.websocket_manager import ws_manager
from app.core.rate_limit import rate_limit
from app.schemas.all_schemas import (
    PromoCodeCreate,
    PromoCodeOut,
    PromoCodeValidateRequest,
    PromoCodeValidateResponse,
)
from app.core.deps import get_superadmin_user

router = APIRouter(prefix="/promo-codes", tags=["Códigos Promocionales"])

@router.get("", response_model=List[PromoCodeOut])
async def list_promo_codes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_superadmin_user)
):
    """Lista todos los códigos promocionales creados (Solo SuperAdmin)."""
    stmt = select(PromoCode).order_by(PromoCode.created_at.desc())
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("", response_model=PromoCodeOut, status_code=status.HTTP_201_CREATED)
async def create_promo_code(
    data: PromoCodeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_superadmin_user)
):
    """Crea un nuevo código promocional (Solo SuperAdmin)."""
    clean_code = data.code.strip().upper()
    if not clean_code:
        raise HTTPException(status_code=400, detail="El código no puede estar vacío.")

    # Verificar si ya existe
    existing = await db.execute(select(PromoCode).where(PromoCode.code == clean_code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"El código '{clean_code}' ya existe.")

    if data.discount_type not in ["percentage", "fixed"]:
        raise HTTPException(status_code=400, detail="El tipo de descuento debe ser 'percentage' o 'fixed'.")

    if data.discount_value <= 0:
        raise HTTPException(status_code=400, detail="El valor del descuento debe ser mayor a 0.")

    if data.discount_type == "percentage" and data.discount_value > 100:
        raise HTTPException(status_code=400, detail="El porcentaje de descuento no puede ser superior al 100%.")

    new_promo = PromoCode(
        code=clean_code,
        discount_type=data.discount_type,
        discount_value=round(data.discount_value, 2),
        max_uses=max(0, data.max_uses),
        is_active=data.is_active,
        valid_until=data.valid_until,
        applicable_plan=data.applicable_plan or "all",
    )
    db.add(new_promo)
    await db.commit()
    await db.refresh(new_promo)

    promo_dict = {c.name: getattr(new_promo, c.name) for c in new_promo.__table__.columns}
    await ws_manager.broadcast({
        "type": "PROMO_CODE_CREATED",
        "data": promo_dict
    })
    return new_promo

@router.patch("/{promo_id}/toggle", response_model=PromoCodeOut)
async def toggle_promo_code(
    promo_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_superadmin_user)
):
    """Activa o desactiva un código promocional (Solo SuperAdmin)."""
    promo = await db.get(PromoCode, promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Código promocional no encontrado.")

    promo.is_active = not promo.is_active
    await db.commit()
    await db.refresh(promo)

    promo_dict = {c.name: getattr(promo, c.name) for c in promo.__table__.columns}
    await ws_manager.broadcast({
        "type": "PROMO_CODE_UPDATED",
        "data": promo_dict
    })
    return promo

@router.delete("/{promo_id}")
async def delete_promo_code(
    promo_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_superadmin_user)
):
    """Elimina permanentemente un código promocional (Solo SuperAdmin)."""
    promo = await db.get(PromoCode, promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Código promocional no encontrado.")

    await db.delete(promo)
    await db.commit()

    await ws_manager.broadcast({
        "type": "PROMO_CODE_DELETED",
        "data": {"id": promo_id}
    })
    return {"message": "Código promocional eliminado correctamente."}

@router.post("/validate", response_model=PromoCodeValidateResponse, dependencies=[Depends(rate_limit("promo_validate", 20, 600))])
async def validate_promo_code(
    data: PromoCodeValidateRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Valida un código promocional aplicado por un comercio y calcula el descuento y precio final.
    Endpoint público disponible durante el registro o pago de suscripción.
    """
    clean_code = data.code.strip().upper()
    if not clean_code:
        return PromoCodeValidateResponse(
            valid=False,
            message="Ingresa un código promocional.",
            discount_amount=0.0,
            final_amount=data.base_amount
        )

    stmt = select(PromoCode).where(PromoCode.code == clean_code)
    promo = (await db.execute(stmt)).scalar_one_or_none()

    if not promo:
        return PromoCodeValidateResponse(
            valid=False,
            message=f"El cupón '{clean_code}' no existe.",
            discount_amount=0.0,
            final_amount=data.base_amount
        )

    if not promo.is_active:
        return PromoCodeValidateResponse(
            valid=False,
            message=f"El cupón '{clean_code}' no se encuentra activo actualmente.",
            discount_amount=0.0,
            final_amount=data.base_amount
        )

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    if promo.valid_until:
        valid_until = promo.valid_until
        if valid_until.tzinfo is not None:
            valid_until = valid_until.astimezone(timezone.utc).replace(tzinfo=None)
        if valid_until < now_utc:
            return PromoCodeValidateResponse(
                valid=False,
                message=f"El cupón '{clean_code}' ha vencido.",
                discount_amount=0.0,
                final_amount=data.base_amount
            )

    if promo.max_uses > 0 and promo.used_count >= promo.max_uses:
        return PromoCodeValidateResponse(
            valid=False,
            message=f"El cupón '{clean_code}' ha alcanzado el límite máximo de canjes permitidos.",
            discount_amount=0.0,
            final_amount=data.base_amount,
            applicable_plan=promo.applicable_plan or "all"
        )

    # Validar que el cupón aplique al plan seleccionado
    plan_titles = {"starter": "Emprendedor", "pro": "Crecimiento Pro", "business": "Negocio Escala"}
    promo_plan = promo.applicable_plan or "all"
    if promo_plan != "all" and promo_plan != data.plan_id:
        expected_name = plan_titles.get(promo_plan, promo_plan.title())
        return PromoCodeValidateResponse(
            valid=False,
            message=f"El cupón '{clean_code}' solo es válido para el Plan {expected_name}.",
            discount_amount=0.0,
            final_amount=data.base_amount,
            applicable_plan=promo_plan
        )

    # Calcular monto del descuento evitando cualquier monto negativo
    base = max(0.0, float(data.base_amount))
    if promo.discount_type == "percentage":
        discount = round(base * (promo.discount_value / 100.0), 2)
    else: # fixed
        discount = round(min(promo.discount_value, base), 2)

    final = max(0.0, round(base - discount, 2))

    return PromoCodeValidateResponse(
        valid=True,
        message=f"¡Cupón '{promo.code}' aplicado con éxito!",
        code=promo.code,
        discount_type=promo.discount_type,
        discount_value=promo.discount_value,
        discount_amount=discount,
        final_amount=final,
        applicable_plan=promo_plan
    )
