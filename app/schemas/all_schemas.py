from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field

# --- Auth ---
class UserLogin(BaseModel):
    identifier: Optional[str] = None # DNI or Email
    email: Optional[str] = None      # Backward compatibility
    password: str                    # PIN or password

class UserRegister(BaseModel):
    # Paso 1: Titular
    dni: Optional[str] = None
    name: str
    phone: Optional[str] = None
    email: EmailStr
    personal_address: Optional[str] = None
    
    # Paso 2: Tienda o Marca
    store_name: Optional[str] = None
    ruc: Optional[str] = None
    category: str = "General"
    store_type: str = "virtual" # 'fisica' | 'virtual'
    store_address: Optional[str] = None
    store_phone: Optional[str] = None
    store_email: Optional[str] = None
    about: Optional[str] = None
    
    # Paso 3: Seguridad
    password: str # 6-digit PIN or password
    pin: Optional[str] = None
    
    # Adicionales
    role: str = "merchant"
    plan: str = "starter"

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]

class UserOut(BaseModel):
    id: str
    name: str
    email: str
    dni: Optional[str] = None
    role: str
    store_id: Optional[str] = None
    phone: Optional[str] = None
    personal_address: Optional[str] = None
    status: str
    subscription_plan: str
    subscription_status: Optional[str] = "active"
    subscription_period_end: Optional[datetime] = None
    failed_login_attempts: Optional[int] = 0
    pin_reset_requested: Optional[bool] = False
    pin_reset_requested_at: Optional[datetime] = None
    must_change_pin: Optional[bool] = False
    created_at: datetime

    class Config:
        from_attributes = True

class ForgotPinRequest(BaseModel):
    identifier: str

class ForgotPinResponse(BaseModel):
    success: bool
    message: str
    user_name: str
    user_dni: Optional[str] = None
    store_name: Optional[str] = None
    admin_phone: str
    whatsapp_url: str

class AdminResetPinDefaultRequest(BaseModel):
    user_id: str

class ChangePinRequest(BaseModel):
    new_pin: str
    confirm_pin: str

class UserProfileUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    dni: Optional[str] = None
    phone: Optional[str] = None
    personal_address: Optional[str] = None
    current_pin: Optional[str] = None
    new_pin: Optional[str] = None

class UserAdminUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    dni: Optional[str] = None
    phone: Optional[str] = None
    personal_address: Optional[str] = None
    role: Optional[str] = None
    store_id: Optional[str] = None
    status: Optional[str] = None
    subscription_plan: Optional[str] = None
    subscription_status: Optional[str] = None
    subscription_period_end: Optional[datetime] = None
    new_pin: Optional[str] = None

# --- Store ---
class StoreBase(BaseModel):
    name: str
    slug: str
    ruc: Optional[str] = ""
    store_type: Optional[str] = "virtual"
    category: Optional[str] = "General"
    tagline: Optional[str] = ""
    description: Optional[str] = ""
    logo: Optional[str] = ""
    banner: Optional[str] = ""
    country_code: str = "51"
    phone: str = ""
    store_email: Optional[str] = ""
    currency: str = "PEN"
    currency_symbol: str = "S/"
    address: Optional[str] = ""
    schedule: Optional[str] = ""
    delivery_fee: float = 10.0
    free_delivery_threshold: float = 150.0
    allow_delivery: bool = True
    allow_pickup: bool = True
    pickup_address: Optional[str] = ""
    preferred_payment_method: Optional[str] = "Transferencia Bancaria"
    payment_instructions: Optional[str] = ""
    whatsapp_message_template: Optional[str] = ""
    theme_color: str = "emerald"
    socials: Optional[Dict[str, str]] = {}

class StoreCreate(StoreBase):
    slug: Optional[str] = None
    owner_id: Optional[str] = None

class StoreUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    store_type: Optional[str] = None # 'fisica' | 'virtual'
    category: Optional[str] = None
    ruc: Optional[str] = None
    tagline: Optional[str] = None
    description: Optional[str] = None
    logo: Optional[str] = None
    banner: Optional[str] = None
    country_code: Optional[str] = None
    phone: Optional[str] = None
    currency: Optional[str] = None
    currency_symbol: Optional[str] = None
    address: Optional[str] = None
    schedule: Optional[str] = None
    delivery_fee: Optional[float] = None
    free_delivery_threshold: Optional[float] = None
    allow_delivery: Optional[bool] = None
    allow_pickup: Optional[bool] = None
    pickup_address: Optional[str] = None
    preferred_payment_method: Optional[str] = None
    payment_instructions: Optional[str] = None
    whatsapp_message_template: Optional[str] = None
    theme_color: Optional[str] = None
    socials: Optional[Dict[str, str]] = None
    is_active: Optional[bool] = None

class StoreOut(StoreBase):
    id: str
    owner_id: Optional[str] = None
    is_active: bool
    created_at: datetime
    products_count: Optional[int] = 0

    class Config:
        from_attributes = True

# --- Product ---
class ProductVariant(BaseModel):
    name: str
    options: List[str]

class ProductBase(BaseModel):
    store_id: str
    name: str
    slug: Optional[str] = None
    description: Optional[str] = ""
    price: float
    compare_at_price: Optional[float] = None
    category: str = "General"
    image_url: str
    additional_images: Optional[List[str]] = []
    sku: Optional[str] = None
    in_stock: bool = True
    stock_count: int = 10
    is_featured: bool = False
    variants: Optional[List[Dict[str, Any]]] = []
    combinations: Optional[List[Dict[str, Any]]] = []

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    compare_at_price: Optional[float] = None
    category: Optional[str] = None
    image_url: Optional[str] = None
    additional_images: Optional[List[str]] = None
    sku: Optional[str] = None
    in_stock: Optional[bool] = None
    stock_count: Optional[int] = None
    is_featured: Optional[bool] = None
    variants: Optional[List[Dict[str, Any]]] = None
    combinations: Optional[List[Dict[str, Any]]] = None

