from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import require_role
from ..enums import BookingStatus, EventStatus, RefundStatus, Role
from ..errors import ApiError
from ..models import Booking, Event, User
from ..pagination import Page, PageParams, paginate
from ..ratelimit import booking_limiter
from ..schemas import BookingCreate, BookingOut
from ..timeutil import utcnow

router = APIRouter(prefix="/bookings", tags=["Bookings"])
attendee_only = require_role(Role.ATTENDEE)


@router.post("", response_model=BookingOut, status_code=201,
             summary="Book tickets (overbooking-safe, rate limited)")
def create_booking(payload: BookingCreate, user: User = Depends(attendee_only),
                   db: Session = Depends(get_db)):
    booking_limiter.check(user.id)
    now = utcnow()

    # THE KEY STATEMENT: check availability and take the seats in ONE atomic UPDATE.
    # The database serializes concurrent updates to the same row, so two requests
    # for the last seat can never both succeed.
    res = db.execute(
        update(Event)
        .where(Event.id == payload.event_id,
               Event.status == EventStatus.PUBLISHED.value,
               Event.start_time > now,
               Event.tickets_sold + payload.quantity <= Event.capacity)
        .values(tickets_sold=Event.tickets_sold + payload.quantity)
        .execution_options(synchronize_session=False))

    if res.rowcount == 0:
        db.rollback()
        event = db.get(Event, payload.event_id)
        if event is None:
            raise ApiError(404, "EVENT_NOT_FOUND", "Event not found")
        if event.status == EventStatus.CANCELLED.value:
            raise ApiError(409, "EVENT_CANCELLED", "This event has been cancelled")
        if event.status == EventStatus.COMPLETED.value or event.start_time <= now:
            raise ApiError(409, "EVENT_STARTED", "This event has already started")
        remaining = event.capacity - event.tickets_sold
        raise ApiError(409, "INSUFFICIENT_CAPACITY",
                       f"Only {remaining} ticket(s) left", [{"remaining": remaining}])

    # We now hold the row lock on the event until commit, so the price we read is consistent.
    price = db.scalar(select(Event.price_cents).where(Event.id == payload.event_id))
    booking = Booking(user_id=user.id, event_id=payload.event_id, quantity=payload.quantity,
                      total_cents=price * payload.quantity)
    db.add(booking)
    db.commit()  # tickets_sold increment + booking row commit together, or not at all
    return booking


@router.get("", response_model=Page[BookingOut], summary="My booking history")
def my_bookings(status: BookingStatus | None = None, params: PageParams = Depends(),
                user: User = Depends(attendee_only), db: Session = Depends(get_db)):
    stmt = select(Booking).where(Booking.user_id == user.id)
    if status:
        stmt = stmt.where(Booking.status == status.value)
    return paginate(db, stmt.order_by(Booking.created_at.desc(), Booking.id.desc()),
                    params, BookingOut)


@router.get("/{booking_id}", response_model=BookingOut, summary="One of my bookings")
def get_booking(booking_id: int, user: User = Depends(attendee_only),
                db: Session = Depends(get_db)):
    booking = db.scalar(select(Booking).where(Booking.id == booking_id,
                                              Booking.user_id == user.id))
    if booking is None:
        raise ApiError(404, "BOOKING_NOT_FOUND", "Booking not found")
    return booking


@router.post("/{booking_id}/cancel", response_model=BookingOut,
             summary="Cancel my booking (within the cancellation window)")
def cancel_booking(booking_id: int, user: User = Depends(attendee_only),
                   db: Session = Depends(get_db)):
    booking = db.scalar(select(Booking).where(Booking.id == booking_id,
                                              Booking.user_id == user.id))
    if booking is None:
        raise ApiError(404, "BOOKING_NOT_FOUND", "Booking not found")
    if booking.status != BookingStatus.CONFIRMED.value:
        raise ApiError(409, "BOOKING_NOT_CANCELLABLE", f"Booking is already {booking.status}")

    now = utcnow()
    event = db.get(Event, booking.event_id)
    deadline = event.start_time - timedelta(hours=settings.cancellation_window_hours)
    if now >= deadline:
        raise ApiError(409, "CANCELLATION_WINDOW_CLOSED",
                       f"Bookings can only be cancelled {settings.cancellation_window_hours}h "
                       "or more before the event starts")

    # Claim the cancellation atomically so a double-click can't release seats twice.
    res = db.execute(update(Booking)
                     .where(Booking.id == booking.id,
                            Booking.status == BookingStatus.CONFIRMED.value)
                     .values(status=BookingStatus.CANCELLED_BY_USER.value,
                             refund_status=RefundStatus.PENDING.value, cancelled_at=now)
                     .execution_options(synchronize_session=False))
    if res.rowcount == 0:
        db.rollback()
        raise ApiError(409, "BOOKING_NOT_CANCELLABLE", "Booking is no longer cancellable")
    db.execute(update(Event).where(Event.id == event.id)
               .values(tickets_sold=Event.tickets_sold - booking.quantity)
               .execution_options(synchronize_session=False))
    db.commit()
    db.refresh(booking)
    return booking