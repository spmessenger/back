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
        self._socket_users: dict[WebSocket, int] = {}
        self._socket_active_chat: dict[WebSocket, int] = {}
        self._chat_connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[user_id].add(websocket)
        self._socket_users[websocket] = user_id

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        user_connections = self._connections.get(user_id)
        if user_connections is None:
            self._clear_active_chat(websocket)
            self._socket_users.pop(websocket, None)
            return

        user_connections.discard(websocket)
        if not user_connections:
            self._connections.pop(user_id, None)
        self._clear_active_chat(websocket)
        self._socket_users.pop(websocket, None)

    def _clear_active_chat(self, websocket: WebSocket) -> None:
        chat_id = self._socket_active_chat.pop(websocket, None)
        if chat_id is None:
            return
        chat_connections = self._chat_connections.get(chat_id)
        if chat_connections is None:
            return
        chat_connections.discard(websocket)
        if not chat_connections:
            self._chat_connections.pop(chat_id, None)

    def set_active_chat(self, *, user_id: int, websocket: WebSocket, chat_id: int) -> None:
        user_connections = self._connections.get(user_id, set())
        if websocket not in user_connections:
            return
        self._clear_active_chat(websocket)
        self._socket_active_chat[websocket] = chat_id
        self._chat_connections[chat_id].add(websocket)

    def get_connected_user_ids_for_chat(self, chat_id: int) -> set[int]:
        connected_user_ids: set[int] = set()
        for websocket in self._chat_connections.get(chat_id, set()):
            user_id = self._socket_users.get(websocket)
            if user_id is not None:
                connected_user_ids.add(user_id)
        return connected_user_ids

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
