import asyncio
import json
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from common.config import get_settings
from common.database import SessionLocal
from common.hubs import user_hub
from tenant_core.deps import resolve_access_token

router = APIRouter(tags=["browser websocket"])

RECHECK_SECONDS = 60


def _authenticate(token: str | None):
    if not token:
        return None
    with SessionLocal() as db:
        ctx = resolve_access_token(db, token)
        if ctx is None:
            return None
        return ctx.user.id, int(ctx.payload["exp"])


@router.websocket("/ws/events")
async def events(ws: WebSocket):
    """Browsers cannot send an Authorization header, so the first message carries the token.

    The token never appears in the URL, and so never lands in server or proxy logs.
    """
    await ws.accept()
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=get_settings().ws_auth_timeout_seconds)
        msg = json.loads(raw)
        token = msg.get("token") if msg.get("type") == "auth" else None
    except (asyncio.TimeoutError, ValueError, AttributeError, WebSocketDisconnect):
        await _close(ws)
        return

    auth = await run_in_threadpool(_authenticate, token)
    if auth is None:
        await _close(ws)
        return
    user_id, exp = auth

    user_hub.add(user_id, ws)
    try:
        await ws.send_json({"event": "ready"})
        while True:
            remaining = exp - time.time()
            if remaining <= 0:
                await _close(ws)  # token expired: the page refreshes it and reconnects
                return
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=min(remaining, RECHECK_SECONDS))
            except asyncio.TimeoutError:
                # Re-check so a logout or a disabled account closes the socket within a minute.
                if await run_in_threadpool(_authenticate, token) is None:
                    await _close(ws)
                    return
                continue
            if raw == "ping":
                await ws.send_text("pong")
    except (WebSocketDisconnect, KeyError, RuntimeError):
        pass  # the browser went away, or sent something that is not text
    finally:
        user_hub.remove(user_id, ws)


async def _close(ws: WebSocket) -> None:
    try:
        await ws.close(code=4401)
    except Exception:
        pass
