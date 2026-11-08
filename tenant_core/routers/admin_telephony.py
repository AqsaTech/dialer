from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from common.database import get_db
from common.hubs import gateway_hub
from common.models import AssignedNumber, Gateway, User
from common.security import generate_gateway_key
from tenant_core.deps import require_admin
from tenant_core.schemas import (
    ActiveUpdate,
    GatewayCreate,
    GatewayCreated,
    GatewayOut,
    NumberAdminOut,
    NumberCreate,
    NumberUpdate,
)

router = APIRouter(
    prefix="/admin",
    tags=["admin: gateways and numbers"],
    dependencies=[Depends(require_admin)],
)


def _gateway_or_404(db: Session, gateway_id: int) -> Gateway:
    gw = db.get(Gateway, gateway_id)
    if gw is None:
        raise HTTPException(status_code=404, detail="Gateway not found")
    return gw


def _active_user_or_error(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="User is disabled")
    return user


# ---- gateways --------------------------------------------------------------
@router.post("/gateways", response_model=GatewayCreated, status_code=201)
def create_gateway(body: GatewayCreate, db: Session = Depends(get_db)):
    if db.scalar(select(Gateway).where(Gateway.name == body.name)) is not None:
        raise HTTPException(status_code=409, detail="Gateway name already exists")
    key, key_hash = generate_gateway_key()
    gw = Gateway(name=body.name, api_key_hash=key_hash)
    db.add(gw)
    db.commit()
    return GatewayCreated(**GatewayOut.model_validate(gw).model_dump(), api_key=key)


@router.get("/gateways", response_model=list[GatewayOut])
def list_gateways(db: Session = Depends(get_db)):
    gateways = db.scalars(select(Gateway).order_by(Gateway.id)).all()
    return [
        GatewayOut.model_validate(g).model_copy(update={"online": gateway_hub.is_online(g.id)})
        for g in gateways
    ]


@router.post("/gateways/{gateway_id}/rotate-key", response_model=GatewayCreated)
def rotate_gateway_key(gateway_id: int, db: Session = Depends(get_db)):
    gw = _gateway_or_404(db, gateway_id)
    key, key_hash = generate_gateway_key()
    gw.api_key_hash = key_hash  # the old key stops working immediately
    db.commit()
    return GatewayCreated(**GatewayOut.model_validate(gw).model_dump(), api_key=key)


@router.patch("/gateways/{gateway_id}/active", response_model=GatewayOut)
def set_gateway_active(gateway_id: int, body: ActiveUpdate, db: Session = Depends(get_db)):
    gw = _gateway_or_404(db, gateway_id)
    gw.is_active = body.is_active
    db.commit()
    return gw


# ---- numbers ---------------------------------------------------------------
@router.post("/numbers", response_model=NumberAdminOut, status_code=201)
def assign_number(body: NumberCreate, db: Session = Depends(get_db)):
    _active_user_or_error(db, body.user_id)
    _gateway_or_404(db, body.gateway_id)
    if db.scalar(select(AssignedNumber).where(AssignedNumber.phone_number == body.phone_number)):
        raise HTTPException(status_code=409, detail="Phone number is already assigned")
    if db.scalar(
        select(AssignedNumber).where(
            AssignedNumber.gateway_id == body.gateway_id,
            AssignedNumber.sim_slot == body.sim_slot,
        )
    ):
        raise HTTPException(status_code=409, detail="That SIM slot on this gateway is already used")
    num = AssignedNumber(**body.model_dump())
    db.add(num)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Number or SIM slot already in use")
    return num


@router.get("/numbers", response_model=list[NumberAdminOut])
def list_numbers(user_id: int | None = None, db: Session = Depends(get_db)):
    stmt = select(AssignedNumber).order_by(AssignedNumber.id)
    if user_id is not None:
        stmt = stmt.where(AssignedNumber.user_id == user_id)
    return db.scalars(stmt).all()


@router.patch("/numbers/{number_id}", response_model=NumberAdminOut)
def update_number(number_id: int, body: NumberUpdate, db: Session = Depends(get_db)):
    num = db.get(AssignedNumber, number_id)
    if num is None:
        raise HTTPException(status_code=404, detail="Number not found")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("user_id") is not None:
        _active_user_or_error(db, changes["user_id"])
        num.user_id = changes["user_id"]  # old logs stay with the previous owner
    if changes.get("is_active") is not None:
        num.is_active = changes["is_active"]
    if "label" in changes:
        num.label = changes["label"]
    db.commit()
    return num
