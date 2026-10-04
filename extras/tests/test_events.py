from datetime import timedelta

import pytest

from app.timeutil import utcnow


def event_payload(**override):
    body = {"title": "Rock Night", "description": "Live band", "category": "concert",
            "city": "Madurai", "venue": "Town Hall",
            "start_time": (utcnow() + timedelta(days=30)).isoformat(),
            "price_cents": 50000, "capacity": 3}
    body.update(override)
    return body


def code(response):
    return response.json()["error"]["code"]


# ---------- create ----------
def test_organizer_can_create_event(client, make_user):
    org = make_user("organizer")
    r = client.post("/events", json=event_payload(), headers=org["headers"])
    assert r.status_code == 201
    body = r.json()
    assert body["organizer_id"] == org["id"]
    assert body["tickets_sold"] == 0 and body["remaining_capacity"] == 3
    assert body["status"] == "published"


def test_attendee_cannot_create_event(client, make_user):
    fan = make_user("attendee")
    r = client.post("/events", json=event_payload(), headers=fan["headers"])
    assert r.status_code == 403 and code(r) == "FORBIDDEN"


def test_create_event_requires_login(client):
    assert client.post("/events", json=event_payload()).status_code == 401


@pytest.mark.parametrize("override", [
    {"start_time": (utcnow() - timedelta(days=1)).isoformat()},  # in the past
    {"capacity": 0},
    {"price_cents": -5},
    {"category": "festival"},
    {"title": "ab"},
])
def test_create_event_rejects_invalid_payloads(client, make_user, override):
    org = make_user("organizer")
    r = client.post("/events", json=event_payload(**override), headers=org["headers"])
    assert r.status_code == 422 and code(r) == "VALIDATION_ERROR"


# ---------- browse ----------
def test_list_events_is_public_and_filterable(client, make_user, make_event):
    org = make_user("organizer")
    make_event(org["id"], title="Rock Night", description="Live band", city="Madurai",
               category="concert", price_cents=500, starts_in=timedelta(days=10))
    make_event(org["id"], title="Python Workshop", city="Chennai", category="workshop",
               price_cents=2000, starts_in=timedelta(days=20))
    make_event(org["id"], title="Free Meetup", city="Madurai", category="meetup",
               price_cents=0, starts_in=timedelta(days=40))
    make_event(org["id"], title="Sold Out Show", city="Madurai", category="concert",
               price_cents=900, capacity=2, tickets_sold=2, starts_in=timedelta(days=15))
    make_event(org["id"], title="Old Gig", starts_in=-timedelta(days=1))      # already started
    make_event(org["id"], title="Cancelled Gig", status="cancelled")          # cancelled

    def titles(**params):
        r = client.get("/events", params=params)
        assert r.status_code == 200
        return sorted(e["title"] for e in r.json()["items"])

    assert titles() == ["Free Meetup", "Python Workshop", "Rock Night", "Sold Out Show"]
    assert titles(city="madurai") == ["Free Meetup", "Rock Night", "Sold Out Show"]
    assert titles(category="workshop") == ["Python Workshop"]
    assert titles(min_price=1000) == ["Python Workshop"]
    assert titles(max_price=600) == ["Free Meetup", "Rock Night"]
    assert titles(q="python") == ["Python Workshop"]
    assert titles(q="live") == ["Rock Night"]  # matches the description
    assert titles(available_only="true") == ["Free Meetup", "Python Workshop", "Rock Night"]
    assert titles(date_from=(utcnow() + timedelta(days=12)).isoformat(),
                  date_to=(utcnow() + timedelta(days=25)).isoformat()) == \
        ["Python Workshop", "Sold Out Show"]


def test_list_events_rejects_inconsistent_filters(client):
    assert client.get("/events", params={"min_price": 100, "max_price": 50}).status_code == 422
    r = client.get("/events", params={"date_from": "2030-01-02T00:00:00",
                                      "date_to": "2030-01-01T00:00:00"})
    assert r.status_code == 422


def test_pagination(client, make_user, make_event):
    org = make_user("organizer")
    for i in range(5):
        make_event(org["id"], title=f"Event {i}", starts_in=timedelta(days=10 + i))
    r = client.get("/events", params={"page_size": 2}).json()
    assert len(r["items"]) == 2 and r["total"] == 5 and r["pages"] == 3
    last = client.get("/events", params={"page_size": 2, "page": 3}).json()
    assert len(last["items"]) == 1
    assert client.get("/events", params={"page_size": 101}).status_code == 422
    assert client.get("/events", params={"page": 0}).status_code == 422


def test_event_detail_and_not_found(client, make_user, make_event):
    org = make_user("organizer")
    event_id = make_event(org["id"], capacity=10, tickets_sold=4)
    r = client.get(f"/events/{event_id}")
    assert r.status_code == 200 and r.json()["remaining_capacity"] == 6
    missing = client.get("/events/99999")
    assert missing.status_code == 404 and code(missing) == "EVENT_NOT_FOUND"


# ---------- organizer ownership ----------
def test_organizer_can_edit_own_event(client, make_user, make_event):
    org = make_user("organizer")
    event_id = make_event(org["id"])
    r = client.patch(f"/events/{event_id}", json={"title": "New Title", "price_cents": 1},
                     headers=org["headers"])
    assert r.status_code == 200
    assert r.json()["title"] == "New Title" and r.json()["price_cents"] == 1


@pytest.mark.parametrize("body", [{}, {"title": None}])
def test_patch_rejects_empty_or_null_updates(client, make_user, make_event, body):
    org = make_user("organizer")
    event_id = make_event(org["id"])
    assert client.patch(f"/events/{event_id}", json=body, headers=org["headers"]).status_code == 422


