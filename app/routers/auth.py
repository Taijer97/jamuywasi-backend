import urllib.parse
from typing import List, Dict, Any
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_access_token, password_needs_rehash
from app.models.all_models import User, Store, SystemSetting
from app.schemas.all_schemas import (
    UserLogin, UserRegister, TokenResponse, UserOut,
    UserProfileUpdate, UserAdminUpdate,
    ForgotPinRequest, ForgotPinResponse,
    AdminResetPinDefaultRequest, ChangePinRequest
)
from app.core.deps import get_required_user, get_superadmin_user
from app.core.websocket_manager import ws_manager
from app.core.rate_limit import rate_limit
from app.core.notifications import notify
from app.core.cache import catalog_cache
import re

router = APIRouter(prefix="/auth", tags=["Autenticación"])

def serialize_user_for_ws(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "dni": user.dni,
        "role": user.role,
        "store_id": user.store_id,
        "phone": user.phone,
        "personal_address": user.personal_address,
        "status": user.status,
        "subscription_plan": user.subscription_plan,
        "subscription_status": user.subscription_status or "active",
        "subscription_period_end": user.subscription_period_end.isoformat() if user.subscription_period_end else None,
        "failed_login_attempts": user.failed_login_attempts or 0,
        "pin_reset_requested": bool(user.pin_reset_requested),
        "pin_reset_requested_at": user.pin_reset_requested_at.isoformat() if user.pin_reset_requested_at else None,
        "must_change_pin": bool(user.must_change_pin),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }

def validate_pin_security(pin: str, dni: str = "", phone: str = "") -> None:
    """Valida que el PIN de 6 dígitos no sea fácil ni predecible"""
    pin = pin.strip()
    if not re.match(r"^\d{6}$", pin):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El PIN de seguridad debe contener exactamente 6 dígitos numéricos."
        )

    # 1. No todos los dígitos iguales (000000, 111111, etc.)
    if len(set(pin)) == 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PIN inseguro: No utilices números repetitivos (ej. 111111, 000000)."
        )

    # 2. No secuencias ascendentes o descendentes obvias
    sequences = ["012345", "123456", "234567", "345678", "456789", "543210", "654321", "765432", "876543", "987654"]
    if pin in sequences:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PIN inseguro: No utilices secuencias de números continuos (ej. 123456, 654321)."
        )

    # 3. No coincidencia con el DNI
    clean_dni = (dni or "").strip()
    if clean_dni:
        if pin in clean_dni or clean_dni.startswith(pin) or clean_dni.endswith(pin):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PIN inseguro: Por tu seguridad, el PIN no debe coincidir con partes de tu DNI."
            )

    # 4. No coincidencia con los últimos 6 dígitos del celular
    clean_phone = re.sub(r"\D", "", phone or "")
    if clean_phone and len(clean_phone) >= 6:
        if pin == clean_phone[-6:]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PIN inseguro: No utilices los últimos dígitos de tu número celular."
            )

