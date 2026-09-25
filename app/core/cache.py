import asyncio
import logging
import time

from app.core import redis_bus
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger("jamuywasi.cache")


def _log_refresh_error(task: "asyncio.Task") -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.warning("No se pudo refrescar la caché: %s", task.exception())


class SimpleTTLCache:
    """
    Caché en memoria con expiración (TTL), pensada para lecturas públicas del catálogo.

    - get_or_compute(): si muchos visitantes piden lo mismo cuando la caché está vacía,
      se consulta la base de datos UNA sola vez y todos reciben ese resultado.
    - mark_stale(): tras un cambio frecuente (p. ej. un producto nuevo) no se borra la copia:
      se sigue sirviendo mientras se recalcula en segundo plano (sin avalancha de consultas).
    - invalidate(): borrado inmediato, para cambios sensibles (suspender/aprobar tiendas).
    """

    def __init__(self, default_ttl_seconds: int = 30):
        self._cache: Dict[str, Any] = {}
        self._expiry: Dict[str, float] = {}
        self._stale: set = set()
        self._inflight: Dict[str, asyncio.Future] = {}
        self._default_ttl = default_ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        if key in self._cache and key not in self._stale:
            if now < self._expiry.get(key, 0):
                return self._cache[key]
            self._cache.pop(key, None)
            self._expiry.pop(key, None)
        return None

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None):
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        self._cache[key] = value
        self._expiry[key] = time.time() + ttl
        self._stale.discard(key)

    def invalidate(self, prefix: Optional[str] = None):
        """Borra en este proceso y avisa a los demás procesos (si hay Redis)."""
        self._invalidate_local(prefix)
        _announce("invalidate", prefix)

    def mark_stale(self, prefix: Optional[str] = None):
        self._mark_stale_local(prefix)
        _announce("stale", prefix)

    def _invalidate_local(self, prefix: Optional[str] = None):
        keys = list(self._cache) if prefix is None else [k for k in self._cache if k.startswith(prefix)]
        for k in keys:
            self._cache.pop(k, None)
            self._expiry.pop(k, None)
            self._stale.discard(k)

    def _mark_stale_local(self, prefix: Optional[str] = None):
        for k in list(self._cache):
            if prefix is None or k.startswith(prefix):
                self._stale.add(k)

    async def _compute(self, key: str, fn: Callable[[], Awaitable[Any]], ttl: Optional[int]) -> Any:
        fut = self._inflight.get(key)
        if fut is not None:
            return await asyncio.shield(fut)
        fut = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            value = await fn()
            self.set(key, value, ttl)
            fut.set_result(value)
            return value
        except BaseException as e:
            if not fut.done():
                fut.set_exception(e)
                fut.exception()  # evita "Future exception was never retrieved"
            raise
        finally:
            self._inflight.pop(key, None)

    async def get_or_compute(self, key: str, fn: Callable[[], Awaitable[Any]], ttl: Optional[int] = None) -> Any:
        now = time.time()
        if key in self._cache:
            fresh = now < self._expiry.get(key, 0) and key not in self._stale
            if fresh:
                return self._cache[key]
            if key in self._stale and now < self._expiry.get(key, 0) + 60:
                # Copia marcada como vieja: se sirve ya y se recalcula en segundo plano (una sola vez)
                if key not in self._inflight:
                    task = asyncio.create_task(self._compute(key, fn, ttl))
                    task.add_done_callback(_log_refresh_error)
                return self._cache[key]
        return await self._compute(key, fn, ttl)


# Instancia global para catálogos y lecturas públicas
catalog_cache = SimpleTTLCache(default_ttl_seconds=30)


def _announce(op: str, prefix: Optional[str]) -> None:
    """Replica la invalidación en los demás procesos del backend."""
    if not redis_bus.enabled():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(redis_bus.publish("cache", {"op": op, "prefix": prefix, "from": redis_bus.WORKER_ID}))


async def _on_redis_cache(msg: dict) -> None:
    if msg.get("from") == redis_bus.WORKER_ID:
        return  # ya se aplicó localmente
    if msg.get("op") == "stale":
        catalog_cache._mark_stale_local(msg.get("prefix"))
    else:
        catalog_cache._invalidate_local(msg.get("prefix"))


redis_bus.subscribe("cache", _on_redis_cache)
