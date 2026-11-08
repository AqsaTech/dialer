"""Live connections. In-memory, so run ONE uvicorn worker.

If you later split the two cores into separate processes, replace these two classes with
Redis pub/sub. Nothing else in the code needs to change.
"""
from collections import defaultdict

from fastapi import WebSocket


class UserHub:
    """Browsers, grouped by tenant. A tenant may have several tabs open."""

    def __init__(self) -> None:
        self._sockets: dict[int, set[WebSocket]] = defaultdict(set)

    def add(self, user_id: int, ws: WebSocket) -> None:
        self._sockets[user_id].add(ws)

    def remove(self, user_id: int, ws: WebSocket) -> None:
        self._sockets[user_id].discard(ws)
        if not self._sockets[user_id]:
            self._sockets.pop(user_id, None)

    async def send(self, user_id: int, event: dict) -> None:
        for ws in list(self._sockets.get(user_id, ())):
            try:
                await ws.send_json(event)
            except Exception:
                self.remove(user_id, ws)


class GatewayHub:
    """Android phones. One live connection per gateway."""

    def __init__(self) -> None:
        self._sockets: dict[int, WebSocket] = {}

    async def connect(self, gateway_id: int, ws: WebSocket) -> None:
        old = self._sockets.get(gateway_id)
        self._sockets[gateway_id] = ws
        if old is not None:
            try:
                await old.close(code=4000)
            except Exception:
                pass

    def disconnect(self, gateway_id: int, ws: WebSocket) -> None:
        if self._sockets.get(gateway_id) is ws:
            del self._sockets[gateway_id]

    def is_online(self, gateway_id: int) -> bool:
        return gateway_id in self._sockets

    async def send_command(self, gateway_id: int, command: dict) -> bool:
        ws = self._sockets.get(gateway_id)
        if ws is None:
            return False
        try:
            await ws.send_json(command)
            return True
        except Exception:
            self.disconnect(gateway_id, ws)
            return False


user_hub = UserHub()
gateway_hub = GatewayHub()
