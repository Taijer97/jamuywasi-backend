"""Evita que recargar la página (o repetir la misma petición) infle las vistas de un producto.

Cuenta como "vista orgánica" una sola vez por (IP, producto) dentro de una ventana de tiempo.
Con Redis el filtro es global entre procesos (SET NX EX, atómico); sin Redis cada proceso
lleva su propio registro en memoria y se reinicia si el proceso se reinicia — misma
limitación ya documentada en core/rate_limit.py para los límites de peticiones.

Esto se hace en el backend a propósito: cualquiera puede llamar al endpoint público
directo (sin pasar por la web), así que el control del lado del cliente no sirve de nada.
"""
import time
from typing import Dict
from fastapi import Request
from app.core import redis_bus

# Una vista por visitante por producto dentro de esta ventana cuenta como "orgánica".
# 12 horas: alguien que vuelve a mirar el mismo producto al día siguiente sí suma una
# vista nueva, pero recargar la página o abrir el link varias veces seguidas no infla el contador.
VIEW_DEDUP_WINDOW_SECONDS = 12 * 60 * 60

_seen: Dict[str, float] = {}
_last_cleanup = 0.0


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _cleanup(now: float) -> None:
    global _last_cleanup
    if now - _last_cleanup < 300:
        return
    _last_cleanup = now
    for k, expires_at in list(_seen.items()):
        if expires_at <= now:
            _seen.pop(k, None)


async def register_view(request: Request, product_id: str, window_seconds: int = VIEW_DEDUP_WINDOW_SECONDS) -> bool:
    """Devuelve True solo la primera vez que esta IP visita este producto dentro de la ventana
    (esa es la única vez que se debe incrementar el contador)."""
    dedup_key = f"{_client_ip(request)}:{product_id}"

    if redis_bus.is_healthy():
        try:
            r = redis_bus.client()
            k = redis_bus.key("view", dedup_key)
            was_new = await r.set(k, "1", nx=True, ex=window_seconds)
            return bool(was_new)
        except Exception:
            pass  # Redis caído: se usa el registro en memoria de este proceso

    now = time.monotonic()
    _cleanup(now)
    expires_at = _seen.get(dedup_key)
    if expires_at and expires_at > now:
        return False
    _seen[dedup_key] = now + window_seconds
    return True
