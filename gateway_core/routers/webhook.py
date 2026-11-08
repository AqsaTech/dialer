from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from common.database import get_db
from common.hubs import user_hub
from common.models import (
    AssignedNumber,
    CallSMSLog,
    Direction,
    Gateway,
    LogStatus,
    LogType,
)
from common.services import apply_status, log_payload
from gateway_core.deps import get_gateway
from gateway_core.schemas import CallStatusEvent, IncomingCall, IncomingSms

router = APIRouter(prefix="/webhook", tags=["gateway webhooks"])


def _number_for_slot(db: Session, gw: Gateway, slot: int) -> AssignedNumber | None:
    return db.scalar(
        select(AssignedNumber).where(
            AssignedNumber.gateway_id == gw.id,
            AssignedNumber.sim_slot == slot,
            AssignedNumber.is_active.is_(True),
        )
    )


def _existing(db: Session, number_id: int, event_id: str) -> CallSMSLog | None:
    return db.scalar(
        select(CallSMSLog).where(
            CallSMSLog.number_id == number_id,
            CallSMSLog.external_event_id == event_id,
        )
    )


def _save_event(db, gw, slot, event_id, log_type, status, remote, body):
    """Return (log, created). log is None when the SIM slot is not assigned to anyone."""
    num = _number_for_slot(db, gw, slot)
    if num is None:
        return None, False
    found = _existing(db, num.id, event_id)
    if found is not None:
        return found, False  # the phone retried; do not create a second row
    log = CallSMSLog(
        user_id=num.user_id,
        number_id=num.id,
        type=log_type,
        direction=Direction.inbound,
        status=status,
        remote_number=remote,
        body=body,
        external_event_id=event_id,
    )
    db.add(log)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _existing(db, num.id, event_id), False
    return log, True


@router.post("/incoming-call")
async def incoming_call(evt: IncomingCall, gw: Gateway = Depends(get_gateway), db: Session = Depends(get_db)):
    log, created = await run_in_threadpool(
        _save_event, db, gw, evt.sim_slot, evt.event_id,
        LogType.call, LogStatus.ringing, evt.remote_number, None,
    )
    if log is None:
        return {"ok": True, "ignored": True}  # unmapped SIM: not our customer's line
    if created:
        await user_hub.send(log.user_id, {"event": "incoming_call", "log": log_payload(log)})
    return {"ok": True, "log_id": log.id, "duplicate": not created}


@router.post("/incoming-sms")
async def incoming_sms(evt: IncomingSms, gw: Gateway = Depends(get_gateway), db: Session = Depends(get_db)):
    log, created = await run_in_threadpool(
        _save_event, db, gw, evt.sim_slot, evt.event_id,
        LogType.sms, LogStatus.received, evt.remote_number, evt.body,
    )
    if log is None:
        return {"ok": True, "ignored": True}
    if created:
        await user_hub.send(log.user_id, {"event": "incoming_sms", "log": log_payload(log)})
    return {"ok": True, "log_id": log.id, "duplicate": not created}


def _update_call(db: Session, gw: Gateway, evt: CallStatusEvent):
    num = _number_for_slot(db, gw, evt.sim_slot)
    if num is None:
        return None
    log = _existing(db, num.id, evt.event_id)
    if log is None or log.type != LogType.call:
        return None
    changed = apply_status(db, log, LogStatus(evt.status), evt.duration_seconds)
    return (log.user_id, log_payload(log)) if changed else None


@router.post("/call-status")
async def call_status(evt: CallStatusEvent, gw: Gateway = Depends(get_gateway), db: Session = Depends(get_db)):
    result = await run_in_threadpool(_update_call, db, gw, evt)
    if result:
        user_id, payload = result
        await user_hub.send(user_id, {"event": "call_status", "log": payload})
    return {"ok": True}
