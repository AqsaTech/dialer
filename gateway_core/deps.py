from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from common.database import get_db
from common.models import Gateway, utcnow
from common.security import hash_gateway_key


def get_gateway(
    x_gateway_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Gateway:
    """Authenticate a phone by its secret key. Phones never use tenant JWTs."""
    if not x_gateway_key:
        raise HTTPException(status_code=401, detail="Missing gateway key")
    gw = db.scalar(select(Gateway).where(Gateway.api_key_hash == hash_gateway_key(x_gateway_key)))
    if gw is None:
        raise HTTPException(status_code=401, detail="Invalid gateway key")
    if not gw.is_active:
        raise HTTPException(status_code=403, detail="Gateway disabled")
    gw.last_seen_at = utcnow()
    db.commit()
    return gw
