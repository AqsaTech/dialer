import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer, field_validator

from common.models import Direction, LogStatus, LogType, Role
from common.phone import normalize_phone


def check_password_rules(value: str) -> str:
    if len(value) < 10:
        raise ValueError("Password must be at least 10 characters")
    if len(value.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 bytes")
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValueError("Password must contain letters and digits")
    return value


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    email: EmailStr
    password: str
    role: Role = Role.user

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return check_password_rules(v)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    role: Role
    is_active: bool


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class ForgotPassword(BaseModel):
    email: EmailStr


class ResetPassword(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password(cls, v: str) -> str:
        return check_password_rules(v)


class ChangePassword(BaseModel):
    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password(cls, v: str) -> str:
        return check_password_rules(v)


class SetPassword(BaseModel):
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password(cls, v: str) -> str:
        return check_password_rules(v)


class ActiveUpdate(BaseModel):
    is_active: bool


class Message(BaseModel):
    message: str


# ---- gateways and numbers --------------------------------------------------
class GatewayCreate(BaseModel):
    name: str = Field(min_length=3, max_length=50)


class GatewayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool
    last_seen_at: datetime | None
    created_at: datetime
    online: bool = False

    @field_serializer("last_seen_at", "created_at", when_used="json")
    def _utc(self, v: datetime | None) -> str | None:
        return v.isoformat() + "Z" if v else None


class GatewayCreated(GatewayOut):
    api_key: str  # shown once


class NumberCreate(BaseModel):
    user_id: int
    gateway_id: int
    phone_number: str
    sim_slot: int = Field(ge=0, le=1)
    label: str | None = Field(default=None, max_length=50)

    @field_validator("phone_number")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_phone(v)


class NumberUpdate(BaseModel):
    user_id: int | None = None
    is_active: bool | None = None
    label: str | None = Field(default=None, max_length=50)


class NumberAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    gateway_id: int
    phone_number: str
    sim_slot: int
    label: str | None
    is_active: bool


class NumberOut(BaseModel):
    """What a tenant sees: no gateway or slot details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    phone_number: str
    label: str | None


# ---- logs and actions ------------------------------------------------------
class LogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number_id: int
    type: LogType
    direction: Direction
    status: LogStatus
    remote_number: str
    body: str | None
    duration_seconds: int | None
    created_at: datetime

    @field_serializer("created_at", when_used="json")
    def _utc(self, v: datetime) -> str:
        return v.isoformat() + "Z"


class LogPage(BaseModel):
    items: list[LogOut]
    next_before_id: int | None = None


class DialRequest(BaseModel):
    number_id: int
    to: str

    @field_validator("to")
    @classmethod
    def _to(cls, v: str) -> str:
        return normalize_phone(v)


class SmsRequest(BaseModel):
    number_id: int
    to: str
    body: str = Field(min_length=1, max_length=1000)

    @field_validator("to")
    @classmethod
    def _to(cls, v: str) -> str:
        return normalize_phone(v)
