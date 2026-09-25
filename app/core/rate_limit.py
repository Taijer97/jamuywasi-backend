"""Límite de peticiones por IP (ventana deslizante en memoria).

Sin dependencias externas. Cada worker de Uvicorn lleva su propia cuenta, así que el
límite efectivo es (límite × nº de workers); para un conteo global exacto usar Redis.
Detrás de Nginx, arrancar Uvicorn con --proxy-headers --forwarded-allow-ips=127.0.0.1
para que request.client.host sea la IP real del visitante.
"""
import time
import uuid
from collections import defaultdict, deque
from typing import Deque, Dict
from fastapi import HTTPException, Request, status

from app.core import redis_bus

_hits: Dict[str, Deque[float]] = defaultdict(deque)
_last_cleanup = 0.0


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _client_key(request: Request, by: str) -> str:
    """Clave del contador: IP, o el usuario del token (varios usuarios pueden compartir IP:
    redes móviles con CGNAT, wifi de una feria o centro comercial)."""
    if by == "user":
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            from app.core.security import decode_token
            payload = decode_token(auth[7:].strip())
            if payload and payload.get("sub"):
                return f"u:{payload['sub']}"
    return f"ip:{_client_ip(request)}"


def _cleanup(now: float, max_window: float = 3600.0) -> None:
    global _last_cleanup
    if now - _last_cleanup < 300:
        return
    _last_cleanup = now
    for key in list(_hits.keys()):
        q = _hits[key]
        while q and now - q[0] > max_window:
            q.popleft()
        if not q:
            _hits.pop(key, None)


def rate_limit(name: str, limit: int, window_seconds: int, by: str = "ip"):
    """Dependencia de FastAPI: máx. `limit` peticiones cada `window_seconds`, por IP (by="ip")
    o por usuario autenticado (by="user", con la IP como respaldo si no hay token)."""

    def _too_many(retry_after: int) -> HTTPException:
        minutes = max(1, round(retry_after / 60))
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Demasiados intentos. Espera {minutes} minuto(s) e inténtalo de nuevo.",
            headers={"Retry-After": str(retry_after)},
        )

    async def _dependency(request: Request) -> None:
        client_key = _client_key(request, by)

        # Con Redis el conteo es global (sirve con varios procesos del backend)
        if redis_bus.is_healthy():
            try:
                r = redis_bus.client()
                k = redis_bus.key("rl", name, client_key)
                now_ms = int(time.time() * 1000)
                member = f"{now_ms}-{uuid.uuid4().hex[:6]}"
                async with r.pipeline(transaction=True) as pipe:
                    pipe.zremrangebyscore(k, 0, now_ms - window_seconds * 1000)
                    pipe.zadd(k, {member: now_ms})
                    pipe.zcard(k)
                    pipe.zrange(k, 0, 0, withscores=True)
                    pipe.expire(k, window_seconds + 5)
                    _, _, count, oldest, _ = await pipe.execute()
                if count > limit:
                    await r.zrem(k, member)
                    oldest_ms = int(oldest[0][1]) if oldest else now_ms
                    raise _too_many(max(1, int(window_seconds - (now_ms - oldest_ms) / 1000)))
                return
            except HTTPException:
                raise
            except Exception:
                pass  # Redis caído: se usa el conteo en memoria de este proceso

        now = time.monotonic()
        _cleanup(now)
        q = _hits[f"{name}:{client_key}"]
        while q and now - q[0] > window_seconds:
            q.popleft()
        if len(q) >= limit:
            raise _too_many(max(1, int(window_seconds - (now - q[0]))))
        q.append(now)

    return _dependency
