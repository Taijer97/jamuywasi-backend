import io
import json
import logging
import threading
import uuid

import urllib3
from minio import Minio

from app.core.config import settings

logger = logging.getLogger("jamuywasi.storage")


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
            maxsize=10,
            retries=urllib3.Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504]),
        )
        self.client = Minio(
            endpoint=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
            http_client=http_client,
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
                    policy = {
                        "Version": "2012-10-17",
                        "Statement": [{
                            "Effect": "Allow",
                            "Principal": {"AWS": ["*"]},
                            "Action": ["s3:GetObject"],
                            "Resource": [f"arn:aws:s3:::{self.bucket_name}/*"],
                        }],
                    }
                    self.client.set_bucket_policy(self.bucket_name, json.dumps(policy))
                self._bucket_checked = True
                logger.info("MinIO OK (%s, bucket %s)", settings.MINIO_ENDPOINT, self.bucket_name)
                return True
            except Exception as e:
                logger.error("No se pudo conectar a MinIO en %s: %s", settings.MINIO_ENDPOINT, e)
                return False

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
