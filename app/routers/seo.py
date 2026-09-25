"""Vista previa de enlaces (WhatsApp, Facebook, Telegram, X...).

Los robots que generan la vista previa NO ejecutan JavaScript: solo leen las etiquetas
<meta property="og:..."> del HTML. Como la web es una SPA, todas las páginas tendrían la misma
vista previa. Nginx detecta a esos robots y les pide a este endpoint un HTML pequeño con
el título, la descripción y la imagen de la tienda o del producto compartido.
Las personas siguen recibiendo la app normal.
"""
import html
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlsplit, parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.all_models import Store, Product, User

router = APIRouter(prefix="/seo", tags=["Vista previa de enlaces"])

BRAND = "JamuyWasi"
DEFAULT_TITLE = "JamuyWasi · Catálogos digitales con pedidos por WhatsApp"
DEFAULT_DESC = "Explora tiendas locales, arma tu pedido y envíalo directo por WhatsApp."
DEFAULT_IMAGE = "/brand/og-image.png"
RESERVED = {"marketplace", "merchant", "superadmin", "home", "catalogo", "catalog", "admin", "index.html"}
MINIO_PATH = re.compile(r"/atalaya-store/(logos|products|banners|uploads)/([^/?#]+)", re.I)


def _base_url(request: Request) -> str:
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL.rstrip("/")
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def _abs_image(url: Optional[str], base: str) -> Optional[str]:
    """Las imágenes deben ser URLs absolutas y públicas para WhatsApp."""
    if not url:
        return None
    m = MINIO_PATH.search(url)
    if m:  # URL interna de MinIO -> servida por la API bajo el dominio público
        return f"{base}/api/uploads/media/{m.group(1)}/{m.group(2)}"
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/"):
        return base + url
    return None


def _short(text: Optional[str], limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _money(symbol: str, value: float) -> str:
    return f"{symbol or 'S/'} {value:,.2f}"


async def _public_store(db: AsyncSession, key: str) -> Optional[Store]:
    store = (await db.execute(select(Store).where(or_(Store.slug == key, Store.id == key)))).scalar_one_or_none()
    if not store or not store.is_active:
        return None
    # No mostrar tiendas cuyo comerciante está pendiente, suspendido o con suscripción vencida
    owner = None
    if store.owner_id:
        owner = await db.get(User, store.owner_id)
    if owner is None:
        owner = (await db.execute(select(User).where(User.store_id == store.id, User.role == "merchant"))).scalars().first()
    if owner and owner.role == "merchant":
        end = owner.subscription_period_end
        if end is not None and end.tzinfo is not None:
            end = end.astimezone(timezone.utc).replace(tzinfo=None)
        if (
            owner.status in ("pending_approval", "suspended")
            or owner.subscription_status in ("past_due", "canceled", "pending_approval")
            or (end is not None and end < datetime.now(timezone.utc).replace(tzinfo=None))
        ):
            return None
    return store


def _page(title: str, desc: str, image: Optional[str], url: str, image_alt: str, og_type: str = "website", price: Optional[str] = None) -> str:
    e = lambda s: html.escape(s or "", quote=True)
    img_tags = ""
    if image:
        img_tags = (
            f'<meta property="og:image" content="{e(image)}">\n'
            f'<meta property="og:image:secure_url" content="{e(image)}">\n'
            f'<meta property="og:image:alt" content="{e(image_alt)}">\n'
            f'<meta name="twitter:image" content="{e(image)}">\n'
        )
    price_tags = f'<meta property="product:price:amount" content="{e(price)}">\n<meta property="product:price:currency" content="PEN">\n' if price else ""
    return f"""<!doctype html>
<html lang="es"><head>
<meta charset="utf-8">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(url)}">
<meta property="og:site_name" content="{BRAND}">
<meta property="og:locale" content="es_PE">
<meta property="og:type" content="{e(og_type)}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(url)}">
{img_tags}{price_tags}<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(title)}">
<meta name="twitter:description" content="{e(desc)}">
</head><body><h1>{e(title)}</h1><p>{e(desc)}</p><p><a href="{e(url)}">{e(url)}</a></p></body></html>"""


@router.get("/render", response_class=HTMLResponse, include_in_schema=False)
async def render_preview(request: Request, uri: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """Recibe la URL original (cabecera X-Original-URI desde Nginx, o ?uri=) y devuelve las etiquetas OG."""
    original = request.headers.get("x-original-uri") or uri or "/"
    parts = urlsplit(original)
    query = parse_qs(parts.query)
    first_segment = parts.path.strip("/").split("/")[0] if parts.path.strip("/") else ""

    store_key = (query.get("store") or [""])[0]
    if not store_key and first_segment and first_segment.lower() not in RESERVED:
        store_key = first_segment
    product_key = (query.get("product") or [""])[0]

    base = _base_url(request)
    page_url = base + original
    headers = {"Cache-Control": "public, max-age=300"}

    store = await _public_store(db, store_key) if store_key else None

    if store and product_key:
        product = (await db.execute(
            select(Product).where(Product.store_id == store.id, or_(Product.id == product_key, Product.slug == product_key))
        )).scalars().first()
        if product:
            symbol = store.currency_symbol or "S/"
            price = _money(symbol, product.price)
            if product.compare_at_price and product.compare_at_price > product.price:
                price += f" (antes {_money(symbol, product.compare_at_price)})"
            stock = "" if product.in_stock else " · Agotado"
            desc = _short(f"{price}{stock} · {product.description or store.tagline or ''}")
            image = _abs_image(product.image_url, base) or _abs_image(store.logo, base) or base + DEFAULT_IMAGE
            return HTMLResponse(_page(f"{product.name} · {store.name}", desc, image, page_url,
                                      product.name, "product", f"{product.price:.2f}"), headers=headers)

    if store:
        desc = _short(store.tagline or store.description or f"Mira el catálogo de {store.name} y pide por WhatsApp.")
        image = _abs_image(store.banner, base) or _abs_image(store.logo, base) or base + DEFAULT_IMAGE
        return HTMLResponse(_page(f"{store.name} · Catálogo en {BRAND}", desc, image, page_url, store.name), headers=headers)

    return HTMLResponse(_page(DEFAULT_TITLE, DEFAULT_DESC, base + DEFAULT_IMAGE, page_url, BRAND), headers=headers)
