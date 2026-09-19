"""Límite de peticiones por IP (ventana deslizante en memoria).

Sin dependencias externas. Cada worker de Uvicorn lleva su propia cuenta, así que el
límite efectivo es (límite × nº de workers); para un conteo global exacto usar Redis.
Detrás de Nginx, arrancar Uvicorn con --proxy-headers --forwarded-allow-ips=127.0.0.1
para que request.client.host sea la IP real del visitante.
"""
import time
from collections import defaultdict, deque
from typing import Deque, Dict
from fastapi import HTTPException, Request, status

_hits: Dict[str, Deque[float]] = defaultdict(deque)
_last_cleanup = 0.0


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


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


def rate_limit(name: str, limit: int, window_seconds: int):
    """Dependencia de FastAPI: máx. `limit` peticiones por IP cada `window_seconds`."""

    async def _dependency(request: Request) -> None:
        now = time.monotonic()
        _cleanup(now)
        q = _hits[f"{name}:{_client_ip(request)}"]
        while q and now - q[0] > window_seconds:
            q.popleft()
        if len(q) >= limit:
            retry_after = max(1, int(window_seconds - (now - q[0])))
            minutes = max(1, round(retry_after / 60))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Demasiados intentos. Espera {minutes} minuto(s) e inténtalo de nuevo.",
                headers={"Retry-After": str(retry_after)},
            )
        q.append(now)

    return _dependency
