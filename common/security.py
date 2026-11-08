import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from common.config import get_settings
from common.models import User

ALGORITHM = "HS256"


class TokenError(Exception):
    pass


# ---- passwords -------------------------------------------------------------
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:  # e.g. password longer than bcrypt's 72-byte limit
        return False


def burn_password_check(password: str) -> None:
    """Spend the same time as a real check so login timing doesn't reveal unknown users."""
    bcrypt.checkpw(password.encode("utf-8")[:72], _DUMMY_HASH)


# ---- tokens ----------------------------------------------------------------
def _key_for(token_type: str) -> str:
    s = get_settings()
    return s.refresh_secret_key if token_type == "refresh" else s.secret_key


def create_token(token_type: str, user: User, lifetime: timedelta) -> tuple[str, str, datetime]:
    """Return (token, jti, expiry as naive UTC). token_type: access | refresh | reset."""
    now = datetime.now(timezone.utc)
    exp = now + lifetime
    jti = uuid.uuid4().hex
    payload = {
        "sub": str(user.id),
        "type": token_type,
        "ver": user.token_version,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    if token_type == "access":
        # Convenience for the UI only. The server always reads the role from the database.
        payload["role"] = user.role.value
    token = jwt.encode(payload, _key_for(token_type), algorithm=ALGORITHM)
    return token, jti, exp.replace(tzinfo=None)


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            _key_for(expected_type),
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub", "jti", "type", "ver"]},
        )
    except jwt.ExpiredSignatureError:
        raise TokenError("Token expired")
    except jwt.InvalidTokenError:
        raise TokenError("Invalid token")
    if payload.get("type") != expected_type:
        raise TokenError("Wrong token type")
    try:
        payload["sub"] = int(payload["sub"])
    except (TypeError, ValueError):
        raise TokenError("Invalid token")
    return payload


def payload_expiry(payload: dict) -> datetime:
    return datetime.fromtimestamp(payload["exp"], timezone.utc).replace(tzinfo=None)


# ---- gateway (phone) keys --------------------------------------------------
def hash_gateway_key(key: str) -> str:
    # Keys are long random strings, so a fast hash is safe and lets us look them up directly.
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_gateway_key() -> tuple[str, str]:
    """Return (key to give the phone once, hash to store)."""
    key = "gw_" + secrets.token_urlsafe(32)
    return key, hash_gateway_key(key)