@router.post("/register", response_model=TokenResponse, dependencies=[Depends(rate_limit("register", 5, 3600))])
async def register(data: UserRegister, db: AsyncSession = Depends(get_db)):
    clean_email = data.email.strip().lower()
    clean_dni = (data.dni or "").strip()
    clean_phone = (data.phone or "").strip()
    secret_key = (data.pin or data.password or "").strip()

    # SEGURIDAD: el rol nunca se acepta desde el cliente. Todo registro público es de comerciante.
    # Los superadmins solo se crean/promueven desde el panel de administración.
    data.role = "merchant"

    # Validar PIN de 6 dígitos si es un registro nuevo de merchant
    if data.role == "merchant":
        validate_pin_security(secret_key, dni=clean_dni, phone=clean_phone)

    # Verificar si el correo ya existe
    stmt_email = select(User).where(User.email == clean_email)
    if (await db.execute(stmt_email)).scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El correo electrónico ya se encuentra registrado."
        )

    # Verificar si el DNI ya existe (si fue provisto)
    if clean_dni:
        stmt_dni = select(User).where(User.dni == clean_dni)
        if (await db.execute(stmt_dni)).scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El número de DNI ya se encuentra registrado con otra cuenta."
            )

    store_id = None
    if data.role == "merchant":
        store_name = (data.store_name or f"Tienda de {data.name}").strip()
        slug = re.sub(r"[^\w\s-]", "", store_name.lower()).strip().replace(" ", "-")
        
        # Check slug collision
        slug_check = await db.execute(select(Store).where(Store.slug == slug))
        if slug_check.scalar_one_or_none():
            import time
            slug = f"{slug}-{int(time.time())}"

        # Dirección de la tienda según modalidad
        effective_store_address = (data.store_address or "").strip()
        if data.store_type == "virtual" and not effective_store_address:
            effective_store_address = "Venta por catálogo en línea (Delivery y envíos)"

        new_store = Store(
            name=store_name,
            slug=slug,
            ruc=(data.ruc or "").strip() or None,
            store_type=data.store_type or "virtual",
            category=data.category or "General",
            tagline=f"Catálogo digital de {store_name}",
            description=(data.about or f"Bienvenido a {store_name}.").strip(),
            logo="https://images.unsplash.com/photo-1472851294608-062f824d29cc?w=300&auto=format&fit=crop&q=80",
            banner="https://images.unsplash.com/photo-1441986300917-64674bd600d8?w=1400&auto=format&fit=crop&q=80",
            phone=(data.store_phone or clean_phone or "").strip(),
            store_email=(data.store_email or "").strip() or None,
            address=effective_store_address,
            is_active=False, # Requiere autorización obligatoria del superadmin
        )
        db.add(new_store)
        await db.flush()
        store_id = new_store.id

    new_user = User(
        name=data.name.strip(),
        email=clean_email,
        dni=clean_dni or None,
        hashed_password=hash_password(secret_key),
        role=data.role,
        store_id=store_id,
        phone=clean_phone or None,
        personal_address=(data.personal_address or "").strip() or None,
        status="pending_approval" if data.role == "merchant" else "active",
        subscription_plan=data.plan or "starter",
        subscription_status="pending_approval" if data.role == "merchant" else "active",
        subscription_period_end=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.add(new_user)
    await db.flush()
    if new_store:
        new_store.owner_id = new_user.id
    await db.commit()
    await db.refresh(new_user)

    user_payload = serialize_user_for_ws(new_user)
    await ws_manager.broadcast({
        "type": "USER_REGISTERED",
        "data": user_payload
    })
    if new_store:
        store_dict = {c.name: getattr(new_store, c.name) for c in new_store.__table__.columns}
        store_dict["products_count"] = 0
        await ws_manager.broadcast({
            "type": "STORE_CREATED",
            "data": store_dict
        })
        await notify([], "APPROVAL_PENDING", "Nueva tienda por aprobar",
                     f"{new_store.name} · {new_user.name} ({new_user.phone or new_user.email}) espera tu autorización.",
                     {"view": "superadmin", "adminTab": "users", "targetId": new_user.id}, new_store.id,
                     to_superadmins=True)

    token = create_access_token(subject=new_user.id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": new_user.id,
            "name": new_user.name,
            "email": new_user.email,
            "dni": new_user.dni,
            "role": new_user.role,
            "store_id": new_user.store_id,
            "phone": new_user.phone,
            "personal_address": new_user.personal_address,
            "status": new_user.status,
            "subscription_plan": new_user.subscription_plan,
            "subscription_status": new_user.subscription_status,
            "subscription_period_end": new_user.subscription_period_end.isoformat() if new_user.subscription_period_end else None,
        }
    }

