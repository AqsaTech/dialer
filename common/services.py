from sqlalchemy.orm import Session

from common.models import CallSMSLog, LogStatus, LogType

FINAL = {
    LogStatus.missed,
    LogStatus.rejected,
    LogStatus.ended,
    LogStatus.failed,
    LogStatus.delivered,
    LogStatus.received,
}
CALL_STATUSES = {
    LogStatus.queued,
    LogStatus.ringing,
    LogStatus.answered,
    LogStatus.missed,
    LogStatus.rejected,
    LogStatus.ended,
    LogStatus.failed,
}
SMS_STATUSES = {
    LogStatus.queued,
    LogStatus.sent,
    LogStatus.delivered,
    LogStatus.received,
    LogStatus.failed,
}


def log_payload(log: CallSMSLog) -> dict:
    return {
        "id": log.id,
        "number_id": log.number_id,
        "type": log.type.value,
        "direction": log.direction.value,
        "status": log.status.value,
        "remote_number": log.remote_number,
        "body": log.body,
        "duration_seconds": log.duration_seconds,
        "created_at": log.created_at.isoformat() + "Z",
    }


def status_event_name(log_type: str) -> str:
    return "call_status" if log_type == LogType.call.value else "sms_status"


def apply_status(db: Session, log: CallSMSLog, status: LogStatus, duration: int | None = None) -> bool:
    """Move a log to a new status. Returns True if something changed.

    Once a log reaches a final status it never changes again, and a call can never get an SMS status.
    """
    allowed = CALL_STATUSES if log.type == LogType.call else SMS_STATUSES
    if status not in allowed or log.status in FINAL or log.status == status:
        return False
    log.status = status
    if duration is not None:
        log.duration_seconds = max(0, int(duration))
    db.commit()
    return True
