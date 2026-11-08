import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select

from common.database import SessionLocal
from common.hubs import gateway_hub, user_hub
from common.models import AssignedNumber, CallSMSLog, Gateway, LogStatus, utcnow
from common.security import hash_gateway_key
from common.services import apply_status, log_payload, status_event_name

router = APIRouter(tags=["gateway websocket"])
log = logging.getLogger("gateway_core.ws")


def _auth_gateway(key: str | None) -> int | None:
    if not key:
        return None
    with SessionLocal() as db:
        gw = db.scalar(select(Gateway).where(Gateway.api_key_hash == hash_gateway_key(key)))
        if gw is None or not gw.is_active:
            return None
        gw.last_seen_at = utcnow()
        db.commit()
        return gw.id


def _touch(gateway_id: int) -> None:
    with SessionLocal() as db:
        gw = db.get(Gateway, gateway_id)
        if gw is not None:
            gw.last_seen_at = utcnow()
            db.commit()


def _apply_result(gateway_id: int, msg: dict):
    """A phone may only report on logs that belong to its own SIMs."""
    try:
        log_id = int(msg["log_id"])
        status = LogStatus(msg["status"])
    except (KeyError, ValueError, TypeError):
        return None
    duration = msg.get("duration_seconds")
    with SessionLocal() as db:
        row = db.scalar(
            select(CallSMSLog)
            .join(AssignedNumber, AssignedNumber.id == CallSMSLog.number_id)
            .where(CallSMSLog.id == log_id, AssignedNumber.gateway_id == gateway_id)
        )
        if row is None:
            return None
        changed = apply_status(db, row, status, duration if isinstance(duration, int) else None)
        return (row.user_id, log_payload(row)) if changed else None


@router.websocket("/ws/gateway")
async def gateway_socket(ws: WebSocket):
    gateway_id = await run_in_threadpool(_auth_gateway, ws.headers.get("x-gateway-key"))
    if gateway_id is None:
        await ws.close(code=4401)
        return
    await ws.accept()
    await gateway_hub.connect(gateway_id, ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
                kind = msg.get("type")
            except (ValueError, AttributeError):
                continue
            if kind == "ping":
                await run_in_threadpool(_touch, gateway_id)
                await ws.send_json({"type": "pong"})
            elif kind == "result":
                result = await run_in_threadpool(_apply_result, gateway_id, msg)
                if result:
                    user_id, payload = result
                    await user_hub.send(
                        user_id, {"event": status_event_name(payload["type"]), "log": payload}
                    )
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("gateway socket error")
    finally:
        gateway_hub.disconnect(gateway_id, ws)
