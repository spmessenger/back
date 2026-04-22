from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any
import logging

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect


logger = logging.getLogger(__name__)


class WebSocketConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[user_id].add(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        user_connections = self._connections.get(user_id)
        if user_connections is None:
            return

        user_connections.discard(websocket)
        if not user_connections:
            self._connections.pop(user_id, None)

    async def send_to_user(self, user_id: int, payload: Mapping[str, Any]) -> None:
        user_connections = list(self._connections.get(user_id, set()))

        for websocket in user_connections:
            try:
                await websocket.send_json(dict(payload))
            except (WebSocketDisconnect, RuntimeError):
                self.disconnect(user_id=user_id, websocket=websocket)
            except OSError:
                self.disconnect(user_id=user_id, websocket=websocket)
            except ValueError:
                logger.exception("Invalid websocket payload for user_id=%s", user_id)
                self.disconnect(user_id=user_id, websocket=websocket)

    def has_user_connections(self, user_id: int) -> bool:
        return bool(self._connections.get(user_id))
