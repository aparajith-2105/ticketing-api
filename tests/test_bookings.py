from datetime import timedelta


def code(response):
    return response.json()["error"]["code"]


def test_booking_success_calculates_total(client, make_user, make_event, book, get_event):
    org, fan = make_user("organizer"), make_user("attendee")
    event_id = make_event(org["id"], price_cents=2500, capacity=10)
    r = book(fan, event_id, 3)
    assert r.status_code == 201
    body = r.json()
    assert body["total_cents"] == 7500 and body["status"] == "confirmed"
    assert get_event(event_id).tickets_sold == 3


def test_cannot_book_more_than_remaining_capacity(client, make_user, make_event, book, get_event):
    org, fan = make_user("organizer"), make_user("attendee")
    event_id = make_event(org["id"], capacity=3)
    assert book(fan, event_id, 2).status_code == 201
    r = book(fan, event_id, 2)
    assert r.status_code == 409 and code(r) == "INSUFFICIENT_CAPACITY"
    assert "1" in r.json()["error"]["message"]
    assert get_event(event_id).tickets_sold == 2  # the failed attempt changed nothing
    assert book(fan, event_id, 1).status_code == 201  # last seat is still available
    assert code(book(fan, event_id, 1)) == "INSUFFICIENT_CAPACITY"  # now sold out


def test_organizer_cannot_book(client, make_user, make_event, book):
    org = make_user("organizer")
    r = book(org, make_event(org["id"]))
    assert r.status_code == 403 and code(r) == "FORBIDDEN"


def test_booking_requires_login(client, make_user, make_event):
    org = make_user("organizer")
    r = client.post("/bookings", json={"event_id": make_event(org["id"]), "quantity": 1})
    assert r.status_code == 401


def test_booking_validation(client, make_user, make_event, book):
    org, fan = make_user("organizer"), make_user("attendee")
    event_id = make_event(org["id"])
    for quantity in (0, -1, 11):
        r = book(fan, event_id, quantity)
        assert r.status_code == 422 and code(r) == "VALIDATION_ERROR"
    assert client.post("/bookings", json={"quantity": 1}, headers=fan["headers"]).status_code == 422


def test_cannot_book_unknown_event(make_user, book):
    fan = make_user("attendee")
    r = book(fan, 99999)
    assert r.status_code == 404 and code(r) == "EVENT_NOT_FOUND"


def test_cannot_book_event_that_has_started(make_user, make_event, book, get_event):
    org, fan = make_user("organizer"), make_user("attendee")
    event_id = make_event(org["id"], starts_in=-timedelta(minutes=5))
    r = book(fan, event_id)
    assert r.status_code == 409 and code(r) == "EVENT_STARTED"
    assert get_event(event_id).tickets_sold == 0


def test_cannot_book_cancelled_event(make_user, make_event, book):
    org, fan = make_user("organizer"), make_user("attendee")
    event_id = make_event(org["id"], status="cancelled")
    r = book(fan, event_id)
    assert r.status_code == 409 and code(r) == "EVENT_CANCELLED"


def test_history_shows_only_own_bookings(client, make_user, make_event, book):
    org, fan1, fan2 = make_user("organizer"), make_user("attendee"), make_user("attendee")
    event_id = make_event(org["id"])
    book(fan1, event_id); book(fan1, event_id); book(fan2, event_id)
    r = client.get("/bookings", headers=fan1["headers"]).json()
    assert r["total"] == 2
    assert all(b["user_id"] == fan1["id"] for b in r["items"])


def test_cancel_booking_inside_window_releases_seats(client, make_user, make_event, book, get_event):
    org, fan = make_user("organizer"), make_user("attendee")
    event_id = make_event(org["id"], capacity=5)
    booking = book(fan, event_id, 3).json()
    r = client.post(f"/bookings/{booking['id']}/cancel", headers=fan["headers"])
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled_by_user" and r.json()["refund_status"] == "pending"
    assert get_event(event_id).tickets_sold == 0

    again = client.post(f"/bookings/{booking['id']}/cancel", headers=fan["headers"])
    assert again.status_code == 409 and code(again) == "BOOKING_NOT_CANCELLABLE"
    assert get_event(event_id).tickets_sold == 0  # seats not released twice


def test_cancel_booking_outside_window_is_rejected(client, make_user, make_event, book, get_event):
    org, fan = make_user("organizer"), make_user("attendee")
    event_id = make_event(org["id"], starts_in=timedelta(hours=2))  # window is 24h
    booking = book(fan, event_id, 1).json()
    r = client.post(f"/bookings/{booking['id']}/cancel", headers=fan["headers"])
    assert r.status_code == 409 and code(r) == "CANCELLATION_WINDOW_CLOSED"
    assert get_event(event_id).tickets_sold == 1


def test_cannot_cancel_or_view_someone_elses_booking(client, make_user, make_event, book):
    org, owner, other = make_user("organizer"), make_user("attendee"), make_user("attendee")
    booking = book(owner, make_event(org["id"])).json()
    cancel = client.post(f"/bookings/{booking['id']}/cancel", headers=other["headers"])
    view = client.get(f"/bookings/{booking['id']}", headers=other["headers"])
    for r in (cancel, view):
        assert r.status_code == 404 and code(r) == "BOOKING_NOT_FOUND"


def test_booking_endpoint_is_rate_limited(make_user, make_event, book):
    org, fan = make_user("organizer"), make_user("attendee")
    event_id = make_event(org["id"], capacity=100)
    for _ in range(5):
        assert book(fan, event_id).status_code == 201
    r = book(fan, event_id)
    assert r.status_code == 429 and code(r) == "RATE_LIMITED"
    assert "retry-after" in r.headers
