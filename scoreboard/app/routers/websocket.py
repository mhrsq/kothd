"""
KoTH CTF Platform — WebSocket Router
Real-time scoreboard updates
"""
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.services.ws_manager import ws_manager

logger = logging.getLogger("koth.websocket")

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/scoreboard")
async def ws_scoreboard(websocket: WebSocket, token: str = Query(None)):
    """WebSocket endpoint for live scoreboard updates (optional auth)"""
    # Optional authentication — log whether connection is authenticated
    client_ip = websocket.client.host if websocket.client else "unknown"
    if token:
        from app.config import get_settings
        settings = get_settings()
        if token == settings.api_admin_token:
            logger.info(f"WS scoreboard: admin authenticated from {client_ip}")
        else:
            logger.info(f"WS scoreboard: invalid token from {client_ip}")
    else:
        logger.debug(f"WS scoreboard: unauthenticated from {client_ip}")

    await ws_manager.connect(websocket, "scoreboard")
    try:
        while True:
            # Keep connection alive; receive pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, "scoreboard")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket, "scoreboard")


@router.websocket("/ws/admin")
async def ws_admin(websocket: WebSocket, token: str = Query(None)):
    """WebSocket endpoint for admin panel (requires token)"""
    from app.config import get_settings

    settings = get_settings()
    if token != settings.api_admin_token:
        await websocket.close(code=4003, reason="Unauthorized")
        return

    await ws_manager.connect(websocket, "admin")
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, "admin")
    except Exception:
        ws_manager.disconnect(websocket, "admin")
