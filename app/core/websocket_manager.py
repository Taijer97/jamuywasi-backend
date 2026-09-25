import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Set
from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder
from app.core.utc_json import mark_utc
from app.core import redis_bus

logger = logging.getLogger("jamuywasi.websockets")

# Eventos que cualquier visitante del catálogo puede recibir (datos públicos).
PUBLIC_EVENTS = {
    "PRODUCT_CREATED", "PRODUCT_UPDATED", "PRODUCT_DELETED",
    "BANNER_CREATED", "BANNER_UPDATED", "BANNER_DELETED",
    "STORE_CREATED", "STORE_UPDATED", "STORE_DELETED",
    "PAYMENT_CONFIG_UPDATED",
}
# Eventos de pedidos: solo el dueño de la tienda (y el superadmin).
STORE_EVENTS = {"ORDER_CREATED", "ORDER_UPDATED"}
# Eventos con datos personales de un usuario: solo ese usuario (y el superadmin).
USER_EVENTS = {"USER_UPDATED", "USER_DELETED", "PAYMENT_VERIFIED", "PIN_RESET_COMPLETED"}
# Cualquier otro evento (USER_REGISTERED, PIN_RESET_REQUESTED, PROMO_CODE_*, ...) => solo superadmin.


@dataclass
class ClientContext:
    user_id: Optional[str] = None
    role: Optional[str] = None
    store_ids: Set[str] = field(default_factory=set)

    @property
    def is_superadmin(self) -> bool:
        return self.role == "superadmin"


def _can_receive(ctx: ClientContext, msg_type: str, data: dict) -> bool:
    if ctx.is_superadmin or msg_type in PUBLIC_EVENTS:
        return True
    if not ctx.user_id:
        return False
    if msg_type in STORE_EVENTS:
        return data.get("store_id") in ctx.store_ids
    if msg_type in USER_EVENTS:
        return ctx.user_id in (data.get("id"), data.get("user_id"))
    return False


class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[WebSocket, ClientContext] = {}

    async def connect(self, websocket: WebSocket, ctx: Optional[ClientContext] = None):
        await websocket.accept()
        self.active_connections[websocket] = ctx or ClientContext()
        logger.info(f"Cliente WebSocket conectado. Total activos: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if self.active_connections.pop(websocket, None) is not None:
            logger.info(f"Cliente WebSocket desconectado. Total activos: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Envía el evento a los clientes autorizados, en TODOS los procesos del backend (vía Redis)."""
        payload = mark_utc(jsonable_encoder(message))
        if await redis_bus.publish("ws", {"kind": "broadcast", "payload": payload}):
            return  # cada proceso (incluido este) lo entrega a sus propios clientes al recibirlo
        await self._deliver_broadcast(payload)

    async def _deliver_broadcast(self, payload: dict):
        """Entrega a los clientes conectados a ESTE proceso."""
        if not self.active_connections:
            return
        msg_type = payload.get("type", "")
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        targets = [c for c, ctx in list(self.active_connections.items()) if _can_receive(ctx, msg_type, data)]
        if not targets:
            return

        async def _send(connection: WebSocket):
            # Envío en paralelo y con tiempo máximo: un cliente con mala señal no retrasa a los demás
            try:
                await asyncio.wait_for(connection.send_json(payload), timeout=5)
                return None
            except Exception as e:
                logger.warning(f"Error al enviar mensaje a cliente WebSocket, desconectando: {e}")
                return connection

        results = await asyncio.gather(*(_send(c) for c in targets))
        for dead in results:
            if dead is not None:
                self.disconnect(dead)
                try:
                    await dead.close()
                except Exception:
                    pass


    async def send_to_users(self, user_ids, message: dict):
        """Envía un evento solo a las conexiones de esos usuarios (p. ej. una notificación)."""
        ids = [str(u) for u in set(user_ids) if u]
        if not ids:
            return
        payload = mark_utc(jsonable_encoder(message))
        if await redis_bus.publish("ws", {"kind": "users", "ids": ids, "payload": payload}):
            return
        await self._deliver_to_users(set(ids), payload)

    async def _deliver_to_users(self, ids: set, payload: dict):
        if not ids or not self.active_connections:
            return
        targets = [c for c, ctx in list(self.active_connections.items()) if ctx.user_id in ids]

        async def _send(connection: WebSocket):
            try:
                await asyncio.wait_for(connection.send_json(payload), timeout=5)
            except Exception:
                self.disconnect(connection)

        await asyncio.gather(*(_send(c) for c in targets))


ws_manager = WebSocketManager()


async def _on_redis_ws(msg: dict) -> None:
    if msg.get("kind") == "broadcast":
        await ws_manager._deliver_broadcast(msg.get("payload") or {})
    elif msg.get("kind") == "users":
        await ws_manager._deliver_to_users(set(msg.get("ids") or []), msg.get("payload") or {})


redis_bus.subscribe("ws", _on_redis_ws)
