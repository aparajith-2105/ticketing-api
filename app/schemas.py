import re
from datetime import datetime

from pydantic import (BaseModel, ConfigDict, EmailStr, Field, computed_field,
                      field_validator, model_validator)

from .enums import Category, Role
from .timeutil import to_utc_naive, utcnow


def _future(v: datetime) -> datetime:
    v = to_utc_naive(v)
    if v <= utcnow():
        raise ValueError("start_time must be in the future")
    return v


# ---------- auth ----------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(min_length=1, max_length=100)
    role: Role

    @field_validator("password")
    @classmethod
    def strong_enough(cls, v: str) -> str:
        if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
            raise ValueError("password must contain at least one letter and one digit")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str
    role: str
    created_at: datetime


# ---------- events ----------
class EventCreate(BaseModel):
    title: str = Field(min_length=3, max_length=150)
    description: str = Field("", max_length=5000)
    category: Category
    city: str = Field(min_length=1, max_length=100)
    venue: str = Field(min_length=1, max_length=150)
    start_time: datetime
    price_cents: int = Field(ge=0, le=100_000_000)
    capacity: int = Field(gt=0, le=1_000_000)

    @field_validator("start_time")
    @classmethod
    def _check_future(cls, v):
        return _future(v)


class EventUpdate(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=150)
    description: str | None = Field(None, max_length=5000)
    category: Category | None = None
    city: str | None = Field(None, min_length=1, max_length=100)
    venue: str | None = Field(None, min_length=1, max_length=150)
    start_time: datetime | None = None
    price_cents: int | None = Field(None, ge=0, le=100_000_000)
    capacity: int | None = Field(None, gt=0, le=1_000_000)

    @field_validator("start_time")
    @classmethod
    def _check_future(cls, v):
        return _future(v) if v is not None else v

    @model_validator(mode="after")
    def _no_nulls(self):
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        for f in self.model_fields_set:
            if getattr(self, f) is None:
                raise ValueError(f"{f} cannot be null")
        return self


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organizer_id: int
    title: str
    description: str
    category: str
    city: str
    venue: str
    start_time: datetime
    price_cents: int
    capacity: int
    tickets_sold: int
    status: str
    created_at: datetime

    @computed_field
    @property
    def remaining_capacity(self) -> int:
        return self.capacity - self.tickets_sold


class CancelEventOut(BaseModel):
    event: EventOut
    bookings_marked_for_refund: int


class SalesSummary(BaseModel):
    event_id: int
    status: str
    capacity: int
    tickets_sold: int
    remaining_capacity: int
    confirmed_bookings: int
    revenue_cents: int
    refunds_pending_cents: int


# ---------- bookings ----------
class BookingCreate(BaseModel):
    event_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=10)


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_id: int
    user_id: int
    quantity: int
    total_cents: int
    status: str
    refund_status: str
    created_at: datetime
    cancelled_at: datetime | None = None


class OrganizerBookingOut(BookingOut):
    attendee_name: str
    attendee_email: str