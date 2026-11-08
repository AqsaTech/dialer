from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from common.database import get_db
from common.models import User
from common.security import hash_password
from tenant_core.deps import require_admin
from tenant_core.schemas import ActiveUpdate, Message, SetPassword, UserCreate, UserOut

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    email = body.email.lower()
    taken = db.scalar(select(User).where(or_(User.email == email, User.username == body.username)))
    if taken is not None:
        raise HTTPException(status_code=409, detail="Username or email already exists")
    user = User(
        username=body.username,
        email=email,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username or email already exists")
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.id)).all()


@router.patch("/users/{user_id}/active", response_model=UserOut)
def set_active(
    user_id: int,
    body: ActiveUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id and not body.is_active:
        raise HTTPException(status_code=400, detail="You cannot disable your own account")
    user.is_active = body.is_active
    if not body.is_active:
        user.token_version += 1  # kicks the user out immediately
    db.commit()
    return user


@router.post("/users/{user_id}/password", response_model=Message)
def set_user_password(
    user_id: int,
    body: SetPassword,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """For tenants who forgot their password when email is not set up. Also unlocks the account."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # signs the user out everywhere
    user.failed_logins = 0
    user.locked_until = None
    db.commit()
    return Message(message="Password updated")