@router.post("/login", response_model=TokenResponse, dependencies=[Depends(rate_limit("login", 10, 600))])
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    # Acepta identifier (DNI o Correo) o email por retrocompatibilidad
    target_identifier = (data.identifier or data.email or "").strip().lower()
    plain_pass = data.password.strip()

    if not target_identifier or not plain_pass:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Por favor ingresa tu DNI o Correo y tu PIN de seguridad."
        )

    # Buscar usuario por email o por DNI
    stmt = select(User).where(
        or_(
            User.email == target_identifier,
            User.dni == target_identifier
        )
    )
    user = (await db.execute(stmt)).scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="DNI/correo o PIN incorrecto."
        )

    # 1. Comprobar si ya agotó los 3 intentos permitidos
    attempts = user.failed_login_attempts or 0
    if attempts >= 3:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Has alcanzado el límite máximo de 3 intentos fallidos con tu PIN. Por seguridad tu acceso ha sido bloqueado. Utiliza la opción 'Olvidé mi PIN' para solicitar el restablecimiento al Administrador.",
                "code": "PIN_LOCKED",
                "remaining_attempts": 0,
                "locked": True,
                "user_name": user.name,
                "identifier": target_identifier
            }
        )

    # 2. Comprobar contraseña o PIN
    if not verify_password(plain_pass, user.hashed_password):
        user.failed_login_attempts = attempts + 1
        await db.commit()
        remaining = max(0, 3 - user.failed_login_attempts)
        if remaining == 0:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "message": "PIN incorrecto. Has alcanzado el límite máximo de 3 intentos permitidos. Tu acceso ha sido bloqueado. Utiliza la opción 'Olvidé mi PIN' para solicitar el restablecimiento.",
                    "code": "PIN_LOCKED",
                    "remaining_attempts": 0,
                    "locked": True,
                    "user_name": user.name,
                    "identifier": target_identifier
                }
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": f"PIN incorrecto. Te quedan {remaining} intento(s) antes del bloqueo de seguridad.",
                "code": "INVALID_PIN",
                "remaining_attempts": remaining,
                "locked": False,
                "identifier": target_identifier
            }
        )

    # 3. PIN correcto: reiniciar intentos fallidos
    user.failed_login_attempts = 0

    # Migración transparente de hashes antiguos (SHA-256) a Argon2
    if password_needs_rehash(user.hashed_password):
        user.hashed_password = hash_password(plain_pass)

    # Comprobar si debe cambiar el PIN (ej. ingresó con el reset '000000' o flag activo)
    if plain_pass == "000000" or user.must_change_pin:
        user.must_change_pin = True

    if user.status == "suspended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Su cuenta ha sido suspendida. Contacte al administrador."
        )

    # Auto-heal store_id and check subscription status for merchant
    if user.role == "merchant":
        needs_commit = False
        if not user.store_id:
            st_stmt = select(Store).where(Store.owner_id == user.id)
            st_res = (await db.execute(st_stmt)).scalars().first()
            if st_res:
                user.store_id = st_res.id
                needs_commit = True

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        sub_end = user.subscription_period_end
        if sub_end and sub_end.tzinfo is not None:
            sub_end = sub_end.astimezone(timezone.utc).replace(tzinfo=None)
        if sub_end and sub_end < now_utc and user.subscription_status not in ["pending_approval", "canceled"]:
            user.subscription_status = "past_due"
            needs_commit = True

        if needs_commit:
            await db.commit()
            await db.refresh(user)

    token = create_access_token(subject=user.id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "dni": user.dni,
            "role": user.role,
            "store_id": user.store_id,
            "phone": user.phone,
            "personal_address": user.personal_address,
            "status": user.status,
            "subscription_plan": user.subscription_plan,
            "subscription_status": user.subscription_status or "active",
            "subscription_period_end": user.subscription_period_end.isoformat() if user.subscription_period_end else None,
            "failed_login_attempts": user.failed_login_attempts or 0,
            "pin_reset_requested": bool(user.pin_reset_requested),
            "must_change_pin": bool(user.must_change_pin),
        }
    }

@router.post("/forgot-pin", response_model=ForgotPinResponse, dependencies=[Depends(rate_limit("forgot_pin", 5, 3600))])
async def request_forgot_pin(data: ForgotPinRequest, db: AsyncSession = Depends(get_db)):
    """
    Registra la solicitud de reseteo de PIN por parte del usuario y genera el mensaje de WhatsApp.
    """
    clean_id = data.identifier.strip().lower()
    stmt = select(User).where(or_(User.email == clean_id, User.dni == clean_id))
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontró ninguna cuenta asociada al DNI o correo ingresado."
        )

    user.pin_reset_requested = True
    user.pin_reset_requested_at = datetime.now(timezone.utc).replace(tzinfo=None)
    user.failed_login_attempts = 3
    await db.commit()

    # Resolver nombre de la tienda
    store_name = "Mi Tienda"
    if user.store_id:
        st = await db.get(Store, user.store_id)
        if st:
            store_name = st.name
    elif user.owned_stores:
        store_name = user.owned_stores[0].name

    # Obtener teléfono de soporte / superadmin
    setting_stmt = select(SystemSetting).where(SystemSetting.key == "yape_config")
    setting = (await db.execute(setting_stmt)).scalar_one_or_none()
    admin_phone = "925763903"
    if setting and setting.value and setting.value.get("phone"):
        admin_phone = str(setting.value["phone"]).strip().replace(" ", "").replace("+", "")

    wa_text = (
        f"Hola JamuyWasi, solicito restablecer el PIN de seguridad de mi cuenta:\n\n"
        f"👤 Titular: {user.name}\n"
        f"📄 DNI: {user.dni or 'No especificado'}\n"
        f"✉️ Correo: {user.email}\n"
        f"🏪 Tienda: {store_name}\n"
        f"⚠️ Motivo: Olvido de PIN / Bloqueo por 3 intentos fallidos."
        
    )
    clean_wa_phone = admin_phone if admin_phone.startswith("51") else f"51{admin_phone}"
    whatsapp_url = f"https://wa.me/{clean_wa_phone}?text={urllib.parse.quote(wa_text)}"

    await ws_manager.broadcast({
        "type": "PIN_RESET_REQUESTED",
        "data": {
            "user_id": user.id,
            "user_name": user.name,
            "identifier": user.dni or user.email,
            "store_name": store_name,
            "failed_attempts": user.failed_login_attempts or 3,
            "requested_at": user.pin_reset_requested_at.isoformat() if user.pin_reset_requested_at else None,
            "user": serialize_user_for_ws(user),
            "message": f"Solicitud de restablecimiento de PIN: {user.name} ({user.dni or user.email})"
        }
    })
    await notify([], "PIN_RESET_REQUESTED", "Solicitud para reiniciar PIN",
                 f"{user.name} ({user.dni or user.email}) · {store_name} no puede ingresar a su cuenta.",
                 {"view": "superadmin", "adminTab": "users", "targetId": user.id}, user.store_id,
                 to_superadmins=True)

    return ForgotPinResponse(
        success=True,
        message="Solicitud de restablecimiento registrada en el sistema. Puedes confirmar tu identidad por WhatsApp para atención inmediata.",
        user_name=user.name,
        user_dni=user.dni,
        store_name=store_name,
        admin_phone=admin_phone,
        whatsapp_url=whatsapp_url
    )

