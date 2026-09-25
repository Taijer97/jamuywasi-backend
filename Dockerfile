# ==============================================================
#  JamuyWasi API (FastAPI) — imagen de producción
# ==============================================================
FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencias primero (se cachean mientras requirements.txt no cambie)
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install -r requirements.txt

# Código de la aplicación
COPY app ./app

# Usuario sin privilegios
RUN useradd --create-home --uid 10001 jamuywasi \
 && chown -R jamuywasi:jamuywasi /app
USER jamuywasi

EXPOSE 8000

# Comprueba la API y la conexión a la base de datos
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)" || exit 1

# 1 worker: el WebSocket, la caché y el límite de intentos viven en memoria.
# (Con Redis se podrá subir WEB_CONCURRENCY.)
# --proxy-headers: toma la IP real del visitante desde Nginx (X-Forwarded-For).
# Varios procesos solo si hay Redis (sin Redis los avisos en tiempo real no llegarían a todos)
CMD ["sh", "-c", "W=${WEB_CONCURRENCY:-1}; if [ -z \"$REDIS_URL\" ] && [ \"$W\" -gt 1 ]; then echo 'Sin REDIS_URL: se usa 1 solo proceso'; W=1; fi; exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers $W --proxy-headers --forwarded-allow-ips=${FORWARDED_ALLOW_IPS:-*} --no-server-header"]
