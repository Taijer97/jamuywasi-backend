import os
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from app.core.utc_json import UTCJSONResponse
from app.core.config import settings
from app.core.database import engine, Base
import app.models # registers all models
from app.routers import auth, stores, products, orders, banners, uploads, websocket_router, promo_codes, payments, seo, notifications

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

    # Columnas nuevas en tablas existentes (p. ej. orders.customer_dni)
    from app.core.schema_upgrade import upgrade_schema
    await upgrade_schema(engine)

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

    # 3) Redis (opcional): reparte WebSocket, caché y límites entre varios procesos del backend
    from app.core import redis_bus
    workers = int(os.getenv("WEB_CONCURRENCY", "1") or 1)
    if redis_bus.enabled():
        await redis_bus.start()
    elif workers > 1:
        logger.error(
            "WEB_CONCURRENCY=%s pero no hay REDIS_URL: con varios procesos sin Redis los avisos en tiempo real "
            "y la caché no se comparten. Configura REDIS_URL o usa WEB_CONCURRENCY=1.", workers
        )

    # 4) Revisión periódica de planes por vencer / vencidos (notificaciones)
    from app.core.notifications import subscription_watcher
    watcher = asyncio.create_task(subscription_watcher())

    yield
    watcher.cancel()
    await redis_bus.stop()
    await engine.dispose()

from app.routers.uploads import reject_oversized_uploads
app = FastAPI(
    default_response_class=UTCJSONResponse,
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
# Subidas demasiado grandes se rechazan antes de leer el cuerpo
app.middleware("http")(reject_oversized_uploads)

app.include_router(auth.router, prefix=api_prefix)
app.include_router(stores.router, prefix=api_prefix)
app.include_router(products.router, prefix=api_prefix)
app.include_router(orders.router, prefix=api_prefix)
app.include_router(banners.router, prefix=api_prefix)
app.include_router(uploads.router, prefix=api_prefix)
app.include_router(websocket_router.router, prefix=api_prefix)
app.include_router(promo_codes.router, prefix=api_prefix)
app.include_router(payments.router, prefix=api_prefix)
app.include_router(seo.router, prefix=api_prefix)
app.include_router(notifications.router, prefix=api_prefix)

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
        from app.core import redis_bus
        redis_state = "off" if not redis_bus.enabled() else ("ok" if redis_bus.is_healthy() else "reconnecting")
        # Redis caído no marca la API como caída: sigue funcionando con memoria local
        return {"status": "healthy", "database": "ok", "redis": redis_state}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unhealthy", "database": "error"})
