from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from common.database import get_db
from common.models import CallSMSLog, Direction, LogStatus, LogType, User
from tenant_core.deps import get_current_user
from tenant_core.schemas import LogOut, LogPage

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("", response_model=LogPage)
def list_logs(
    type: LogType | None = None,
    direction: Direction | None = None,
    status: LogStatus | None = None,
    number_id: int | None = None,
    remote_number: str | None = Query(default=None, max_length=64),
    before_id: int | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # user_id comes from the verified token. It is the first and mandatory filter.
    stmt = select(CallSMSLog).where(CallSMSLog.user_id == user.id)
    if type is not None:
        stmt = stmt.where(CallSMSLog.type == type)
    if direction is not None:
        stmt = stmt.where(CallSMSLog.direction == direction)
    if status is not None:
        stmt = stmt.where(CallSMSLog.status == status)
    if number_id is not None:
        stmt = stmt.where(CallSMSLog.number_id == number_id)
    if remote_number:
        stmt = stmt.where(CallSMSLog.remote_number == remote_number.strip())
    if before_id is not None:
        stmt = stmt.where(CallSMSLog.id < before_id)
    rows = list(db.scalars(stmt.order_by(CallSMSLog.id.desc()).limit(limit + 1)).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    return LogPage(items=rows, next_before_id=rows[-1].id if has_more and rows else None)


@router.get("/{log_id}", response_model=LogOut)
def get_log(log_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(CallSMSLog).where(CallSMSLog.id == log_id, CallSMSLog.user_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Log not found")
    return row
