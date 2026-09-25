import asyncio
import logging
import os
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from app.core.minio_client import minio_service, upload_slots, run_storage
from app.core.deps import get_required_user
from app.models.all_models import User
from app.core.rate_limit import rate_limit

logger = logging.getLogger("jamuywasi.uploads")

router = APIRouter(prefix="/uploads", tags=["Subida de Imágenes MinIO"])

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    # SVG deshabilitado: puede contener JavaScript (XSS almacenado)
}

# Carpetas permitidas (evita escribir en rutas arbitrarias del bucket)
ALLOWED_UPLOAD_FOLDERS = {"logos", "products", "banners"}
ALLOWED_MEDIA_FOLDERS = ALLOWED_UPLOAD_FOLDERS | {"uploads"}

# Tamaño máximo por imagen. El navegador ya comprime las fotos a ~150-400 KB,
# así que 5 MB es un margen amplio (antes 10 MB).
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "5"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# Firmas de archivo: evita que un archivo cualquiera se suba con un content-type de imagen
_MAGIC = {
    "jpg": [b"\xff\xd8\xff"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "gif": [b"GIF87a", b"GIF89a"],
    "webp": [b"RIFF"],
}


def _looks_like(ext: str, head: bytes) -> bool:
    if ext == "webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    return any(head.startswith(sig) for sig in _MAGIC.get(ext, []))


async def reject_oversized_uploads(request: Request, call_next):
    """Rechaza subidas demasiado grandes ANTES de leer el cuerpo (no gasta memoria ni disco)."""
    if request.method == "POST" and request.url.path.endswith("/uploads/image"):
        try:
            length = int(request.headers.get("content-length") or 0)
        except ValueError:
            length = 0
        if length > MAX_UPLOAD_BYTES + 64 * 1024:  # margen para los encabezados multipart
            return JSONResponse(
                status_code=413,
                content={"detail": f"La imagen excede el límite de {MAX_UPLOAD_MB} MB."},
            )
        # Turno de subida ANTES de leer el cuerpo: así solo UPLOAD_CONCURRENCY imágenes ocupan
        # memoria a la vez; las demás esperan con la conexión abierta (sin gastar RAM).
        slots = upload_slots()
        try:
            await asyncio.wait_for(slots.acquire(), timeout=90)
        except asyncio.TimeoutError:
            return JSONResponse(
                status_code=503,
                content={"detail": "Hay muchas subidas en este momento. Inténtalo de nuevo en unos segundos."},
                headers={"Retry-After": "10"},
            )
        try:
            return await call_next(request)
        finally:
            slots.release()
    return await call_next(request)


# 120 subidas cada 10 min POR USUARIO (antes 60 por IP: varios comerciantes con la misma IP se bloqueaban)
@router.post("/image", dependencies=[Depends(rate_limit("upload", 120, 600, by="user"))])
async def upload_image(
    file: UploadFile = File(...),
    folder: str = "products",
    current_user: User = Depends(get_required_user)
):
    """Sube una imagen a MinIO por partes (sin cargarla entera en memoria) y devuelve su URL."""
    if folder not in ALLOWED_UPLOAD_FOLDERS:
        raise HTTPException(status_code=400, detail="Carpeta de destino no permitida.")

    content_type = file.content_type or "image/jpeg"
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de archivo no permitido: {content_type}. Solo se aceptan imágenes (JPG, PNG, WEBP, GIF)."
        )
    ext = ALLOWED_IMAGE_TYPES[content_type]

    # El archivo ya está en un temporal (en disco si pasa de 1 MB): medirlo sin leerlo entero
    fobj = file.file
    fobj.seek(0, os.SEEK_END)
    size = fobj.tell()
    fobj.seek(0)
    if size == 0:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    if size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"La imagen excede el límite de {MAX_UPLOAD_MB} MB.")
    head = fobj.read(16)
    fobj.seek(0)
    if not _looks_like(ext, head):
        raise HTTPException(status_code=400, detail="El archivo no es una imagen válida.")

    try:
        # (el turno de subida se tomó en reject_oversized_uploads, antes de leer el cuerpo)
        url = await run_storage(
            minio_service.upload_stream, fobj, size, ext, content_type=content_type, folder=folder
        )
        return {"status": "success", "url": url, "filename": file.filename, "size": size}
    except Exception as e:
        logger.error("Error subiendo imagen a MinIO: %s", e)
        raise HTTPException(status_code=502, detail="No se pudo guardar la imagen. Inténtalo de nuevo en unos segundos.")
    finally:
        await file.close()


