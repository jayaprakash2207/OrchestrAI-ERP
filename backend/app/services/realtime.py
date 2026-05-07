from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class WebSocketHub:
    def __init__(self) -> None:
        self.connections: dict[str, list[WebSocket]] = defaultdict(list)
        self.lock = asyncio.Lock()

    async def connect(self, channel: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self.lock:
            self.connections[channel].append(websocket)

    async def disconnect(self, channel: str, websocket: WebSocket) -> None:
        async with self.lock:
            if channel in self.connections and websocket in self.connections[channel]:
                self.connections[channel].remove(websocket)
            if channel in self.connections and not self.connections[channel]:
                self.connections.pop(channel, None)

    async def broadcast(self, channel: str, message: dict[str, Any]) -> None:
        sockets = list(self.connections.get(channel, []))
        for socket in sockets:
            try:
                await socket.send_json(message)
            except Exception:
                await self.disconnect(channel, socket)


websocket_hub = WebSocketHub()
