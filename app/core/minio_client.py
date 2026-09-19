import io
import uuid
from typing import Optional
from minio import Minio
from minio.error import S3Error
from app.core.config import settings

class MinIOStorageService:
    def __init__(self):
        self.endpoint = settings.MINIO_ENDPOINT
        self.access_key = settings.MINIO_ACCESS_KEY
        self.secret_key = settings.MINIO_SECRET_KEY
        self.bucket_name = settings.MINIO_BUCKET
        self.secure = settings.MINIO_SECURE

        self.client = Minio(
            endpoint=self.endpoint,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=self.secure,
        )
        self._ensure_bucket()

    def _ensure_bucket(self):
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                # Set public read policy so uploaded images can be retrieved directly
                import json
                policy = {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"AWS": ["*"]},
                            "Action": ["s3:GetObject"],
                            "Resource": [f"arn:aws:s3:::{self.bucket_name}/*"]
                        }
                    ]
                }
                self.client.set_bucket_policy(self.bucket_name, json.dumps(policy))
        except Exception as e:
            print(f"Warning initializing MinIO bucket: {e}")

    def upload_file_bytes(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str = "image/jpeg",
        folder: str = "uploads"
    ) -> str:
        """Upload bytes to MinIO and return the public URL"""
        ext = filename.split(".")[-1].lower() if "." in filename else "jpg"
        unique_name = f"{folder}/{uuid.uuid4().hex}.{ext}"

        file_stream = io.BytesIO(file_bytes)
        self.client.put_object(
            bucket_name=self.bucket_name,
            object_name=unique_name,
            data=file_stream,
            length=len(file_bytes),
            content_type=content_type,
        )

        if settings.MINIO_PUBLIC_URL_PREFIX:
            prefix = settings.MINIO_PUBLIC_URL_PREFIX.rstrip("/")
            return f"{prefix}/{self.bucket_name}/{unique_name}"

        # Enlace servido directamente a través de la API para garantizar HTTPS en cualquier túnel o dominio
        return f"{settings.API_V1_STR}/uploads/media/{unique_name}"

minio_service = MinIOStorageService()