@router.get("/media/{folder}/{filename}")
async def get_uploaded_media(folder: str, filename: str):
    """
    Proxy seguro para servir imágenes de MinIO bajo HTTPS.
    Resuelve el error 'Mixed Content' cuando el frontend se carga con Ngrok/SSL.
    """
    if folder not in ALLOWED_MEDIA_FOLDERS or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=404, detail="Imagen no encontrada o no disponible")
    object_name = f"{folder}/{filename}"
    try:
        # Se envía por partes (64 KB) en vez de cargar la imagen entera en memoria
        obj = await run_storage(minio_service.client.get_object, minio_service.bucket_name, object_name)
    except Exception:
        raise HTTPException(status_code=404, detail="Imagen no encontrada o no disponible")

    ext = filename.split(".")[-1].lower() if "." in filename else "jpg"
    content_type_map = {
        "webp": "image/webp",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "svg": "image/svg+xml",
        "jfif": "image/jpeg"
    }

    def chunks():
        try:
            yield from obj.stream(64 * 1024)
        finally:
            obj.close()
            obj.release_conn()

    headers = {
        "Cache-Control": "public, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff",
        # Si existe algún SVG antiguo, impide que ejecute scripts al abrirse directamente
        "Content-Security-Policy": "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox",
    }
    length = obj.headers.get("Content-Length") if hasattr(obj, "headers") else None
    if length:
        headers["Content-Length"] = str(length)
    return StreamingResponse(chunks(), media_type=content_type_map.get(ext, "image/jpeg"), headers=headers)


# =====================================================================================
#  Subida DIRECTA del navegador a MinIO (la foto no pasa por el backend)
#
#  1) POST /uploads/presign -> el backend firma un formulario que solo permite subir UN archivo,
#     con nombre, tipo (imagen) y tamaño máximo fijados por el servidor (válido 5 min), y
#     devuelve de una vez la URL final.
#  2) El navegador envía la foto a DIRECT_UPLOAD_URL (Nginx la pasa a MinIO) y usa esa URL.
#  Las imágenes se sirven con nosniff + CSP sandbox, así que un archivo que no sea imagen no se
#  puede ejecutar. Si DIRECT_UPLOADS=false (desarrollo) el navegador usa POST /uploads/image.
# =====================================================================================
import uuid as _uuid
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

DIRECT_UPLOADS = os.getenv("DIRECT_UPLOADS", "false").strip().lower() in ("1", "true", "yes", "si", "sí")
DIRECT_UPLOAD_URL = os.getenv("DIRECT_UPLOAD_URL", "/s3-upload")
THUMB_MAX_BYTES = 512 * 1024


class PresignRequest(BaseModel):
    folder: str = "products"
    content_type: str = Field(..., max_length=40)
    size: int = Field(..., ge=1)
    thumb_size: int | None = Field(None, ge=1)   # miniatura de 400 px (opcional, solo webp)


def _post_form(key: str, content_type: str, max_bytes: int) -> dict:
    from minio.datatypes import PostPolicy
    policy = PostPolicy(minio_service.bucket_name, datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5))
    policy.add_equals_condition("key", key)
    policy.add_equals_condition("Content-Type", content_type)
    policy.add_content_length_range_condition(1, max_bytes)
    fields = minio_service.client.presigned_post_policy(policy)   # solo firma (sin llamar a MinIO)
    fields["key"] = key
    fields["Content-Type"] = content_type
    return fields


@router.post("/presign", dependencies=[Depends(rate_limit("upload", 120, 600, by="user"))])
async def presign_upload(data: PresignRequest, current_user: User = Depends(get_required_user)):
    if not DIRECT_UPLOADS:
        return {"direct": False}
    if data.folder not in ALLOWED_UPLOAD_FOLDERS:
        raise HTTPException(status_code=400, detail="Carpeta de destino no permitida.")
    if data.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Solo se aceptan imágenes (JPG, PNG, WEBP, GIF).")
    if data.size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"La imagen excede el límite de {MAX_UPLOAD_MB} MB.")

    ext = ALLOWED_IMAGE_TYPES[data.content_type]
    uid = _uuid.uuid4().hex
    with_thumb = bool(data.thumb_size) and data.folder == "products" and data.thumb_size <= THUMB_MAX_BYTES
    # "-t" en el nombre indica que la imagen tiene miniatura "<nombre>_400.webp" (el front la usa en las tarjetas)
    key = f"{data.folder}/{uid}{'-t' if with_thumb else ''}.{ext}"
    thumb_key = f"{data.folder}/{uid}-t_400.webp" if with_thumb else None
    return {
        "direct": True,
        "upload_url": DIRECT_UPLOAD_URL,
        "fields": _post_form(key, data.content_type, MAX_UPLOAD_BYTES),
        "thumb_fields": _post_form(thumb_key, "image/webp", THUMB_MAX_BYTES) if with_thumb else None,
        "url": minio_service.public_url(key),
        "thumb_url": minio_service.public_url(thumb_key) if with_thumb else None,
    }