@router.post("/admin/reset-pin-default")
async def admin_reset_pin_default(
    data: AdminResetPinDefaultRequest,
    current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Permite al SuperAdministrador restablecer el PIN de un comerciante al valor por defecto 000000.
    Marca must_change_pin = True para exigir cambio obligatorio al ingresar.
    """
    user = await db.get(User, data.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado.")
    # Solo se restablece si el propio usuario lo pidió ("Olvidé mi PIN" o 3 intentos fallidos)
    if not user.pin_reset_requested:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este usuario no ha solicitado restablecer su PIN. Pídele que use \"¿Olvidaste tu PIN?\" en el inicio de sesión.",
        )

    user.hashed_password = hash_password("000000")
    user.failed_login_attempts = 0
    user.pin_reset_requested = False
    user.must_change_pin = True
    await db.commit()

    await ws_manager.broadcast({
        "type": "PIN_RESET_COMPLETED",
        "data": {
            "user_id": user.id,
            "user_name": user.name,
            "user": serialize_user_for_ws(user),
            "message": f"PIN restablecido a 000000 para {user.name}"
        }
    })
    await ws_manager.broadcast({
        "type": "USER_UPDATED",
        "data": serialize_user_for_ws(user)
    })

    return {
        "success": True,
        "message": f"El PIN de {user.name} ha sido restablecido a 000000 por defecto. Al iniciar sesión se le exigirá registrar su nuevo PIN personal."
    }

@router.post("/change-pin")
async def change_user_pin(
    data: ChangePinRequest,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Permite al usuario autenticado (después de ingresar con el PIN reseteado 000000) registrar y confirmar su nuevo PIN definitivo.
    """
    # Este endpoint solo sirve para el cambio obligatorio tras un reseteo (PIN 000000).
    if not current_user.must_change_pin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Para cambiar tu PIN usa tu perfil e ingresa tu PIN actual."
        )

    p1 = data.new_pin.strip()
    p2 = data.confirm_pin.strip()

    if p1 != p2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Los dos PIN ingresados no coinciden. Por favor verifica ambos campos."
        )

    if p1 == "000000":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes utilizar 000000 como tu PIN definitivo. Por favor define un PIN personal y seguro."
        )

    # Validar que cumpla con las políticas de seguridad
    validate_pin_security(p1, dni=current_user.dni or "", phone=current_user.phone or "")

    current_user.hashed_password = hash_password(p1)
    current_user.must_change_pin = False
    current_user.failed_login_attempts = 0
    current_user.pin_reset_requested = False
    await db.commit()
    await db.refresh(current_user)

    await ws_manager.broadcast({
        "type": "USER_UPDATED",
        "data": serialize_user_for_ws(current_user)
    })

    return {
        "success": True,
        "message": "¡Tu nuevo PIN de seguridad ha sido guardado exitosamente! Tu cuenta está completamente protegida.",
        "must_change_pin": False
    }