def test_organizer_cannot_touch_another_organizers_event(client, make_user, make_event,
                                                          book, get_event):
    owner, intruder, fan = make_user("organizer"), make_user("organizer"), make_user("attendee")
    event_id = make_event(owner["id"], title="Original")
    assert book(fan, event_id).status_code == 201

    h = intruder["headers"]
    responses = [
        client.patch(f"/events/{event_id}", json={"title": "Hacked"}, headers=h),
        client.delete(f"/events/{event_id}", headers=h),
        client.post(f"/events/{event_id}/cancel", headers=h),
        client.get(f"/events/{event_id}/bookings", headers=h),
        client.get(f"/events/{event_id}/sales", headers=h),
    ]
    for r in responses:
        assert r.status_code == 404 and code(r) == "EVENT_NOT_FOUND"
    event = get_event(event_id)
    assert event.title == "Original" and event.status == "published"


def test_attendee_cannot_use_organizer_endpoints(client, make_user, make_event):
    org, fan = make_user("organizer"), make_user("attendee")
    event_id = make_event(org["id"])
    for r in (client.get(f"/events/{event_id}/sales", headers=fan["headers"]),
              client.get(f"/events/{event_id}/bookings", headers=fan["headers"]),
              client.get("/organizer/events", headers=fan["headers"])):
        assert r.status_code == 403


def test_my_events_lists_only_own_events(client, make_user, make_event):
    a, b = make_user("organizer"), make_user("organizer")
    make_event(a["id"]); make_event(a["id"]); make_event(b["id"])
    r = client.get("/organizer/events", headers=a["headers"]).json()
    assert r["total"] == 2
    assert all(e["organizer_id"] == a["id"] for e in r["items"])


def test_cannot_edit_event_that_has_started(client, make_user, make_event):
    org = make_user("organizer")
    event_id = make_event(org["id"], starts_in=-timedelta(hours=1))
    r = client.patch(f"/events/{event_id}", json={"title": "Too late"}, headers=org["headers"])
    assert r.status_code == 409 and code(r) == "EVENT_NOT_MODIFIABLE"


def test_capacity_cannot_drop_below_tickets_sold(client, make_user, make_event):
    org = make_user("organizer")
    event_id = make_event(org["id"], capacity=10, tickets_sold=5)
    r = client.patch(f"/events/{event_id}", json={"capacity": 3}, headers=org["headers"])
    assert r.status_code == 409 and code(r) == "CAPACITY_BELOW_SOLD"
    ok = client.patch(f"/events/{event_id}", json={"capacity": 5}, headers=org["headers"])
    assert ok.status_code == 200


def test_delete_event_only_when_no_bookings(client, make_user, make_event, book):
    org, fan = make_user("organizer"), make_user("attendee")
    empty = make_event(org["id"])
    booked = make_event(org["id"])
    assert book(fan, booked).status_code == 201

    blocked = client.delete(f"/events/{booked}", headers=org["headers"])
    assert blocked.status_code == 409 and code(blocked) == "EVENT_HAS_BOOKINGS"

    assert client.delete(f"/events/{empty}", headers=org["headers"]).status_code == 204
    assert client.get(f"/events/{empty}").status_code == 404


# ---------- cancel + dashboard ----------
def test_cancelling_event_marks_every_booking_for_refund(client, make_user, make_event, book):
    org, fan1, fan2 = make_user("organizer"), make_user("attendee"), make_user("attendee")
    event_id = make_event(org["id"], capacity=10)
    assert book(fan1, event_id, 2).status_code == 201
    assert book(fan2, event_id, 1).status_code == 201

    r = client.post(f"/events/{event_id}/cancel", headers=org["headers"])
    assert r.status_code == 200
    assert r.json()["event"]["status"] == "cancelled"
    assert r.json()["bookings_marked_for_refund"] == 2

    for fan in (fan1, fan2):
        item = client.get("/bookings", headers=fan["headers"]).json()["items"][0]
        assert item["status"] == "cancelled_by_organizer"
        assert item["refund_status"] == "pending"

    again = client.post(f"/events/{event_id}/cancel", headers=org["headers"])
    assert again.status_code == 409 and code(again) == "EVENT_NOT_CANCELLABLE"
    late = book(fan1, event_id)
    assert late.status_code == 409 and code(late) == "EVENT_CANCELLED"


def test_sales_summary(client, make_user, make_event, book):
    org, fan_a, fan_b = make_user("organizer"), make_user("attendee"), make_user("attendee")
    event_id = make_event(org["id"], capacity=10, price_cents=1000)
    booking_a = book(fan_a, event_id, 3).json()
    assert book(fan_b, event_id, 2).status_code == 201

    s = client.get(f"/events/{event_id}/sales", headers=org["headers"]).json()
    assert (s["tickets_sold"], s["remaining_capacity"], s["confirmed_bookings"],
            s["revenue_cents"]) == (5, 5, 2, 5000)

    # A cancels (event is 30 days away, inside the window): seats are released.
    assert client.post(f"/bookings/{booking_a['id']}/cancel",
                       headers=fan_a["headers"]).status_code == 200
    s = client.get(f"/events/{event_id}/sales", headers=org["headers"]).json()
    assert (s["tickets_sold"], s["remaining_capacity"], s["confirmed_bookings"],
            s["revenue_cents"], s["refunds_pending_cents"]) == (2, 8, 1, 2000, 3000)


def test_organizer_sees_bookings_with_attendee_details(client, make_user, make_event, book):
    org, fan = make_user("organizer"), make_user("attendee")
    event_id = make_event(org["id"])
    book(fan, event_id, 2)
    r = client.get(f"/events/{event_id}/bookings", headers=org["headers"]).json()
    assert r["total"] == 1
    assert r["items"][0]["attendee_email"] == fan["email"]
    assert r["items"][0]["quantity"] == 2
