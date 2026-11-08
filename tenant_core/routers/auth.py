from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from common.config import get_settings
from common.database import get_db
from common.models import RevokedToken, User, utcnow
from common.security import (
    TokenError,
    burn_password_check,
    create_token,
    decode_token,
    hash_password,
    payload_expiry,
    verify_password,
)
from tenant_core.deps import AuthContext, get_auth_context, get_current_user
from tenant_core.email_utils import send_reset_email
from tenant_core.schemas import (
    ChangePassword,
    ForgotPassword,
    LogoutRequest,
    Message,
    RefreshRequest,
    ResetPassword,
    TokenPair,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])

BAD_LOGIN = "Invalid username or password"


def _issue_pair(user: User) -> TokenPair:
    s = get_settings()
    access, _, _ = create_token("access", user, timedelta(minutes=s.access_token_minutes))
    refresh, _, _ = create_token("refresh", user, timedelta(days=s.refresh_token_days))
    return TokenPair(access_token=access, refresh_token=refresh)


def _revoke(db: Session, jti: str, user_id: int, expires_at: datetime) -> None:
    if db.get(RevokedToken, jti) is None:
        db.add(RevokedToken(jti=jti, user_id=user_id, expires_at=expires_at))


@router.post("/login", response_model=TokenPair)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    s = get_settings()
    ident = form.username.strip()
    user = db.scalar(select(User).where(or_(User.email == ident.lower(), User.username == ident)))

    if user is None:
        burn_password_check(form.password)
        raise HTTPException(status_code=401, detail=BAD_LOGIN)

    now = utcnow()
    if user.locked_until and user.locked_until > now:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")

    if not verify_password(form.password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= s.max_failed_logins:
            user.locked_until = now + timedelta(minutes=s.lockout_minutes)
            user.failed_logins = 0
        db.commit()
        raise HTTPException(status_code=401, detail=BAD_LOGIN)

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled. Contact the administrator.")

    user.failed_logins = 0
    user.locked_until = None
    db.commit()
    return _issue_pair(user)


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token, "refresh")
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    if db.get(RevokedToken, payload["jti"]) is not None:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active or user.token_version != payload["ver"]:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Rotation: each refresh token works once.
    _revoke(db, payload["jti"], user.id, payload_expiry(payload))
    db.commit()
    return _issue_pair(user)


@router.post("/logout", response_model=Message)
def logout(
    body: LogoutRequest | None = None,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    _revoke(db, ctx.payload["jti"], ctx.user.id, payload_expiry(ctx.payload))
    if body and body.refresh_token:
        try:
            rp = decode_token(body.refresh_token, "refresh")
            if rp["sub"] == ctx.user.id:
                _revoke(db, rp["jti"], ctx.user.id, payload_expiry(rp))
        except TokenError:
            pass
    db.commit()
    return Message(message="Logged out")


@router.post("/logout-all", response_model=Message)
def logout_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.token_version += 1
    db.commit()
    return Message(message="Logged out from all devices")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/change-password", response_model=Message)
def change_password(
    body: ChangePassword,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Old password is incorrect")
    if body.old_password == body.new_password:
        raise HTTPException(status_code=400, detail="New password must be different")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # ends every existing session
    db.commit()
    return Message(message="Password changed. Please log in again.")


@router.post("/forgot-password", response_model=Message)
def forgot_password(body: ForgotPassword, background: BackgroundTasks, db: Session = Depends(get_db)):
    s = get_settings()
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is not None and user.is_active:
        token, _, _ = create_token("reset", user, timedelta(minutes=s.reset_token_minutes))
        background.add_task(send_reset_email, user.email, token)
    # Same answer whether or not the email exists.
    return Message(message="If that email is registered, a reset link has been sent.")


@router.post("/reset-password", response_model=Message)
def reset_password(body: ResetPassword, db: Session = Depends(get_db)):
    try:
        payload = decode_token(body.token, "reset")
    except TokenError:
        raise HTTPException(status_code=400, detail="Reset link is invalid or expired")
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active or user.token_version != payload["ver"]:
        raise HTTPException(status_code=400, detail="Reset link is invalid or expired")

    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # makes this reset link single-use and ends old sessions
    user.failed_logins = 0
    user.locked_until = None
    db.commit()
    return Message(message="Password reset. You can log in now.")
