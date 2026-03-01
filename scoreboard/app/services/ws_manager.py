"""
KoTH CTF Platform — WebSocket Connection Manager
Manages real-time connections for live scoreboard updates
"""
import json
import logging
from typing import Dict, Set
from datetime import datetime
from fastapi import WebSocket

logger = logging.getLogger("koth.websocket")


class ConnectionManager:
    """Manages WebSocket connections for live scoreboard updates"""

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {
            "scoreboard": set(),
            "admin": set(),
        }

    async def connect(self, websocket: WebSocket, channel: str = "scoreboard"):
        await websocket.accept()
        if channel not in self.active_connections:
            self.active_connections[channel] = set()
        self.active_connections[channel].add(websocket)
        logger.info(
            f"WebSocket connected: {channel} "
            f"(total: {len(self.active_connections[channel])})"
        )

    def disconnect(self, websocket: WebSocket, channel: str = "scoreboard"):
        if channel in self.active_connections:
            self.active_connections[channel].discard(websocket)
            logger.info(
                f"WebSocket disconnected: {channel} "
                f"(total: {len(self.active_connections[channel])})"
            )

    async def broadcast(self, message: dict, channel: str = "scoreboard"):
        """Broadcast message to all connections in a channel"""
        if channel not in self.active_connections:
            return

        dead_connections = set()
        payload = json.dumps(message, default=str)

        for connection in self.active_connections[channel]:
            try:
                await connection.send_text(payload)
            except Exception:
                dead_connections.add(connection)

        # Clean up dead connections
        for conn in dead_connections:
            self.active_connections[channel].discard(conn)

    async def broadcast_all(self, message: dict):
        """Broadcast to all channels"""
        for channel in self.active_connections:
            await self.broadcast(message, channel)

    async def broadcast_tick_update(self, tick_data: dict):
        """Broadcast tick update to scoreboard channel"""
        await self.broadcast({
            "type": "tick_update",
            "data": tick_data,
            "timestamp": datetime.utcnow().isoformat(),
        }, "scoreboard")

    async def broadcast_king_change(self, change_data: dict):
        """Broadcast king change event"""
        await self.broadcast_all({
            "type": "king_change",
            "data": change_data,
            "timestamp": datetime.utcnow().isoformat(),
        })

    async def broadcast_first_blood(self, fb_data: dict):
        """Broadcast first blood event"""
        await self.broadcast_all({
            "type": "first_blood",
            "data": fb_data,
            "timestamp": datetime.utcnow().isoformat(),
        })

    async def broadcast_game_event(self, event: str, details: dict = None):
        """Broadcast game lifecycle events"""
        await self.broadcast_all({
            "type": "game_event",
            "data": {"event": event, "details": details or {}},
            "timestamp": datetime.utcnow().isoformat(),
        })

    @property
    def connection_count(self) -> int:
        return sum(len(conns) for conns in self.active_connections.values())


# Global singleton
ws_manager = ConnectionManager()