@router.get("/me", response_model=UserOut)
async def get_current_user_profile(
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db)
):
    if user.role == "merchant":
        needs_commit = False
        if not user.store_id:
            st_stmt = select(Store).where(Store.owner_id == user.id)
            st_res = (await db.execute(st_stmt)).scalars().first()
            if st_res:
                user.store_id = st_res.id
                needs_commit = True

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        sub_end = user.subscription_period_end
        if sub_end and sub_end.tzinfo is not None:
            sub_end = sub_end.astimezone(timezone.utc).replace(tzinfo=None)
        if sub_end and sub_end < now_utc and user.subscription_status not in ["pending_approval", "canceled"]:
            user.subscription_status = "past_due"
            needs_commit = True

        if needs_commit:
            await db.commit()
            await db.refresh(user)

    return user

@router.put("/profile", response_model=UserOut)
async def update_current_user_profile(
    data: UserProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user)
):
    """
    Permite al usuario autenticado (comerciante o superadmin) actualizar sus datos personales
    y rectificar su nombre, correo, DNI, teléfono, dirección y cambiar su PIN de acceso.
    """
    # 1. Si cambia el correo, verificar unicidad
    if data.email and data.email.strip().lower() != current_user.email.lower():
        clean_email = data.email.strip().lower()
        stmt = select(User).where(User.email == clean_email, User.id != current_user.id)
        exists = (await db.execute(stmt)).scalar_one_or_none()
        if exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El correo electrónico ingresado ya está registrado por otro usuario."
            )
        current_user.email = clean_email

    # 2. Si cambia el DNI, verificar formato y unicidad
    if data.dni is not None:
        clean_dni = data.dni.strip()
        if clean_dni:
            if not re.match(r"^\d{8}$", clean_dni):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El DNI debe contener exactamente 8 dígitos numéricos."
                )
            stmt = select(User).where(User.dni == clean_dni, User.id != current_user.id)
            exists = (await db.execute(stmt)).scalar_one_or_none()
            if exists:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El DNI ingresado ya está registrado por otro usuario."
                )
            current_user.dni = clean_dni
        else:
            current_user.dni = None

    # 3. Datos personales básicos
    if data.name and data.name.strip():
        current_user.name = data.name.strip()
    if data.phone is not None:
        current_user.phone = data.phone.strip()
    if data.personal_address is not None:
        current_user.personal_address = data.personal_address.strip()

    # 4. Cambio de PIN
    if data.new_pin:
        # SEGURIDAD: siempre se exige el PIN actual para cambiarlo
        if not data.current_pin or not verify_password(data.current_pin.strip(), current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El PIN de seguridad actual no es correcto."
            )
        validate_pin_security(data.new_pin, current_user.dni or "", current_user.phone or "")
        current_user.hashed_password = hash_password(data.new_pin.strip())

    await db.commit()
    await db.refresh(current_user)
    return current_user

