from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..deps import require_role
from ..enums import BookingStatus, Category, EventStatus, RefundStatus, Role
from ..errors import ApiError
from ..models import Booking, Event, User
from ..pagination import Page, PageParams, paginate
from ..schemas import (CancelEventOut, EventCreate, EventOut, EventUpdate,
                       OrganizerBookingOut, SalesSummary)
from ..timeutil import to_utc_naive, utcnow

router = APIRouter(tags=["Events"])
organizer_only = require_role(Role.ORGANIZER)


def get_owned_event(db: Session, event_id: int, user: User) -> Event:
    event = db.get(Event, event_id)
    # 404 (not 403) so we don't reveal that someone else's event exists.
    if event is None or event.organizer_id != user.id:
        raise ApiError(404, "EVENT_NOT_FOUND", "Event not found")
    return event


# ---------------- public ----------------
@router.get("/events", response_model=Page[EventOut], summary="Browse upcoming events")
def list_events(
    category: Category | None = None,
    city: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    min_price: int | None = Query(None, ge=0, description="in cents"),
    max_price: int | None = Query(None, ge=0, description="in cents"),
    q: str | None = Query(None, min_length=2, max_length=100,
                          description="search title/description"),
    available_only: bool = False,
    params: PageParams = Depends(),
    db: Session = Depends(get_db),
):
    if date_from and date_to and to_utc_naive(date_from) > to_utc_naive(date_to):
        raise ApiError(422, "VALIDATION_ERROR", "date_from must be before date_to")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ApiError(422, "VALIDATION_ERROR", "min_price must be <= max_price")

    stmt = select(Event).where(Event.status == EventStatus.PUBLISHED.value,
                               Event.start_time > utcnow())
    if category:
        stmt = stmt.where(Event.category == category.value)
    if city:
        stmt = stmt.where(func.lower(Event.city) == city.strip().lower())
    if date_from:
        stmt = stmt.where(Event.start_time >= to_utc_naive(date_from))
    if date_to:
        stmt = stmt.where(Event.start_time <= to_utc_naive(date_to))
    if min_price is not None:
        stmt = stmt.where(Event.price_cents >= min_price)
    if max_price is not None:
        stmt = stmt.where(Event.price_cents <= max_price)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Event.title.ilike(like), Event.description.ilike(like)))
    if available_only:
        stmt = stmt.where(Event.tickets_sold < Event.capacity)
    return paginate(db, stmt.order_by(Event.start_time, Event.id), params, EventOut)


@router.get("/events/{event_id}", response_model=EventOut, summary="Event details")
def get_event(event_id: int, db: Session = Depends(get_db)):
    event = db.get(Event, event_id)
    if event is None:
        raise ApiError(404, "EVENT_NOT_FOUND", "Event not found")
    return event


# ---------------- organizer ----------------
@router.post("/events", response_model=EventOut, status_code=201, summary="Create an event")
def create_event(payload: EventCreate, user: User = Depends(organizer_only),
                 db: Session = Depends(get_db)):
    data = payload.model_dump()
    data["category"] = payload.category.value
    event = Event(**data, organizer_id=user.id)
    db.add(event)
    db.commit()
    return event


@router.get("/organizer/events", response_model=Page[EventOut],
            summary="List my own events")
def my_events(status: EventStatus | None = None, params: PageParams = Depends(),
              user: User = Depends(organizer_only), db: Session = Depends(get_db)):
    stmt = select(Event).where(Event.organizer_id == user.id)
    if status:
        stmt = stmt.where(Event.status == status.value)
    return paginate(db, stmt.order_by(Event.start_time.desc(), Event.id), params, EventOut)


@router.patch("/events/{event_id}", response_model=EventOut, summary="Edit my event")
def update_event(event_id: int, payload: EventUpdate, user: User = Depends(organizer_only),
                 db: Session = Depends(get_db)):
    event = get_owned_event(db, event_id, user)
    if event.status != EventStatus.PUBLISHED.value or event.start_time <= utcnow():
        raise ApiError(409, "EVENT_NOT_MODIFIABLE",
                       "Events that have started, completed or been cancelled cannot be modified")
    data = payload.model_dump(exclude_unset=True)
    if "category" in data:
        data["category"] = data["category"].value
    if "capacity" in data and data["capacity"] < event.tickets_sold:
        raise ApiError(409, "CAPACITY_BELOW_SOLD",
                       f"Capacity cannot be below tickets already sold ({event.tickets_sold})")
    for key, value in data.items():
        setattr(event, key, value)
    try:
        db.commit()
    except IntegrityError:  # a booking slipped in and the DB CHECK constraint caught it
        db.rollback()
        raise ApiError(409, "CAPACITY_BELOW_SOLD", "Capacity is below tickets sold")
    return event


