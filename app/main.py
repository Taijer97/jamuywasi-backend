import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from app.core.config import settings
from app.core.database import engine, Base
import app.models # registers all models
from app.routers import auth, stores, products, orders, banners, uploads, websocket_router, promo_codes, payments

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("jamuywasi")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1) Base de datos: crea las tablas que falten. Si MySQL no responde, el error se explica claramente.
    db_host = settings.DATABASE_URL.split("@")[-1].split("/")[0]
    logger.info("Conectando a MySQL en %s ...", db_host)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        logger.error(
            "NO SE PUDO CONECTAR A MYSQL (%s): %s. Revisa DATABASE_URL en .env y que el servidor "
            "llegue a esa IP/puerto (si es una IP de Tailscale 100.x, el servidor debe estar en tu tailnet).",
            db_host, e,
        )
        raise
    logger.info("MySQL OK")

    # Limpieza única de textos automáticos antiguos de los anuncios del carrusel:
    # antes, al dejar vacíos el título o la etiqueta se guardaban "Anuncio Promocional" / "OFERTA".
    # Ahora esos campos son opcionales y vacíos significa "no mostrar nada". (Idempotente.)
    try:
        from sqlalchemy import update
        from app.models.all_models import PromotionalBanner
        async with engine.begin() as conn:
            r1 = await conn.execute(update(PromotionalBanner).where(PromotionalBanner.title == "Anuncio Promocional").values(title=""))
            r2 = await conn.execute(update(PromotionalBanner).where(PromotionalBanner.badge == "OFERTA").values(badge=""))
        if r1.rowcount or r2.rowcount:
            logger.info("Anuncios: %s título(s) y %s etiqueta(s) automáticos vaciados", r1.rowcount, r2.rowcount)
    except Exception as e:
        logger.warning("No se pudo limpiar textos automáticos de anuncios: %s", e)

    # 2) MinIO: se comprueba en segundo plano (no bloquea el arranque)
    from app.core.minio_client import minio_service
    asyncio.get_running_loop().run_in_executor(None, minio_service.ensure_bucket)

    yield
    await engine.dispose()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    # En producción no se publica la documentación interactiva de la API
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

# Compresión GZip de respuestas JSON grandes (catálogo de productos, pedidos): ~70-85% menos datos
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

# CORS: solo hace falta si la web se sirve desde OTRO dominio que la API.
# Con el Nginx del frontend (mismo dominio) se puede dejar CORS_ORIGINS vacío.
if settings.cors_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Register API Routers
api_prefix = settings.API_V1_STR
app.include_router(auth.router, prefix=api_prefix)
app.include_router(stores.router, prefix=api_prefix)
app.include_router(products.router, prefix=api_prefix)
app.include_router(orders.router, prefix=api_prefix)
app.include_router(banners.router, prefix=api_prefix)
app.include_router(uploads.router, prefix=api_prefix)
app.include_router(websocket_router.router, prefix=api_prefix)
app.include_router(promo_codes.router, prefix=api_prefix)
app.include_router(payments.router, prefix=api_prefix)

@app.get("/")
async def root():
    return {
        "message": "JamuyWasi API Online",
        "version": settings.VERSION
    }

@app.get("/api/health")
async def health_check():
    """Comprueba de verdad la base de datos (útil para Docker / monitoreo)."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "ok"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unhealthy", "database": "error"})