@router.get("/users", response_model=List[UserOut])
async def get_all_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user)
):
    if current_user.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido únicamente para el Superadministrador."
        )
    stmt = select(User).order_by(User.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()

@router.put("/users/{user_id}", response_model=UserOut)
async def admin_update_user(
    user_id: str,
    data: UserAdminUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user)
):
    """
    Permite al SuperAdmin rectificar cualquier dato de un usuario, asignarle rol/tienda,
    cambiar su estado de suscripción o resetearle el PIN de 6 dígitos.
    """
    if current_user.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido únicamente para el Superadministrador."
        )
    target_user = await db.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if data.email and data.email.strip().lower() != target_user.email.lower():
        clean_email = data.email.strip().lower()
        stmt = select(User).where(User.email == clean_email, User.id != target_user.id)
        exists = (await db.execute(stmt)).scalar_one_or_none()
        if exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El correo electrónico ya está registrado por otro usuario."
            )
        target_user.email = clean_email

    if data.dni is not None:
        clean_dni = data.dni.strip()
        if clean_dni:
            if not re.match(r"^\d{8}$", clean_dni):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El DNI debe contener exactamente 8 dígitos numéricos."
                )
            stmt = select(User).where(User.dni == clean_dni, User.id != target_user.id)
            exists = (await db.execute(stmt)).scalar_one_or_none()
            if exists:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El DNI ya está registrado por otro usuario."
                )
            target_user.dni = clean_dni
        else:
            target_user.dni = None

    if data.name and data.name.strip():
        target_user.name = data.name.strip()
    if data.phone is not None:
        target_user.phone = data.phone.strip()
    if data.personal_address is not None:
        target_user.personal_address = data.personal_address.strip()
    if data.role and data.role in ["merchant", "superadmin"]:
        target_user.role = data.role
    if data.store_id is not None:
        target_user.store_id = data.store_id if data.store_id != "all" else None
    if data.subscription_plan:
        target_user.subscription_plan = data.subscription_plan

    if data.subscription_period_end is not None:
        target_user.subscription_period_end = data.subscription_period_end

    if data.subscription_status and data.subscription_status in ["active", "trial", "past_due", "canceled", "pending_approval"]:
        target_user.subscription_status = data.subscription_status

    if data.status and data.status in ["active", "suspended", "pending_approval"]:
        target_user.status = data.status
        if target_user.store_id:
            store = await db.get(Store, target_user.store_id)
            if store:
                store.is_active = (data.status == "active")

    if data.new_pin:
        validate_pin_security(data.new_pin, target_user.dni or "", target_user.phone or "")
        target_user.hashed_password = hash_password(data.new_pin.strip())

    await db.commit()
    catalog_cache.invalidate()  # aprobar/suspender/eliminar cambia qué tiendas son públicas
    await db.refresh(target_user)
    await ws_manager.broadcast({
        "type": "USER_UPDATED",
        "data": serialize_user_for_ws(target_user)
    })
    return target_user

@router.put("/users/{user_id}/status")
async def update_user_status(
    user_id: str,
    status_data: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user)
):
    if current_user.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido únicamente para el Superadministrador."
        )
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    new_status = status_data.get("status")
    previous_status = user.status
    if new_status:
        user.status = new_status
        if user.store_id:
            store = await db.get(Store, user.store_id)
            if store:
                store.is_active = (new_status == "active")
        await db.commit()
        catalog_cache.invalidate()  # aprobar/suspender/eliminar cambia qué tiendas son públicas
        await db.refresh(user)
        await ws_manager.broadcast({
            "type": "USER_UPDATED",
            "data": serialize_user_for_ws(user)
        })
        if user.role == "merchant" and previous_status != new_status:
            if new_status == "active":
                await notify([user.id], "ACCOUNT_APPROVED", "¡Tu tienda fue aprobada!",
                             "Ya está publicada y puede recibir pedidos por WhatsApp.",
                             {"view": "merchant", "tab": "overview"}, user.store_id)
            elif new_status == "suspended":
                await notify([user.id], "ACCOUNT_SUSPENDED", "Tu cuenta fue suspendida",
                             "Tu tienda no se muestra al público. Comunícate con el administrador.",
                             {"view": "merchant", "tab": "subscription"}, user.store_id)
    return {"message": "Estado actualizado exitosamente", "user_id": user.id, "status": user.status}

@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    role_data: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user)
):
    if current_user.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido únicamente para el Superadministrador."
        )
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    new_role = role_data.get("role")
    if new_role and new_role not in ("merchant", "superadmin"):
        raise HTTPException(status_code=400, detail="Rol no válido.")
    if new_role:
        user.role = new_role
        await db.commit()
        await db.refresh(user)
        await ws_manager.broadcast({
            "type": "USER_UPDATED",
            "data": serialize_user_for_ws(user)
        })
    return {"message": "Rol actualizado exitosamente", "user_id": user.id, "role": user.role}

@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user)
):
    if current_user.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido únicamente para el Superadministrador."
        )
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes eliminar tu propia cuenta de Superadministrador."
        )

    # Solo poder eliminar un usuario si su plan está vencido o cancelado
    if user.role == "merchant":
        is_explicit = (
            user.subscription_status in ("past_due", "canceled")
            or user.status == "suspended"
        )
        now_utc = datetime.now(timezone.utc)
        is_period_past = False
        if user.subscription_period_end:
            end_dt = user.subscription_period_end
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            is_period_past = end_dt <= now_utc
        
        if not (is_explicit or is_period_past):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Solo se puede eliminar un usuario si su plan de suscripción está vencido o cancelado."
            )
    
    await db.delete(user)
    await db.commit()
    catalog_cache.invalidate()  # aprobar/suspender/eliminar cambia qué tiendas son públicas
    await ws_manager.broadcast({
        "type": "USER_DELETED",
        "data": {"id": user_id}
    })
    return {"message": "Usuario eliminado exitosamente"}

