import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.database import Base


def utcnow() -> datetime:
    """Naive UTC time. All DateTime columns in this project store UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Role(str, enum.Enum):
    admin = "admin"
    user = "user"


class LogType(str, enum.Enum):
    call = "call"
    sms = "sms"


class Direction(str, enum.Enum):
    inbound = "inbound"
    outbound = "outbound"


class LogStatus(str, enum.Enum):
    # calls
    ringing = "ringing"
    answered = "answered"
    missed = "missed"
    rejected = "rejected"
    ended = "ended"
    # sms
    queued = "queued"
    sent = "sent"
    delivered = "delivered"
    received = "received"
    failed = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.user)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Bumping this number instantly invalidates every token the user holds.
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class Gateway(Base):
    """One physical Android phone that holds SIM cards."""

    __tablename__ = "gateways"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    # SHA-256 of the phone's secret key. The key itself is shown once and never stored.
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    numbers: Mapped[list["AssignedNumber"]] = relationship(back_populates="gateway")


class AssignedNumber(Base):
    """A SIM line (its own phone number) that belongs to exactly one tenant."""

    __tablename__ = "assigned_numbers"
    __table_args__ = (
        UniqueConstraint("gateway_id", "sim_slot", name="uq_gateway_sim_slot"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    gateway_id: Mapped[int] = mapped_column(ForeignKey("gateways.id"), index=True)
    phone_number: Mapped[str] = mapped_column(String(20), unique=True)  # E.164, e.g. +923001234567
    sim_slot: Mapped[int] = mapped_column(Integer)  # 0 or 1 on a dual-SIM phone
    label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User"] = relationship()
    gateway: Mapped["Gateway"] = relationship(back_populates="numbers")


class CallSMSLog(Base):
    __tablename__ = "call_sms_logs"
    __table_args__ = (
        # A retry from the phone with the same event id can never create a second row.
        UniqueConstraint("number_id", "external_event_id", name="uq_log_number_event"),
        Index("ix_logs_user_created", "user_id", "created_at"),
        Index("ix_logs_user_remote", "user_id", "remote_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Copied from the number's owner so tenant queries never need a join to stay isolated.
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    number_id: Mapped[int] = mapped_column(ForeignKey("assigned_numbers.id"), index=True)
    type: Mapped[LogType] = mapped_column(Enum(LogType))
    direction: Mapped[Direction] = mapped_column(Enum(Direction))
    status: Mapped[LogStatus] = mapped_column(Enum(LogStatus))
    remote_number: Mapped[str] = mapped_column(String(32))  # the other person, any country
    body: Mapped[str | None] = mapped_column(Text, nullable=True)  # SMS text
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    number: Mapped["AssignedNumber"] = relationship()
