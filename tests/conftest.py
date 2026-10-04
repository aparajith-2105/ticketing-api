import os
import tempfile

# Must be set BEFORE the app is imported. By default tests use a throwaway SQLite file.
# To run the same tests against PostgreSQL:  set TEST_DATABASE_URL=postgresql+psycopg2://...
_TMP = tempfile.mkdtemp(prefix="ticketing-tests-")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_TMP}/test.db")
os.environ["JWT_SECRET"] = "test-secret-not-for-production"

import itertools  # noqa: E402
from datetime import timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Booking, Event, User  # noqa: E402
from app.ratelimit import booking_limiter  # noqa: E402
from app.security import create_access_token, hash_password  # noqa: E402
from app.timeutil import utcnow  # noqa: E402

_counter = itertools.count(1)
_PW_HASH = hash_password("Passw0rd123")  # hash once; bcrypt is deliberately slow


@pytest.fixture(autouse=True)
def clean_db():
    """Every test starts with empty tables and a fresh rate limiter."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    booking_limiter.reset()
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def make_user():
    """Insert a user directly; returns id, email and ready-to-use auth headers."""
    def _make(role="attendee", email=None):
        n = next(_counter)
        email = email or f"{role}{n}@test.com"
        with SessionLocal() as db:
            user = User(email=email, password_hash=_PW_HASH, full_name=f"Test {n}", role=role)
            db.add(user)
            db.commit()
            uid = user.id
        token = create_access_token(uid, role)
        return {"id": uid, "email": email, "headers": {"Authorization": f"Bearer {token}"}}
    return _make


@pytest.fixture
def make_event():
    """Insert an event directly (lets tests create past or cancelled events)."""
    def _make(organizer_id, *, title="Test Event", description="", category="concert",
              city="Madurai", venue="Town Hall", price_cents=1000, capacity=10,
              tickets_sold=0, status="published", starts_in=timedelta(days=30)):
        with SessionLocal() as db:
            event = Event(organizer_id=organizer_id, title=title, description=description,
                          category=category, city=city, venue=venue,
                          start_time=utcnow() + starts_in, price_cents=price_cents,
                          capacity=capacity, tickets_sold=tickets_sold, status=status)
            db.add(event)
            db.commit()
            return event.id
    return _make


@pytest.fixture
def book(client):
    def _book(user, event_id, quantity=1):
        return client.post("/bookings", json={"event_id": event_id, "quantity": quantity},
                           headers=user["headers"])
    return _book


@pytest.fixture
def get_event():
    def _get(event_id):
        with SessionLocal() as db:
            return db.get(Event, event_id)
    return _get


@pytest.fixture
def count_bookings():
    def _count(event_id):
        with SessionLocal() as db:
            return db.scalar(select(func.count()).select_from(Booking)
                             .where(Booking.event_id == event_id))
    return _count
