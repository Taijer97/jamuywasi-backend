from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import AsyncAdaptedQueuePool
from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    poolclass=AsyncAdaptedQueuePool,
    pool_size=30,
    max_overflow=50,
    pool_timeout=30.0,
    pool_recycle=1800,
    pool_pre_ping=True,   # descarta conexiones cortadas por MySQL/red en vez de fallar la petición
    # si MySQL no responde, falla en 10 s en vez de colgarse
    connect_args={"connect_timeout": 10} if "mysql" in settings.DATABASE_URL else {},
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

Base = declarative_base()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
