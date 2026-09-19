import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Set
from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

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
        """Envía el evento solo a los clientes autorizados a verlo."""
        if not self.active_connections:
            return

        payload = jsonable_encoder(message)
        msg_type = payload.get("type", "")
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        dead = []
        for connection, ctx in list(self.active_connections.items()):
            if not _can_receive(ctx, msg_type, data):
                continue
            try:
                await connection.send_json(payload)
            except Exception as e:
                logger.warning(f"Error al enviar mensaje a cliente WebSocket, desconectando: {e}")
                dead.append(connection)

        for d in dead:
            self.disconnect(d)


ws_manager = WebSocketManager()
