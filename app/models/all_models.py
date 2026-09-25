from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, Text, Boolean, Integer, Float, DateTime, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base

def generate_uuid(prefix: str = "") -> str:
    unique = uuid.uuid4().hex[:12]
    return f"{prefix}_{unique}" if prefix else unique

class User(Base):
    __tablename__ = "users"

    id = Column(String(50), primary_key=True, default=lambda: generate_uuid("usr"))
    name = Column(String(120), nullable=False)
    email = Column(String(150), unique=True, index=True, nullable=False)
    dni = Column(String(20), unique=True, index=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(30), default="merchant") # 'merchant' or 'superadmin'
    store_id = Column(String(50), ForeignKey("stores.id", ondelete="SET NULL"), nullable=True)
    phone = Column(String(50), nullable=True)
    personal_address = Column(String(255), nullable=True)
    status = Column(String(30), default="active")
    subscription_plan = Column(String(30), default="starter")
    subscription_status = Column(String(30), default="active")
    subscription_period_end = Column(DateTime, nullable=True)
    yape_verification_attempts = Column(Integer, default=0)
    failed_login_attempts = Column(Integer, default=0)
    pin_reset_requested = Column(Boolean, default=False)
    pin_reset_requested_at = Column(DateTime, nullable=True)
    must_change_pin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    store = relationship("Store", back_populates="users", foreign_keys=[store_id])
    owned_stores = relationship("Store", back_populates="owner", foreign_keys="Store.owner_id")
    invoices = relationship("SubscriptionInvoice", back_populates="user", cascade="all, delete-orphan")

class Store(Base):
    __tablename__ = "stores"

    id = Column(String(50), primary_key=True, default=lambda: generate_uuid("store"))
    owner_id = Column(String(50), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(120), nullable=False)
    ruc = Column(String(20), nullable=True)
    store_type = Column(String(20), default="virtual") # 'fisica' | 'virtual'
    category = Column(String(100), default="General")
    slug = Column(String(120), unique=True, index=True, nullable=False)
    tagline = Column(String(255), default="")
    description = Column(Text, default="")
    logo = Column(String(500), default="")
    banner = Column(String(500), default="")
    country_code = Column(String(10), default="51")
    phone = Column(String(30), default="") # WhatsApp phone number
    store_email = Column(String(150), nullable=True)
    currency = Column(String(10), default="PEN")
    currency_symbol = Column(String(10), default="S/")
    address = Column(String(255), default="")
    schedule = Column(String(255), default="")
    delivery_fee = Column(Float, default=10.0)
    free_delivery_threshold = Column(Float, default=150.0)
    allow_delivery = Column(Boolean, default=True)
    allow_pickup = Column(Boolean, default=True)
    pickup_address = Column(String(255), default="")
    preferred_payment_method = Column(String(100), default="Transferencia Bancaria")
    payment_instructions = Column(Text, default="")
    whatsapp_message_template = Column(Text, default="")
    theme_color = Column(String(30), default="emerald")
    socials = Column(JSON, default=dict) # {"instagram": "...", "facebook": "..."}
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    owner = relationship("User", back_populates="owned_stores", foreign_keys=[owner_id])
    users = relationship("User", back_populates="store", foreign_keys=[User.store_id])
    products = relationship("Product", back_populates="store", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="store", cascade="all, delete-orphan")
    invoices = relationship("SubscriptionInvoice", back_populates="store")

class Product(Base):
    __tablename__ = "products"

    id = Column(String(50), primary_key=True, default=lambda: generate_uuid("prod"))
    store_id = Column(String(50), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False, index=True)
    slug = Column(String(200), nullable=False)
    description = Column(Text, default="")
    price = Column(Float, nullable=False)
    compare_at_price = Column(Float, nullable=True)
    category = Column(String(100), index=True, default="General")
    image_url = Column(String(500), nullable=False)
    additional_images = Column(JSON, default=list)
    sku = Column(String(100), nullable=True)
    in_stock = Column(Boolean, default=True)
    stock_count = Column(Integer, default=10)
    is_featured = Column(Boolean, default=False)
    views_count = Column(Integer, default=0, index=True)
    variants = Column(JSON, default=list) # [{"name": "Talla", "options": ["S", "M", "L"]}]
    combinations = Column(JSON, default=list)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    store = relationship("Store", back_populates="products")

