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

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize all database tables on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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

# CORS configuration
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