class ProductOut(ProductBase):
    id: str
    views_count: int
    created_at: datetime
    store_name: Optional[str] = None
    store_logo: Optional[str] = None

    class Config:
        from_attributes = True

# --- Order ---
class OrderItemSchema(BaseModel):
    productId: str
    productName: str
    price: float
    quantity: int
    selectedVariants: Optional[Dict[str, str]] = {}
    subtotal: float
    imageUrl: Optional[str] = None

class OrderCreate(BaseModel):
    store_id: str = Field(..., max_length=50)
    order_number: Optional[str] = Field(None, max_length=20)  # número mostrado en el mensaje de WhatsApp
    customer_name: str = Field(..., min_length=1, max_length=120)
    customer_phone: str = Field(..., min_length=1, max_length=50)
    customer_address: Optional[str] = Field("", max_length=255)
    notes: Optional[str] = Field("", max_length=2000)
    delivery_type: str = Field("delivery", max_length=30)
    payment_method: str = Field("Yape/Plin", max_length=50)
    items: List[Dict[str, Any]] = Field(..., min_length=1, max_length=100)
    # Los montos enviados por el navegador solo se usan para detectar diferencias;
    # el servidor recalcula subtotal, envío y total con los precios de la base de datos.
    subtotal: float = 0.0
    delivery_fee: float = 0.0
    total: float = 0.0
    whatsapp_message_sent: Optional[str] = Field("", max_length=8000)

class OrderOut(BaseModel):
    id: str
    order_number: str
    store_id: str
    customer_name: str
    customer_phone: str
    customer_address: str
    notes: str
    delivery_type: str
    payment_method: str
    items: List[Dict[str, Any]]
    subtotal: float
    delivery_fee: float
    total: float
    status: str
    whatsapp_message_sent: str
    created_at: datetime

    class Config:
        from_attributes = True

# --- Banner ---
class PromotionalBannerBase(BaseModel):
    title: str
    subtitle: Optional[str] = ""
    badge: Optional[str] = "OFERTA"
    image_url: str
    product_id: Optional[str] = None
    store_id: Optional[str] = None
    button_text: str = "Ver Producto"
    gradient_theme: str = "emerald"
    is_active: bool = True
    order: int = 0

class PromotionalBannerCreate(PromotionalBannerBase):
    pass

class PromotionalBannerUpdate(BaseModel):
    title: Optional[str] = None
    subtitle: Optional[str] = None
    badge: Optional[str] = None
    image_url: Optional[str] = None
    product_id: Optional[str] = None
    store_id: Optional[str] = None
    button_text: Optional[str] = None
    gradient_theme: Optional[str] = None
    is_active: Optional[bool] = None
    order: Optional[int] = None

class PromotionalBannerOut(PromotionalBannerBase):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True

# --- Promo Codes ---
class PromoCodeCreate(BaseModel):
    code: str
    discount_type: str = "percentage" # 'percentage' | 'fixed'
    discount_value: float
    max_uses: int = 0
    is_active: bool = True
    valid_until: Optional[datetime] = None
    applicable_plan: Optional[str] = "all" # 'all' | 'starter' | 'pro' | 'business'

class PromoCodeOut(BaseModel):
    id: str
    code: str
    discount_type: str
    discount_value: float
    max_uses: int
    used_count: int
    is_active: bool
    valid_until: Optional[datetime] = None
    applicable_plan: Optional[str] = "all"
    created_at: datetime

    class Config:
        from_attributes = True

class PromoCodeValidateRequest(BaseModel):
    code: str
    plan_id: str
    billing_cycle: str = "monthly"
    base_amount: float

class PromoCodeValidateResponse(BaseModel):
    valid: bool
    message: str
    code: Optional[str] = None
    discount_type: Optional[str] = None
    discount_value: Optional[float] = 0.0
    discount_amount: float = 0.0
    final_amount: float = 0.0
    applicable_plan: Optional[str] = "all"

# --- Yape Verification ---
class YapeVerifyRequest(BaseModel):
    plan_id: str
    codigo: Optional[str] = "000" # 3-digit code for Yape, or "000" for free plans
    billing_cycle: str = "monthly"
    promo_code: Optional[str] = None

class YapeVerifyResponse(BaseModel):
    success: bool
    message: str
    activated: bool = False
    attempts: int = 0
    remaining_attempts: int = 3
    must_send_whatsapp: bool = False
    amount_paid: Optional[float] = None
    plan_id: Optional[str] = None
    store_id: Optional[str] = None
    user_status: Optional[str] = None
    subscription_status: Optional[str] = None
    subscription_period_end: Optional[datetime] = None

class YapePaymentConfigSchema(BaseModel):
    phone: str = "925763903"
    phone_formatted: str = "+51 925 763 903"
    holder: str = "JamuyWasi"
    qr_url: Optional[str] = ""
    instructions: Optional[str] = "Abona el monto exacto por Yape o Plin. Luego ingresa el código de aprobación de 3 dígitos para verificación y activación inmediata de tu tienda."
    updated_at: Optional[datetime] = None

class SubscriptionInvoiceOut(BaseModel):
    id: str
    invoice_number: str
    user_id: str
    store_id: Optional[str] = None
    plan_id: str
    plan_name: str
    billing_cycle: str
    amount: float
    currency: str
    payment_method: str
    reference: Optional[str] = None
    status: str
    period_start: datetime
    period_end: datetime
    created_at: datetime
    store_name: Optional[str] = None
    customer_name: Optional[str] = None
    customer_dni: Optional[str] = None

    class Config:
        from_attributes = True