class Order(Base):
    __tablename__ = "orders"

    id = Column(String(50), primary_key=True, default=lambda: generate_uuid("ord"))
    order_number = Column(String(50), unique=True, index=True, nullable=False)
    store_id = Column(String(50), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_name = Column(String(120), nullable=False)
    customer_dni = Column(String(12), nullable=True)   # DNI (8) o carné de extranjería (9)
    customer_phone = Column(String(50), nullable=False)
    customer_address = Column(String(255), default="")
    notes = Column(Text, default="")
    delivery_type = Column(String(30), default="delivery") # 'delivery' | 'pickup'
    payment_method = Column(String(50), default="Yape/Plin")
    items = Column(JSON, default=list) # Array of order items
    subtotal = Column(Float, default=0.0)
    delivery_fee = Column(Float, default=0.0)
    total = Column(Float, default=0.0)
    status = Column(String(50), default="pending_whatsapp")
    whatsapp_message_sent = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    store = relationship("Store", back_populates="orders")

class PromotionalBanner(Base):
    __tablename__ = "promotional_banners"

    id = Column(String(50), primary_key=True, default=lambda: generate_uuid("banner"))
    title = Column(String(200), nullable=False, default="")
    subtitle = Column(String(255), default="")
    badge = Column(String(100), default="")
    image_url = Column(String(500), nullable=False)
    product_id = Column(String(50), nullable=True)
    store_id = Column(String(50), nullable=True)
    button_text = Column(String(100), default="Ver Producto")
    gradient_theme = Column(String(50), default="emerald")
    is_active = Column(Boolean, default=True)
    order = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class PromoCode(Base):
    __tablename__ = "promo_codes"

    id = Column(String(50), primary_key=True, default=lambda: generate_uuid("promo"))
    code = Column(String(50), unique=True, index=True, nullable=False)
    discount_type = Column(String(20), default="percentage") # 'percentage' | 'fixed'
    discount_value = Column(Float, nullable=False)
    max_uses = Column(Integer, default=0) # 0 = unlimited
    used_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    valid_until = Column(DateTime, nullable=True)
    applicable_plan = Column(String(50), default="all") # 'all' | 'starter' | 'pro' | 'business'
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String(100), primary_key=True)
    value = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class SubscriptionInvoice(Base):
    __tablename__ = "subscription_invoices"

    id = Column(String(50), primary_key=True, default=lambda: generate_uuid("inv"))
    invoice_number = Column(String(50), unique=True, index=True, nullable=False)
    user_id = Column(String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    store_id = Column(String(50), ForeignKey("stores.id", ondelete="SET NULL"), nullable=True, index=True)
    plan_id = Column(String(30), nullable=False)
    plan_name = Column(String(100), nullable=False)
    billing_cycle = Column(String(20), default="monthly")
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="PEN")
    payment_method = Column(String(50), default="Yape/Plin")
    reference = Column(String(100), nullable=True)
    status = Column(String(30), default="paid")
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="invoices")
    store = relationship("Store", back_populates="invoices")


class Notification(Base):
    """Notificación para un usuario (comerciante o superadmin). Una fila por destinatario."""
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key", name="uq_notification_user_dedupe"),)

    id = Column(String(50), primary_key=True, default=lambda: generate_uuid("ntf"))
    user_id = Column(String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    store_id = Column(String(50), nullable=True)
    type = Column(String(40), nullable=False)          # ORDER_NEW, PLAN_EXPIRING, PLAN_EXPIRED, APPROVAL_PENDING, ...
    title = Column(String(160), nullable=False)
    message = Column(String(400), default="")
    link = Column(JSON, default=dict)                   # {"view": "merchant", "tab": "orders", "targetId": "ord_..."}
    dedupe_key = Column(String(120), nullable=True)     # evita repetir recordatorios (p. ej. plan por vencer)
    is_read = Column(Boolean, default=False, index=True)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
