from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from common.database import get_db
from common.models import RevokedToken, Role, User
from common.security import TokenError, decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


@dataclass
class AuthContext:
    user: User
    payload: dict


def resolve_access_token(db: Session, token: str) -> AuthContext | None:
    """Shared by HTTP routes and the browser WebSocket. Returns None for any invalid token."""
    try:
        payload = decode_token(token, "access")
    except TokenError:
        return None
    if db.get(RevokedToken, payload["jti"]) is not None:
        return None
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active or user.token_version != payload["ver"]:
        return None
    return AuthContext(user=user, payload=payload)


def get_auth_context(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> AuthContext:
    ctx = resolve_access_token(db, token)
    if ctx is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return ctx


def get_current_user(ctx: AuthContext = Depends(get_auth_context)) -> User:
    """Use this on every tenant route. The user id always comes from here, never from the request body."""
    return ctx.user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
