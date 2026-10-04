import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.main import app


def run_in_parallel(jobs):
    """Run callables simultaneously: every thread waits at a barrier, then all go at once."""
    barrier = threading.Barrier(len(jobs), timeout=30)

    def wrapped(job):
        client = TestClient(app)  # one client per thread
        barrier.wait()
        return job(client)

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        return list(pool.map(wrapped, jobs))


def booking_job(user, event_id, quantity):
    def job(client):
        r = client.post("/bookings", json={"event_id": event_id, "quantity": quantity},
                        headers=user["headers"])
        return r.status_code, r.json()
    return job


def test_20_buyers_race_for_5_seats(make_user, make_event, get_event, count_bookings):
    org = make_user("organizer")
    event_id = make_event(org["id"], capacity=5)
    buyers = [make_user("attendee") for _ in range(20)]

    results = run_in_parallel([booking_job(b, event_id, 1) for b in buyers])

    statuses = Counter(status for status, _ in results)
    assert statuses == {201: 5, 409: 15}, statuses
    for status, body in results:
        if status == 409:
            assert body["error"]["code"] == "INSUFFICIENT_CAPACITY"
    assert get_event(event_id).tickets_sold == 5
    assert count_bookings(event_id) == 5


def test_two_buyers_race_for_the_last_seat(make_user, make_event, get_event):
    org = make_user("organizer")
    event_id = make_event(org["id"], capacity=1)
    a, b = make_user("attendee"), make_user("attendee")

    results = run_in_parallel([booking_job(a, event_id, 1), booking_job(b, event_id, 1)])

    assert sorted(status for status, _ in results) == [201, 409]
    assert get_event(event_id).tickets_sold == 1


def test_mixed_quantities_never_exceed_capacity(make_user, make_event, get_event, count_bookings):
    org = make_user("organizer")
    event_id = make_event(org["id"], capacity=5)
    buyers = [make_user("attendee") for _ in range(10)]

    results = run_in_parallel([booking_job(b, event_id, 2) for b in buyers])

    winners = [s for s, _ in results if s == 201]
    assert len(winners) == 2  # 2 + 2 = 4 fits; a third pair would need 6 > 5
    event = get_event(event_id)
    assert event.tickets_sold == 4 <= event.capacity
    assert count_bookings(event_id) == 2


def test_same_refresh_token_used_concurrently_works_only_once(client):
    client.post("/auth/register", json={"email": "ann@test.com", "password": "Passw0rd123",
                                        "full_name": "Ann", "role": "attendee"})
    tokens = client.post("/auth/login", json={"email": "ann@test.com",
                                              "password": "Passw0rd123"}).json()

    def refresh_job(c):
        return c.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code

    statuses = run_in_parallel([refresh_job] * 5)
    assert sorted(statuses) == [200, 401, 401, 401, 401]
