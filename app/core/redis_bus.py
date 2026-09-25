"""
Redis (opcional) para correr VARIOS procesos del backend a la vez.

Sin REDIS_URL todo funciona como antes, en la memoria de un solo proceso.
Con REDIS_URL:
  - los mensajes del WebSocket se reparten a todos los procesos (cada cliente está
    conectado a uno solo de ellos),
  - la caché del catálogo se invalida en todos los procesos,
  - los límites de peticiones se cuentan de forma global,
  - las tareas periódicas corren en un solo proceso (bloqueo).
"""
import asyncio
import json
import logging
import os
import uuid
from typing import Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("jamuywasi.redis")

REDIS_URL = os.getenv("REDIS_URL", "").strip()
PREFIX = os.getenv("REDIS_PREFIX", "jw:")
WORKER_ID = uuid.uuid4().hex[:8]

_client = None
_handlers: Dict[str, List[Callable[[dict], Awaitable[None]]]] = {}
_listener_task: Optional[asyncio.Task] = None
_healthy = False


def enabled() -> bool:
    return bool(REDIS_URL)


def is_healthy() -> bool:
    """True si Redis está configurado y la suscripción está activa."""
    return enabled() and _healthy


def client():
    """Cliente redis.asyncio (o None si no hay REDIS_URL)."""
    global _client
    if not enabled():
        return None
    if _client is None:
        import redis.asyncio as aioredis
        _client = aioredis.from_url(
            REDIS_URL,
            socket_connect_timeout=3,
            socket_timeout=3,
            health_check_interval=30,
            retry_on_timeout=True,
        )
    return _client


def key(*parts: str) -> str:
    return PREFIX + ":".join(parts)


def subscribe(channel: str, handler: Callable[[dict], Awaitable[None]]) -> None:
    """Registra un manejador para los mensajes de un canal (se llama en TODOS los procesos)."""
    _handlers.setdefault(channel, []).append(handler)


async def publish(channel: str, message: dict) -> bool:
    """Publica en Redis. Devuelve False si no se pudo (el llamador hace el reparto local)."""
    r = client()
    if r is None or not _healthy:
        return False
    try:
        await r.publish(key("ch", channel), json.dumps(message, ensure_ascii=False, default=str))
        return True
    except Exception as e:
        logger.warning("No se pudo publicar en Redis (%s): %s", channel, e)
        return False


async def _listen_forever() -> None:
    global _healthy
    delay = 1
    while True:
        pubsub = None
        try:
            r = client()
            pubsub = r.pubsub(ignore_subscribe_messages=True)
            await pubsub.subscribe(*[key("ch", c) for c in _handlers] or [key("ch", "noop")])
            _healthy = True
            delay = 1
            logger.info("Redis conectado (proceso %s)", WORKER_ID)
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                channel = msg["channel"].decode() if isinstance(msg["channel"], bytes) else msg["channel"]
                name = channel[len(key("ch", "")):]
                try:
                    data = json.loads(msg["data"])
                except Exception:
                    continue
                for h in _handlers.get(name, []):
                    try:
                        await h(data)
                    except Exception as e:
                        logger.warning("Error procesando mensaje de Redis (%s): %s", name, e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if _healthy:
                logger.error("Se perdió la conexión con Redis: %s (reintentando)", e)
            _healthy = False
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
        finally:
            _healthy = False
            if pubsub is not None:
                try:
                    await pubsub.aclose()
                except Exception:
                    pass


async def start() -> None:
    """Arranca la escucha de Redis (llamar en el lifespan)."""
    global _listener_task
    if not enabled() or _listener_task is not None:
        return
    _listener_task = asyncio.create_task(_listen_forever())
    # Espera breve para que las primeras publicaciones ya viajen por Redis
    for _ in range(30):
        if _healthy:
            break
        await asyncio.sleep(0.1)
    if not _healthy:
        logger.error("Redis configurado (%s) pero no responde; se usará memoria local hasta que vuelva.", REDIS_URL)


async def stop() -> None:
    global _listener_task, _client
    if _listener_task is not None:
        _listener_task.cancel()
        try:
            await _listener_task
        except (asyncio.CancelledError, Exception):
            pass
        _listener_task = None
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:
            pass
        _client = None


async def acquire_lock(name: str, ttl_seconds: int) -> bool:
    """Bloqueo simple entre procesos. Sin Redis siempre devuelve True (hay un solo proceso)."""
    r = client()
    if r is None:
        return True
    try:
        return bool(await r.set(key("lock", name), WORKER_ID, nx=True, ex=ttl_seconds))
    except Exception as e:
        logger.warning("No se pudo tomar el bloqueo %s en Redis: %s", name, e)
        return True
