import asyncio
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from app.core.minio_client import minio_service
from app.core.deps import get_required_user
from app.models.all_models import User
from app.core.rate_limit import rate_limit

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

@router.post("/image", dependencies=[Depends(rate_limit("upload", 60, 600))])
async def upload_image(
    file: UploadFile = File(...),
    folder: str = "products",
    current_user: User = Depends(get_required_user)
):
    """Sube una imagen al bucket de MinIO de forma no bloqueante y retorna la URL pública directa"""
    if folder not in ALLOWED_UPLOAD_FOLDERS:
        raise HTTPException(status_code=400, detail="Carpeta de destino no permitida.")

    content_type = file.content_type or "image/jpeg"
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de archivo no permitido: {content_type}. Solo se aceptan imágenes (JPG, PNG, WEBP, GIF)."
        )

    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024: # 10MB limit
        raise HTTPException(
            status_code=400,
            detail="La imagen excede el límite máximo permitido de 10 MB."
        )

    try:
        url = await asyncio.to_thread(
            minio_service.upload_file_bytes,
            file_bytes=file_bytes,
            filename=f"image.{ALLOWED_IMAGE_TYPES[content_type]}",
            content_type=content_type,
            folder=folder
        )
        return {
            "status": "success",
            "url": url,
            "filename": file.filename,
            "size": len(file_bytes)
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al subir imagen a MinIO: {str(e)}"
        )

from fastapi.responses import Response

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
        def fetch_object():
            response = minio_service.client.get_object(minio_service.bucket_name, object_name)
            data = response.read()
            response.close()
            response.release_conn()
            return data

        data = await asyncio.to_thread(fetch_object)
        
        # Determinar Content-Type
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
        content_type = content_type_map.get(ext, "image/jpeg")

        return Response(
            content=data,
            media_type=content_type,
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "X-Content-Type-Options": "nosniff",
                # Si existe algún SVG antiguo, impide que ejecute scripts al abrirse directamente
                "Content-Security-Policy": "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox",
            }
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail="Imagen no encontrada o no disponible")
