from datetime import datetime, timezone, timedelta
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.config import settings
from app.core.cache import catalog_cache
from app.core.deps import get_required_user, get_superadmin_user
from app.core.websocket_manager import ws_manager
from app.core.rate_limit import rate_limit
from app.core.notifications import notify
from app.models.all_models import User, Store, PromoCode, SystemSetting, SubscriptionInvoice
from app.schemas.all_schemas import (
    YapeVerifyRequest,
    YapeVerifyResponse,
    YapePaymentConfigSchema,
    SubscriptionInvoiceOut
)

router = APIRouter(prefix="/payments", tags=["Pagos & Verificación Yape"])

PLAN_PRICING = {
    "starter": {"monthly": 10.0, "annual": 100.0},
    "pro": {"monthly": 25.0, "annual": 250.0},
    "business": {"monthly": 50.0, "annual": 500.0}
}

def calculate_renewal_period_end(current_end: Optional[datetime], days: int) -> tuple[datetime, int]:
    """
    Calcula la nueva fecha de fin de vigencia:
    - Si el usuario tiene vigencia activa en el futuro (current_end > now_utc),
      se respetan los días restantes y se suman los nuevos días (remaining_days + days).
    - Si la suscripción ya venció o no tiene fecha previa, inicia desde now_utc + days.
    Retorna (new_period_end, remaining_days_accumulated).
    """
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    remaining_days = 0
    if current_end is not None:
        curr = current_end.replace(tzinfo=None) if current_end.tzinfo else current_end
        if curr > now_utc:
            remaining_seconds = (curr - now_utc).total_seconds()
            remaining_days = max(1, int(round(remaining_seconds / 86400)))
            new_end = curr + timedelta(days=days)
            return new_end, remaining_days
    new_end = now_utc + timedelta(days=days)
    return new_end, 0

async def get_admin_whatsapp_display(db: AsyncSession) -> str:
    """Número de WhatsApp del SuperAdmin configurado en SuperAdmin > Cobros & QR Yape."""
    setting = (await db.execute(select(SystemSetting).where(SystemSetting.key == "yape_config"))).scalar_one_or_none()
    val = (setting.value if setting and setting.value else {}) or {}
    formatted = str(val.get("phone_formatted") or "").strip()
    if formatted:
        return formatted
    digits = "".join(ch for ch in str(val.get("phone") or "925763903") if ch.isdigit())
    wa = f"51{digits}" if len(digits) == 9 else digits
    return f"+{wa[:2]} {wa[2:5]} {wa[5:8]} {wa[8:]}" if len(wa) == 11 else f"+{wa}"


async def generate_invoice_number(db: AsyncSession) -> str:
    from sqlalchemy import func
    year = datetime.now(timezone.utc).year
    prefix = f"REC-{year}-"
    stmt = select(func.count(SubscriptionInvoice.id))
    total = (await db.execute(stmt)).scalar() or 0
    candidate = f"{prefix}{total + 1:05d}"
    exists = (await db.execute(select(SubscriptionInvoice).where(SubscriptionInvoice.invoice_number == candidate))).scalar_one_or_none()
    offset = 1
    while exists:
        candidate = f"{prefix}{total + 1 + offset:05d}"
        exists = (await db.execute(select(SubscriptionInvoice).where(SubscriptionInvoice.invoice_number == candidate))).scalar_one_or_none()
        offset += 1
    return candidate

