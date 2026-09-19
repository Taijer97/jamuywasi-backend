import logging
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select, or_
from app.core.database import AsyncSessionLocal
from app.core.security import decode_token
from app.core.websocket_manager import ws_manager, ClientContext
from app.models.all_models import User, Store

logger = logging.getLogger("jamuywasi.websockets")
router = APIRouter(tags=["WebSockets"])


async def _build_context(token: Optional[str]) -> ClientContext:
    """Identifica al usuario a partir del token (?token=...). Sin token => visitante anónimo."""
    if not token:
        return ClientContext()
    payload = decode_token(token)
    if not payload or "sub" not in payload:
        return ClientContext()
    async with AsyncSessionLocal() as db:
        user = await db.get(User, payload["sub"])
        if not user or user.status == "suspended":
            return ClientContext()
        res = await db.execute(
            select(Store.id).where(or_(Store.owner_id == user.id, Store.id == user.store_id))
        )
        store_ids = {row[0] for row in res.all()}
        return ClientContext(user_id=user.id, role=user.role, store_ids=store_ids)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    ctx = await _build_context(websocket.query_params.get("token"))
    await ws_manager.connect(websocket, ctx)
    try:
        while True:
            # Recibe pings del cliente para mantener la conexión viva
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"Excepción en conexión WebSocket: {e}")
        ws_manager.disconnect(websocket)
