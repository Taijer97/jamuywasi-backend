import asyncio
import io
import json
import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import urllib3
from minio import Minio

from app.core.config import settings

logger = logging.getLogger("jamuywasi.storage")

# --- Concurrencia del almacenamiento --------------------------------------------------
# Hilos propios para hablar con MinIO (antes se usaba el pool por defecto de asyncio,
# que en un VPS de 2 núcleos tiene solo 6 hilos y además lo comparte con todo lo demás).
STORAGE_THREADS = int(os.getenv("STORAGE_THREADS", "16"))
# Máximo de subidas procesándose a la vez; el resto espera su turno sin ocupar memoria extra.
UPLOAD_CONCURRENCY = int(os.getenv("UPLOAD_CONCURRENCY", "16"))
PUBLIC_FOLDERS = ("products", "logos", "banners", "uploads")
storage_executor = ThreadPoolExecutor(max_workers=STORAGE_THREADS, thread_name_prefix="minio")
_upload_slots: "asyncio.Semaphore | None" = None


def upload_slots() -> asyncio.Semaphore:
    global _upload_slots
    if _upload_slots is None:
        _upload_slots = asyncio.Semaphore(UPLOAD_CONCURRENCY)
    return _upload_slots


async def run_storage(fn, *args, **kwargs):
    """Ejecuta una llamada bloqueante de MinIO en los hilos de almacenamiento."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(storage_executor, lambda: fn(*args, **kwargs))


class MinIOStorageService:
    """Cliente de MinIO que NO se conecta al importar la app.

    Antes se comprobaba el bucket al importar el módulo: si MinIO no respondía,
    la API tardaba minutos en arrancar (o fallaba). Ahora la conexión es perezosa,
    con tiempos de espera cortos, y el bucket se verifica la primera vez que se usa.
    """

    def __init__(self):
        self.bucket_name = settings.MINIO_BUCKET
        self._bucket_checked = False
        self._lock = threading.Lock()

        http_client = urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=5, read=30),
            maxsize=STORAGE_THREADS,
            retries=urllib3.Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504]),
        )
        self.client = Minio(
            endpoint=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
            http_client=http_client,
            # Región fija: permite firmar subidas directas sin consultar a MinIO
            region=os.getenv("MINIO_REGION", "us-east-1"),
        )

    def ensure_bucket(self) -> bool:
        """Crea el bucket (lectura pública) si no existe. Devuelve True si MinIO responde."""
        if self._bucket_checked:
            return True
        with self._lock:
            if self._bucket_checked:
                return True
            try:
                if not self.client.bucket_exists(self.bucket_name):
                    self.client.make_bucket(self.bucket_name)
                # Lectura pública SOLO de las carpetas de imágenes (Nginx las sirve directo desde MinIO).
                # Se aplica siempre, también a buckets ya existentes (es idempotente).
                policy = {
                    "Version": "2012-10-17",
                    "Statement": [{
                        "Effect": "Allow",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{self.bucket_name}/{f}/*" for f in PUBLIC_FOLDERS],
                    }],
                }
                try:
                    self.client.set_bucket_policy(self.bucket_name, json.dumps(policy))
                except Exception as e:
                    logger.warning("No se pudo aplicar la política de lectura pública del bucket: %s", e)
                self._bucket_checked = True
                logger.info("MinIO OK (%s, bucket %s)", settings.MINIO_ENDPOINT, self.bucket_name)
                return True
            except Exception as e:
                logger.error("No se pudo conectar a MinIO en %s: %s", settings.MINIO_ENDPOINT, e)
                return False

    def upload_stream(
        self,
        stream,
        length: int,
        ext: str,
        content_type: str = "image/jpeg",
        folder: str = "uploads",
    ) -> str:
        """Sube un archivo leyéndolo por partes (sin cargarlo entero en memoria) y devuelve la URL."""
        self.ensure_bucket()
        unique_name = f"{folder}/{uuid.uuid4().hex}.{ext}"
        self.client.put_object(
            bucket_name=self.bucket_name,
            object_name=unique_name,
            data=stream,
            length=length,
            content_type=content_type,
            part_size=5 * 1024 * 1024,
        )
        return self.public_url(unique_name)

    def public_url(self, object_name: str) -> str:
        if settings.MINIO_PUBLIC_URL_PREFIX:
            prefix = settings.MINIO_PUBLIC_URL_PREFIX.rstrip("/")
            return f"{prefix}/{self.bucket_name}/{object_name}"
        # Servido a través de la API para garantizar HTTPS en cualquier dominio
        return f"{settings.API_V1_STR}/uploads/media/{object_name}"

    def upload_file_bytes(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str = "image/jpeg",
        folder: str = "uploads",
    ) -> str:
        """Sube bytes a MinIO y devuelve la URL pública."""
        self.ensure_bucket()
        ext = filename.split(".")[-1].lower() if "." in filename else "jpg"
        unique_name = f"{folder}/{uuid.uuid4().hex}.{ext}"

        self.client.put_object(
            bucket_name=self.bucket_name,
            object_name=unique_name,
            data=io.BytesIO(file_bytes),
            length=len(file_bytes),
            content_type=content_type,
        )

        if settings.MINIO_PUBLIC_URL_PREFIX:
            prefix = settings.MINIO_PUBLIC_URL_PREFIX.rstrip("/")
            return f"{prefix}/{self.bucket_name}/{unique_name}"

        # Servido a través de la API para garantizar HTTPS en cualquier dominio
        return f"{settings.API_V1_STR}/uploads/media/{unique_name}"


minio_service = MinIOStorageService()
