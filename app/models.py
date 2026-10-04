from datetime import datetime

from sqlalchemy import (Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer,
                        String, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .timeutil import utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    events = relationship("Event", back_populates="organizer", passive_deletes=True)
    bookings = relationship("Booking", back_populates="user", passive_deletes=True)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("capacity > 0", name="ck_event_capacity_positive"),
        CheckConstraint("tickets_sold >= 0 AND tickets_sold <= capacity",
                        name="ck_event_no_overbooking"),
        CheckConstraint("price_cents >= 0", name="ck_event_price_nonneg"),
        Index("ix_events_city_start", "city", "start_time"),
        Index("ix_events_category_start", "category", "start_time"),
        Index("ix_events_status_start", "status", "start_time"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organizer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(20))
    city: Mapped[str] = mapped_column(String(100))
    venue: Mapped[str] = mapped_column(String(150))
    start_time: Mapped[datetime] = mapped_column(DateTime)
    price_cents: Mapped[int] = mapped_column(Integer)
    capacity: Mapped[int] = mapped_column(Integer)
    tickets_sold: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="published")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    organizer = relationship("User", back_populates="events")
    bookings = relationship("Booking", back_populates="event", passive_deletes=True)


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_booking_quantity_positive"),
        Index("ix_bookings_user_created", "user_id", "created_at"),
        Index("ix_bookings_event_status", "event_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"))
    quantity: Mapped[int] = mapped_column(Integer)
    total_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="confirmed")
    refund_status: Mapped[str] = mapped_column(String(20), default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user = relationship("User", back_populates="bookings")
    event = relationship("Event", back_populates="bookings")

    @property
    def attendee_email(self) -> str:
        return self.user.email

    @property
    def attendee_name(self) -> str:
        return self.user.full_name


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    jti: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    family_id: Mapped[str] = mapped_column(String(32), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)