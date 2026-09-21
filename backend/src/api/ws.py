"""WebSocket live-события KARTA (SPEC S2-03).

Эндпоинт: ``/ws?token=<access JWT>``. События: decision.proposed,
approval.requested, tx.submitted, tx.confirmed, agent.status, provider.degraded.
Доставка — in-process fan-out (Redis pub/sub подключим в S2-04 при use-case).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..config.settings import get_settings
from ..db import UserRepository, session_scope
from ..security.tokens import ACCESS, TokenError, decode_token

logger = logging.getLogger("api.ws")

router = APIRouter()
settings = get_settings()


class ConnectionManager:
    """Fan-out менеджер активных WS-соединений."""

    def __init__(self) -> None:
        self.active: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active.discard(websocket)

    async def broadcast(self, event: dict[str, Any]) -> None:
        if not self.active:
            return
        dead: list[WebSocket] = []
        for websocket in list(self.active):
            try:
                await websocket.send_json(event)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(websocket)

    @property
    def connections(self) -> int:
        return len(self.active)


manager = ConnectionManager()


async def agent_event_sink(event: dict[str, Any]) -> None:
    """Мост runtime→WS: передавать как ``event_sink`` в OnChainAgent."""
    await manager.broadcast(event)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(default="")):
    """Live-канал: аутентификация по access-JWT в query-параметре."""
    try:
        payload = decode_token(token, settings.jwt_secret_key, settings.jwt_algorithm,
                               expected_type=ACCESS)
    except TokenError:
        await websocket.accept()
        await websocket.close(code=4401)
        return

    async with session_scope() as session:
        user = await UserRepository(session).get_by_username(payload.get("sub", ""))
    if user is None:
        await websocket.accept()
        await websocket.close(code=4401)
        return

    await manager.connect(websocket)
    try:
        await websocket.send_json({"type": "hello", "username": user.username})
        while True:
            await websocket.receive_text()  # keepalive/ping; контент игнорируем
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:  # noqa: BLE001 — соединение закрываем при любой ошибке
        logger.warning("WS closed: %s", e)
        manager.disconnect(websocket)
