import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE_PATH = Path(__file__).resolve().parent.parent.parent / ".env"

load_dotenv(dotenv_path=ENV_FILE_PATH, encoding="utf-8-sig", override=False)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="allow"
    )

    PROJECT_NAME: str = "JamuyWasi API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api"
    
    DATABASE_URL: str
    
    MINIO_ENDPOINT: str = "100.75.189.26:9000"
    MINIO_ACCESS_KEY: str
    MINIO_SECRET_KEY: str
    MINIO_BUCKET: str = "atalaya-store"
    MINIO_SECURE: bool = False
    MINIO_PUBLIC_URL_PREFIX: str = ""
    
    # Obligatorio en .env. Debe ser largo y aleatorio (mínimo 32 caracteres).
    JWT_SECRET: str
    # Salt de los hashes SHA-256 antiguos (solo para migrar cuentas existentes a Argon2).
    LEGACY_PASSWORD_SALT: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    
    CORS_ORIGINS: str = "*"

    # "production" oculta /docs y exige CORS_ORIGINS con dominios concretos
    ENVIRONMENT: str = "development"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.strip().lower() == "production"

    URL_YAPE_VERIFY: str = "https://backend-yata.jamuywasi.com/api/v1/transactions/verify"
    TOKEN_YAPE: str = ""

    @property
    def cors_origins_list(self) -> List[str]:
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

settings = Settings()

if len(settings.JWT_SECRET) < 32 or settings.JWT_SECRET.startswith("super-secret-atalaya"):
    raise RuntimeError(
        "JWT_SECRET inseguro: define en .env un valor aleatorio de al menos 32 caracteres "
        "(ej. python -c \"import secrets; print(secrets.token_urlsafe(48))\")."
    )

if settings.is_production and settings.CORS_ORIGINS.strip() == "*":
    raise RuntimeError(
        "En producción CORS_ORIGINS no puede ser '*'. "
        "Si la web y la API van en el mismo dominio (Nginx del frontend), déjalo vacío: CORS_ORIGINS= . "
        "Si la web está en otro dominio: CORS_ORIGINS=https://tudominio.com,https://www.tudominio.com"
    )
