from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from common.config import get_settings
from common.database import get_db
from common.hubs import gateway_hub
from common.models import (
    AssignedNumber,
    CallSMSLog,
    Direction,
    Gateway,
    LogStatus,
    LogType,
    User,
    utcnow,
)
from common.services import apply_status
from tenant_core.deps import get_current_user
from tenant_core.schemas import DialRequest, SmsRequest

router = APIRouter(tags=["calls and sms"])


# ---- guards ----------------------------------------------------------------
def _owned_number(db: Session, user: User, number_id: int) -> AssignedNumber:
    num = db.scalar(
        select(AssignedNumber).where(
            AssignedNumber.id == number_id,
            AssignedNumber.user_id == user.id,
            AssignedNumber.is_active.is_(True),
        )
    )
    if num is None:
        raise HTTPException(status_code=404, detail="Number not found")
    return num


def _require_gateway_online(db: Session, num: AssignedNumber) -> None:
    gw = db.get(Gateway, num.gateway_id)
    if gw is None or not gw.is_active or not gateway_hub.is_online(gw.id):
        raise HTTPException(status_code=503, detail="The gateway phone is offline")


def _check_destination(to: str) -> None:
    s = get_settings()
    if any(to.startswith(p) for p in s.blocked_prefix_list):
        raise HTTPException(status_code=403, detail="This destination is blocked")
    allowed = s.allowed_prefix_list
    if allowed and not any(to.startswith(p) for p in allowed):
        raise HTTPException(status_code=403, detail="This destination is not allowed")


def _check_limits(db: Session, user: User, num: AssignedNumber, kind: LogType) -> None:
    s = get_settings()
    now = utcnow()
    per_minute = db.scalar(
        select(func.count()).select_from(CallSMSLog).where(
            CallSMSLog.user_id == user.id,
            CallSMSLog.direction == Direction.outbound,
            CallSMSLog.type == kind,
            CallSMSLog.created_at >= now - timedelta(seconds=60),
        )
    )
    limit = s.max_calls_per_minute if kind == LogType.call else s.max_sms_per_minute
    if per_minute >= limit:
        raise HTTPException(status_code=429, detail="Too many requests. Wait a minute and try again.")
    per_day = db.scalar(
        select(func.count()).select_from(CallSMSLog).where(
            CallSMSLog.number_id == num.id,
            CallSMSLog.direction == Direction.outbound,
            CallSMSLog.created_at >= now - timedelta(hours=24),
        )
    )
    if per_day >= s.max_outbound_per_day:
        raise HTTPException(status_code=429, detail="Daily limit reached for this number")


def _prepare_outbound(db, user, number_id, to, kind, body):
    num = _owned_number(db, user, number_id)
    _check_destination(to)
    _require_gateway_online(db, num)
    _check_limits(db, user, num, kind)
    log = CallSMSLog(
        user_id=user.id,
        number_id=num.id,
        type=kind,
        direction=Direction.outbound,
        status=LogStatus.queued,
        remote_number=to,
        body=body,
    )
    db.add(log)
    db.commit()
    return log, num


async def _send_or_fail(db: Session, log: CallSMSLog, num: AssignedNumber, command: dict) -> None:
    if await gateway_hub.send_command(num.gateway_id, command):
        return
    await run_in_threadpool(apply_status, db, log, LogStatus.failed)
    raise HTTPException(status_code=503, detail="The gateway phone is offline")


# ---- routes ----------------------------------------------------------------
@router.post("/calls/dial", status_code=202)
async def dial(body: DialRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    log, num = await run_in_threadpool(_prepare_outbound, db, user, body.number_id, body.to, LogType.call, None)
    await _send_or_fail(
        db, log, num,
        {"cmd": "dial", "log_id": log.id, "sim_slot": num.sim_slot, "to": body.to},
    )
    return {"log_id": log.id, "status": "queued"}


@router.post("/sms/send", status_code=202)
async def send_sms(body: SmsRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    log, num = await run_in_threadpool(_prepare_outbound, db, user, body.number_id, body.to, LogType.sms, body.body)
    await _send_or_fail(
        db, log, num,
        {"cmd": "sms", "log_id": log.id, "sim_slot": num.sim_slot, "to": body.to, "body": body.body},
    )
    return {"log_id": log.id, "status": "queued"}


def _prepare_control(db: Session, user: User, log_id: int, action: str):
    log = db.scalar(
        select(CallSMSLog).where(
            CallSMSLog.id == log_id,
            CallSMSLog.user_id == user.id,
            CallSMSLog.type == LogType.call,
        )
    )
    if log is None:
        raise HTTPException(status_code=404, detail="Call not found")
    if action in ("answer", "reject"):
        if log.direction != Direction.inbound or log.status != LogStatus.ringing:
            raise HTTPException(status_code=409, detail="This call is not ringing")
    elif log.status not in (LogStatus.queued, LogStatus.ringing, LogStatus.answered):
        raise HTTPException(status_code=409, detail="This call is not active")
    num = db.get(AssignedNumber, log.number_id)
    _require_gateway_online(db, num)
    return log, num


@router.post("/calls/{log_id}/{action}", status_code=202)
async def control_call(
    log_id: int,
    action: Literal["answer", "reject", "hangup"],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    log, num = await run_in_threadpool(_prepare_control, db, user, log_id, action)
    delivered = await gateway_hub.send_command(
        num.gateway_id,
        {
            "cmd": action,
            "log_id": log.id,
            "event_id": log.external_event_id,
            "sim_slot": num.sim_slot,
        },
    )
    if not delivered:
        raise HTTPException(status_code=503, detail="The gateway phone is offline")
    return {"log_id": log.id, "requested": action}
