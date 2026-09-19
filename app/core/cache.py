import time
from typing import Any, Optional, Dict

class SimpleTTLCache:
    """
    Caché en memoria ultraligero con expiración TTL (Time-To-Live).
    Permite responder miles de peticiones por segundo sin saturar la base de datos.
    """
    def __init__(self, default_ttl_seconds: int = 30):
        self._cache: Dict[str, Any] = {}
        self._expiry: Dict[str, float] = {}
        self._default_ttl = default_ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        if key in self._cache:
            if now < self._expiry.get(key, 0):
                return self._cache[key]
            # Expirado
            self._cache.pop(key, None)
            self._expiry.pop(key, None)
        return None

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None):
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        self._cache[key] = value
        self._expiry[key] = time.time() + ttl

    def invalidate(self, prefix: Optional[str] = None):
        if prefix is None:
            self._cache.clear()
            self._expiry.clear()
        else:
            keys_to_del = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_del:
                self._cache.pop(k, None)
                self._expiry.pop(k, None)

# Instancia global para catálogos y lecturas públicas
catalog_cache = SimpleTTLCache(default_ttl_seconds=30)
