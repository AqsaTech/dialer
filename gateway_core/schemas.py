from typing import Literal

from pydantic import BaseModel, Field, field_validator

from common.phone import clean_remote


class _Event(BaseModel):
    # The SIM slot is how we know which tenant owns the line. Phones often cannot read their own number.
    sim_slot: int = Field(ge=0, le=1)
    remote_number: str = Field(min_length=1, max_length=64)
    event_id: str = Field(min_length=1, max_length=64)

    @field_validator("remote_number")
    @classmethod
    def _remote(cls, v: str) -> str:
        return clean_remote(v)


class IncomingCall(_Event):
    pass


class IncomingSms(_Event):
    body: str = Field(min_length=1, max_length=4000)


class CallStatusEvent(BaseModel):
    sim_slot: int = Field(ge=0, le=1)
    event_id: str = Field(min_length=1, max_length=64)  # the id sent with incoming-call
    status: Literal["answered", "missed", "rejected", "ended"]
    duration_seconds: int | None = Field(default=None, ge=0, le=86400)
