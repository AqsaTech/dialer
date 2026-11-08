from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from common.database import get_db
from common.models import AssignedNumber, User
from tenant_core.deps import get_current_user
from tenant_core.schemas import NumberOut

router = APIRouter(prefix="/numbers", tags=["numbers"])


def _mine():
    """Base filter for tenant queries: the owner always comes from the verified token."""
    return select(AssignedNumber)


@router.get("", response_model=list[NumberOut])
def my_numbers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = (
        _mine()
        .where(AssignedNumber.user_id == user.id, AssignedNumber.is_active.is_(True))
        .order_by(AssignedNumber.id)
    )
    return db.scalars(stmt).all()


@router.get("/{number_id}", response_model=NumberOut)
def my_number(number_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = _mine().where(
        AssignedNumber.id == number_id,
        AssignedNumber.user_id == user.id,
        AssignedNumber.is_active.is_(True),
    )
    num = db.scalar(stmt)
    if num is None:
        # 404 (not 403) so we never confirm that another tenant's number exists.
        raise HTTPException(status_code=404, detail="Number not found")
    return num