@router.delete("/events/{event_id}", status_code=204, summary="Delete my event")
def delete_event(event_id: int, user: User = Depends(organizer_only),
                 db: Session = Depends(get_db)):
    event = get_owned_event(db, event_id, user)
    has_bookings = db.scalar(select(func.count()).select_from(Booking)
                             .where(Booking.event_id == event.id))
    if has_bookings:
        raise ApiError(409, "EVENT_HAS_BOOKINGS",
                       "Events with bookings cannot be deleted; cancel the event instead")
    db.delete(event)
    db.commit()
    return Response(status_code=204)


@router.post("/events/{event_id}/cancel", response_model=CancelEventOut,
             summary="Cancel my event and mark all bookings for refund")
def cancel_event(event_id: int, user: User = Depends(organizer_only),
                 db: Session = Depends(get_db)):
    event = get_owned_event(db, event_id, user)
    now = utcnow()
    res = db.execute(update(Event)
                     .where(Event.id == event.id, Event.status == EventStatus.PUBLISHED.value,
                            Event.start_time > now)
                     .values(status=EventStatus.CANCELLED.value, updated_at=now)
                     .execution_options(synchronize_session=False))
    if res.rowcount == 0:
        db.rollback()
        raise ApiError(409, "EVENT_NOT_CANCELLABLE",
                       "Only upcoming, published events can be cancelled")
    refunded = db.execute(update(Booking)
                          .where(Booking.event_id == event.id,
                                 Booking.status == BookingStatus.CONFIRMED.value)
                          .values(status=BookingStatus.CANCELLED_BY_ORGANIZER.value,
                                  refund_status=RefundStatus.PENDING.value, cancelled_at=now)
                          .execution_options(synchronize_session=False)).rowcount
    db.commit()
    db.refresh(event)
    return CancelEventOut(event=EventOut.model_validate(event),
                          bookings_marked_for_refund=refunded)


@router.get("/events/{event_id}/bookings", response_model=Page[OrganizerBookingOut],
            summary="All bookings for my event")
def event_bookings(event_id: int, status: BookingStatus | None = None,
                   params: PageParams = Depends(), user: User = Depends(organizer_only),
                   db: Session = Depends(get_db)):
    event = get_owned_event(db, event_id, user)
    stmt = (select(Booking).where(Booking.event_id == event.id)
            .options(selectinload(Booking.user)))
    if status:
        stmt = stmt.where(Booking.status == status.value)
    return paginate(db, stmt.order_by(Booking.created_at.desc(), Booking.id),
                    params, OrganizerBookingOut)


@router.get("/events/{event_id}/sales", response_model=SalesSummary,
            summary="Sales summary for my event")
def event_sales(event_id: int, user: User = Depends(organizer_only),
                db: Session = Depends(get_db)):
    event = get_owned_event(db, event_id, user)
    confirmed = BookingStatus.CONFIRMED.value
    revenue = db.scalar(select(func.coalesce(func.sum(Booking.total_cents), 0))
                        .where(Booking.event_id == event.id, Booking.status == confirmed))
    count = db.scalar(select(func.count()).select_from(Booking)
                      .where(Booking.event_id == event.id, Booking.status == confirmed))
    pending = db.scalar(select(func.coalesce(func.sum(Booking.total_cents), 0))
                        .where(Booking.event_id == event.id,
                               Booking.refund_status == RefundStatus.PENDING.value))
    return SalesSummary(event_id=event.id, status=event.status, capacity=event.capacity,
                        tickets_sold=event.tickets_sold,
                        remaining_capacity=event.capacity - event.tickets_sold,
                        confirmed_bookings=count, revenue_cents=revenue,
                        refunds_pending_cents=pending)