@router.post("/verify-yape", response_model=YapeVerifyResponse, dependencies=[Depends(rate_limit("verify_yape", 10, 3600))])
async def verify_yape_payment(
    data: YapeVerifyRequest,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Verifica automáticamente una transferencia de Yape consultando la API externa con el monto y código de 3 dígitos.
    Controla un límite estricto de máximo 3 intentos.
    Al verificar con éxito (200), activa automáticamente la cuenta del comerciante y su tienda.
    Si el comerciante renueva o adquiere un nuevo plan antes de vencer, se respetan los días restantes y se suman a la nueva vigencia.
    """
    # 1. Comprobar si ya agotó los 3 intentos
    attempts = current_user.yape_verification_attempts or 0

    # 2. Calcular monto exacto según el plan y cupón si aplica
    plan_info = PLAN_PRICING.get(data.plan_id, PLAN_PRICING["starter"])
    base_amount = plan_info.get(data.billing_cycle, plan_info["monthly"])

    promo = None
    discount = 0.0
    if data.promo_code:
        clean_promo = data.promo_code.strip().upper()
        stmt = select(PromoCode).where(PromoCode.code == clean_promo)
        promo = (await db.execute(stmt)).scalar_one_or_none()
        if promo and promo.is_active:
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            is_valid_date = promo.valid_until is None or promo.valid_until >= now_utc
            is_valid_uses = promo.max_uses == 0 or promo.used_count < promo.max_uses
            promo_plan = promo.applicable_plan or "all"
            is_valid_plan = promo_plan in ["all", "", None, data.plan_id]

            if is_valid_date and is_valid_uses and is_valid_plan:
                if promo.discount_type == "percentage":
                    discount = round(base_amount * (promo.discount_value / 100.0), 2)
                else:
                    discount = round(min(promo.discount_value, base_amount), 2)

    final_amount = max(0.0, round(base_amount - discount, 2))
    # Formatear monto para la API de Yape (entero si no tiene decimales significativos o float)
    yape_amount = int(final_amount) if final_amount == int(final_amount) else final_amount

    # 3. Si el monto final es 0 (ej. cupón 100% de descuento o monto cubierto totalmente):
    # ¡ACCESO DIRECTO E INMEDIATO SIN VERIFICACIÓN DE PAGO NI PERMISOS!
    if final_amount <= 0:
        days = 365 if data.billing_cycle == "annual" else 30
        new_period_end, remaining_days = calculate_renewal_period_end(current_user.subscription_period_end, days)

        current_user.status = "active"
        current_user.subscription_status = "active"
        current_user.subscription_plan = data.plan_id
        current_user.subscription_period_end = new_period_end
        current_user.yape_verification_attempts = 0

        if current_user.store_id:
            store = await db.get(Store, current_user.store_id)
            if store:
                store.is_active = True
        # También activar cualquier tienda donde sea dueño
        res_owned = await db.execute(select(Store).where(Store.owner_id == current_user.id))
        for owned_st in res_owned.scalars().all():
            owned_st.is_active = True
            if not current_user.store_id:
                current_user.store_id = owned_st.id

        if promo:
            promo.used_count += 1

        plan_titles = {"starter": "Emprendedor", "pro": "Crecimiento Pro", "business": "Negocio Escala"}
        p_name = plan_titles.get(data.plan_id, data.plan_id.title())
        now_clean = datetime.now(timezone.utc).replace(tzinfo=None)

        inv_num = await generate_invoice_number(db)
        inv = SubscriptionInvoice(
            invoice_number=inv_num,
            user_id=current_user.id,
            store_id=current_user.store_id,
            plan_id=data.plan_id,
            plan_name=p_name,
            billing_cycle=data.billing_cycle,
            amount=0.0,
            currency="PEN",
            payment_method="Cupón Promocional" if promo else "Promoción Gratuita",
            reference=f"Cupón: {clean_promo}" if promo else "Acceso Gratuito 100%",
            status="paid",
            period_start=now_clean,
            period_end=new_period_end,
            created_at=now_clean
        )
        db.add(inv)

        await db.commit()
        catalog_cache.invalidate()

        await ws_manager.broadcast({
            "type": "PAYMENT_VERIFIED",
            "data": {
                "user_id": current_user.id,
                "store_id": current_user.store_id,
                "plan_id": data.plan_id,
                "status": "active",
                "subscription_period_end": current_user.subscription_period_end.isoformat() if current_user.subscription_period_end else None,
                "amount": 0.0,
                "invoice_number": inv.invoice_number,
                "user_name": current_user.name
            }
        })
        # Notificaciones: al comerciante (plan activo) y a los superadmins (pago recibido)
        _end = new_period_end.strftime("%d/%m/%Y")
        await notify([current_user.id], "PLAN_ACTIVATED", f"Plan {p_name} activo",
                     f"Tu plan está activo hasta el {_end}. Comprobante {inv.invoice_number}.",
                     {"view": "merchant", "tab": "subscription"}, current_user.store_id)
        await notify([], "PAYMENT_RECEIVED", f"Pago recibido: {current_user.name}",
                     f"Plan {p_name} · S/ {float(final_amount):.2f} · vigente hasta el {_end}.",
                     {"view": "superadmin", "adminTab": "users", "targetId": current_user.id},
                     current_user.store_id, to_superadmins=True)
        await ws_manager.broadcast({
            "type": "USER_UPDATED",
            "data": {
                "id": current_user.id,
                "status": "active",
                "subscription_status": "active",
                "subscription_plan": data.plan_id,
                "subscription_period_end": current_user.subscription_period_end.isoformat() if current_user.subscription_period_end else None,
            }
        })

        if remaining_days > 0:
            success_msg = (
                f"¡Acceso directo activado con éxito mediante tu código promocional! "
                f"Se sumaron {days} días a tus {remaining_days} día(s) restantes (vigencia total: {remaining_days + days} días). "
                f"Tu plan {p_name} está activo."
            )
        else:
            success_msg = f"¡Acceso directo concedido con éxito! Tu plan {p_name} y tu tienda están activos por {days} días."

        return YapeVerifyResponse(
            success=True,
            message=success_msg,
            activated=True,
            attempts=0,
            remaining_attempts=3,
            must_send_whatsapp=False,
            amount_paid=0.0,
            plan_id=data.plan_id,
            store_id=current_user.store_id,
            user_status="active",
            subscription_status="active",
            subscription_period_end=current_user.subscription_period_end
        )

    # 4. Si el monto final es mayor a 0, comprobar límite de intentos y código de Yape
    if attempts >= 3:
        return YapeVerifyResponse(
            success=False,
            message=f"Has alcanzado el límite máximo de 3 intentos automáticos. Por favor, envía tu comprobante directamente a nuestro WhatsApp ({await get_admin_whatsapp_display(db)}) para activación manual.",
            activated=False,
            attempts=attempts,
            remaining_attempts=0,
            must_send_whatsapp=True,
            plan_id=data.plan_id,
            store_id=current_user.store_id
        )

    clean_code = (data.codigo or "").strip()
    if not clean_code or len(clean_code) != 3 or not clean_code.isdigit():
        return YapeVerifyResponse(
            success=False,
            message="El código de confirmación de Yape debe tener exactamente 3 dígitos numéricos (ej. 895).",
            activated=False,
            attempts=attempts,
            remaining_attempts=max(0, 3 - attempts),
            must_send_whatsapp=False,
            plan_id=data.plan_id,
            store_id=current_user.store_id
        )

    # 4b. SEGURIDAD: un mismo pago de Yape (código + monto) solo puede activar UNA suscripción.
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    dup_stmt = select(SubscriptionInvoice.id).where(
        SubscriptionInvoice.payment_method == "Yape",
        SubscriptionInvoice.reference.like(f"Operación Yape: {clean_code}%"),
        SubscriptionInvoice.amount.between(float(final_amount) - 0.005, float(final_amount) + 0.005),
        SubscriptionInvoice.created_at >= since,
    ).limit(1)
    if (await db.execute(dup_stmt)).first():
        current_user.yape_verification_attempts = attempts + 1
        await db.commit()
        remaining = max(0, 3 - current_user.yape_verification_attempts)
        return YapeVerifyResponse(
            success=False,
            message="Este código de operación de Yape ya fue utilizado para activar otra suscripción. Si crees que es un error, envía tu comprobante por WhatsApp.",
            activated=False,
            attempts=current_user.yape_verification_attempts,
            remaining_attempts=remaining,
            must_send_whatsapp=remaining <= 0,
            amount_paid=float(final_amount),
            plan_id=data.plan_id,
            store_id=current_user.store_id
        )

    # 5. Llamar a la API externa de verificación de Yape
    yape_url = f"{settings.URL_YAPE_VERIFY}?api_token={settings.TOKEN_YAPE}"
    payload = {
        "monto": yape_amount,
        "codigo": clean_code,
        "tiempo_min": 15,
        "use_time_limit": True
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(yape_url, json=payload)
    except Exception as e:
        return YapeVerifyResponse(
            success=False,
            message=f"No se pudo conectar con el servicio de verificación de Yape ({str(e)}). Por favor intenta de nuevo o envía tu comprobante por WhatsApp.",
            activated=False,
            attempts=attempts,
            remaining_attempts=max(0, 3 - attempts),
            must_send_whatsapp=False,
            amount_paid=float(final_amount),
            plan_id=data.plan_id,
            store_id=current_user.store_id
        )

    # 6. Evaluar respuesta de la API externa
    if resp.status_code == 200:
        # ¡PAGO VERIFICADO EXITOSAMENTE!
        days = 365 if data.billing_cycle == "annual" else 30
        new_period_end, remaining_days = calculate_renewal_period_end(current_user.subscription_period_end, days)

        current_user.status = "active"
        current_user.subscription_status = "active"
        current_user.subscription_plan = data.plan_id
        current_user.subscription_period_end = new_period_end
        current_user.yape_verification_attempts = 0

        # Activar tienda del usuario
        if current_user.store_id:
            store = await db.get(Store, current_user.store_id)
            if store:
                store.is_active = True
        res_owned = await db.execute(select(Store).where(Store.owner_id == current_user.id))
        for owned_st in res_owned.scalars().all():
            owned_st.is_active = True
            if not current_user.store_id:
                current_user.store_id = owned_st.id

        # Incrementar uso del cupón si aplicó
        if promo:
            promo.used_count += 1

        plan_titles = {"starter": "Emprendedor", "pro": "Crecimiento Pro", "business": "Negocio Escala"}
        p_name = plan_titles.get(data.plan_id, data.plan_id.title())
        now_clean = datetime.now(timezone.utc).replace(tzinfo=None)

        inv_num = await generate_invoice_number(db)
        inv = SubscriptionInvoice(
            invoice_number=inv_num,
            user_id=current_user.id,
            store_id=current_user.store_id,
            plan_id=data.plan_id,
            plan_name=p_name,
            billing_cycle=data.billing_cycle,
            amount=float(final_amount),
            currency="PEN",
            payment_method="Yape",
            reference=f"Operación Yape: {clean_code}" + (f" (Cupón: {promo.code})" if promo else ""),
            status="paid",
            period_start=now_clean,
            period_end=new_period_end,
            created_at=now_clean
        )
        db.add(inv)

        await db.commit()
        catalog_cache.invalidate()

        await ws_manager.broadcast({
            "type": "PAYMENT_VERIFIED",
            "data": {
                "user_id": current_user.id,
                "store_id": current_user.store_id,
                "plan_id": data.plan_id,
                "status": "active",
                "subscription_period_end": current_user.subscription_period_end.isoformat() if current_user.subscription_period_end else None,
                "amount": float(final_amount),
                "invoice_number": inv.invoice_number,
                "user_name": current_user.name
            }
        })
        # Notificaciones: al comerciante (plan activo) y a los superadmins (pago recibido)
        _end = new_period_end.strftime("%d/%m/%Y")
        await notify([current_user.id], "PLAN_ACTIVATED", f"Plan {p_name} activo",
                     f"Tu plan está activo hasta el {_end}. Comprobante {inv.invoice_number}.",
                     {"view": "merchant", "tab": "subscription"}, current_user.store_id)
        await notify([], "PAYMENT_RECEIVED", f"Pago recibido: {current_user.name}",
                     f"Plan {p_name} · S/ {float(final_amount):.2f} · vigente hasta el {_end}.",
                     {"view": "superadmin", "adminTab": "users", "targetId": current_user.id},
                     current_user.store_id, to_superadmins=True)
        await ws_manager.broadcast({
            "type": "USER_UPDATED",
            "data": {
                "id": current_user.id,
                "status": "active",
                "subscription_status": "active",
                "subscription_plan": data.plan_id,
                "subscription_period_end": current_user.subscription_period_end.isoformat() if current_user.subscription_period_end else None,
            }
        })

        plan_titles = {"starter": "Emprendedor", "pro": "Crecimiento Pro", "business": "Negocio Escala"}
        p_name = plan_titles.get(data.plan_id, data.plan_id.title())

        if remaining_days > 0:
            success_msg = (
                f"¡Pago de S/ {final_amount:.2f} verificado con Yape! "
                f"Se respetaron tus {remaining_days} día(s) restante(s) y se sumaron {days} días (vigencia total: {remaining_days + days} días). "
                f"Tu plan {p_name} y tienda están activos."
            )
        else:
            success_msg = f"¡Pago de S/ {final_amount:.2f} verificado automáticamente con Yape! Tu plan {p_name} y tienda han sido activados por {days} días con éxito."

        return YapeVerifyResponse(
            success=True,
            message=success_msg,
            activated=True,
            attempts=0,
            remaining_attempts=3,
            must_send_whatsapp=False,
            amount_paid=float(final_amount),
            plan_id=data.plan_id,
            store_id=current_user.store_id,
            user_status="active",
            subscription_status="active",
            subscription_period_end=current_user.subscription_period_end
        )
    else:
        # Error o transacción no concordante: registrar intento fallido
        current_user.yape_verification_attempts = (current_user.yape_verification_attempts or 0) + 1
        await db.commit()

        err_detail = "Transacción no encontrada o datos no coincidentes."
        try:
            err_data = resp.json()
            err_detail = err_data.get("detail") or err_data.get("message") or err_detail
        except Exception:
            pass

        remaining = max(0, 3 - current_user.yape_verification_attempts)
        must_whatsapp = remaining <= 0
        if must_whatsapp:
            await notify([], "PAYMENT_MANUAL_REVIEW", f"Pago por revisar: {current_user.name}",
                         f"Agotó los 3 intentos de verificación Yape (S/ {final_amount:.2f}). Revisa su comprobante por WhatsApp.",
                         {"view": "superadmin", "adminTab": "users", "targetId": current_user.id},
                         current_user.store_id, to_superadmins=True)

        if must_whatsapp:
            user_msg = (
                f"{err_detail} Has agotado los 3 intentos permitidos. "
                f"Por favor, envía tu comprobante por WhatsApp a {await get_admin_whatsapp_display(db)} para que nuestro equipo active tu tienda de inmediato."
            )
        else:
            user_msg = (
                f"{err_detail} Asegúrate de haber yapeado exactamente S/ {final_amount:.2f} e ingresar el código de 3 dígitos de la confirmación. "
                f"Te quedan {remaining} intento(s)."
            )

        return YapeVerifyResponse(
            success=False,
            message=user_msg,
            activated=False,
            attempts=current_user.yape_verification_attempts,
            remaining_attempts=remaining,
            must_send_whatsapp=must_whatsapp,
            amount_paid=float(final_amount),
            plan_id=data.plan_id,
            store_id=current_user.store_id
        )

@router.get("/config", response_model=YapePaymentConfigSchema)
async def get_payment_config(db: AsyncSession = Depends(get_db)):
    """
    Retorna la configuración actual de Yape (teléfono, QR, titular, instrucciones).
    Disponible públicamente para que la vista de compras de planes cargue los datos actualizados.
    """
    stmt = select(SystemSetting).where(SystemSetting.key == "yape_config")
    setting = (await db.execute(stmt)).scalar_one_or_none()
    if setting and setting.value:
        val = setting.value
        return YapePaymentConfigSchema(
            phone=val.get("phone", "925763903"),
            phone_formatted=val.get("phone_formatted", "+51 925 763 903"),
            holder=val.get("holder", "JamuyWasi"),
            qr_url=val.get("qr_url", ""),
            instructions=val.get("instructions", "Abona el monto exacto por Yape o Plin. Luego ingresa el código de aprobación de 3 dígitos para verificación y activación inmediata de tu tienda."),
            updated_at=setting.updated_at
        )
    return YapePaymentConfigSchema()

@router.put("/config", response_model=YapePaymentConfigSchema)
async def update_payment_config(
    data: YapePaymentConfigSchema,
    current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Actualiza la configuración de Yape (teléfono, QR, titular, instrucciones).
    Acceso exclusivo para el SuperAdministrador.
    """
    stmt = select(SystemSetting).where(SystemSetting.key == "yape_config")
    setting = (await db.execute(stmt)).scalar_one_or_none()

    clean_data = {
        "phone": data.phone.strip(),
        "phone_formatted": data.phone_formatted.strip() or f"+51 {data.phone.strip()}",
        "holder": data.holder.strip(),
        "qr_url": (data.qr_url or "").strip(),
        "instructions": (data.instructions or "").strip()
    }

    now_utc = datetime.now(timezone.utc)
    if not setting:
        setting = SystemSetting(
            key="yape_config",
            value=clean_data,
            updated_at=now_utc
        )
        db.add(setting)
    else:
        setting.value = clean_data
        setting.updated_at = now_utc

    await db.commit()
    await db.refresh(setting)

    await ws_manager.broadcast({
        "type": "PAYMENT_CONFIG_UPDATED",
        "data": clean_data
    })

    return YapePaymentConfigSchema(
        phone=clean_data["phone"],
        phone_formatted=clean_data["phone_formatted"],
        holder=clean_data["holder"],
        qr_url=clean_data["qr_url"],
        instructions=clean_data["instructions"],
        updated_at=setting.updated_at
    )

@router.get("/my-invoices", response_model=list[SubscriptionInvoiceOut])
async def get_my_invoices(
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retorna el historial real de comprobantes de facturación de la tienda del usuario actual.
    Si no tiene comprobantes previos pero cuenta con suscripción activa, genera el comprobante inicial histórico.
    """
    stmt = (
        select(SubscriptionInvoice)
        .where(SubscriptionInvoice.user_id == current_user.id)
        .order_by(SubscriptionInvoice.created_at.desc())
    )
    res = await db.execute(stmt)
    invoices = list(res.scalars().all())

    # Obtener nombre de la tienda
    store_name = "Mi Tienda"
    if current_user.store_id:
        st = await db.get(Store, current_user.store_id)
        if st:
            store_name = st.name
    elif current_user.owned_stores:
        store_name = current_user.owned_stores[0].name

    # Backfill automático si no tiene ningún comprobante y cuenta con suscripción o tienda
    if not invoices and (current_user.subscription_status == "active" or current_user.store_id or current_user.role == "merchant"):
        plan_id = current_user.subscription_plan or "starter"
        plan_titles = {"starter": "Emprendedor", "pro": "Crecimiento Pro", "business": "Negocio Escala"}
        p_name = plan_titles.get(plan_id, plan_id.title())
        plan_info = PLAN_PRICING.get(plan_id, PLAN_PRICING["starter"])
        amount = plan_info.get("monthly", 10.0)

        now_clean = datetime.now(timezone.utc).replace(tzinfo=None)
        if current_user.subscription_period_end:
            p_end = current_user.subscription_period_end.replace(tzinfo=None) if current_user.subscription_period_end.tzinfo else current_user.subscription_period_end
        else:
            p_end = now_clean + timedelta(days=30)
            
        p_start = p_end - timedelta(days=30)
        if p_start > now_clean:
            p_start = now_clean

        inv_num = await generate_invoice_number(db)
        inv = SubscriptionInvoice(
            invoice_number=inv_num,
            user_id=current_user.id,
            store_id=current_user.store_id,
            plan_id=plan_id,
            plan_name=p_name,
            billing_cycle="monthly",
            amount=amount,
            currency="PEN",
            payment_method="Yape/Plin",
            reference="Activación Inicial de Tienda",
            status="paid",
            period_start=p_start,
            period_end=p_end,
            created_at=p_start
        )
        db.add(inv)
        await db.commit()
        await db.refresh(inv)
        invoices = [inv]

    result = []
    for inv in invoices:
        result.append(
            SubscriptionInvoiceOut(
                id=inv.id,
                invoice_number=inv.invoice_number,
                user_id=inv.user_id,
                store_id=inv.store_id,
                plan_id=inv.plan_id,
                plan_name=inv.plan_name,
                billing_cycle=inv.billing_cycle,
                amount=inv.amount,
                currency=inv.currency,
                payment_method=inv.payment_method,
                reference=inv.reference,
                status=inv.status,
                period_start=inv.period_start,
                period_end=inv.period_end,
                created_at=inv.created_at,
                store_name=store_name,
                customer_name=current_user.name,
                customer_dni=current_user.dni or "N/A"
            )
        )
    return result

@router.get("/invoices/{invoice_id}", response_model=SubscriptionInvoiceOut)
async def get_invoice_by_id(
    invoice_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retorna el detalle completo de un comprobante específico.
    """
    inv = await db.get(SubscriptionInvoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Comprobante no encontrado.")
    if inv.user_id != current_user.id and current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="No tienes permisos para ver este comprobante.")

    store_name = "Mi Tienda"
    if inv.store_id:
        st = await db.get(Store, inv.store_id)
        if st:
            store_name = st.name

    return SubscriptionInvoiceOut(
        id=inv.id,
        invoice_number=inv.invoice_number,
        user_id=inv.user_id,
        store_id=inv.store_id,
        plan_id=inv.plan_id,
        plan_name=inv.plan_name,
        billing_cycle=inv.billing_cycle,
        amount=inv.amount,
        currency=inv.currency,
        payment_method=inv.payment_method,
        reference=inv.reference,
        status=inv.status,
        period_start=inv.period_start,
        period_end=inv.period_end,
        created_at=inv.created_at,
        store_name=store_name,
        customer_name=current_user.name,
        customer_dni=current_user.dni or "N/A"
    )
