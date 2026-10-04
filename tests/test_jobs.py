from datetime import timedelta

from app.jobs import complete_past_events


def test_completion_job_only_touches_past_published_events(make_user, make_event, get_event):
    org = make_user("organizer")
    past = make_event(org["id"], starts_in=-timedelta(hours=1))
    future = make_event(org["id"], starts_in=timedelta(days=5))
    cancelled_past = make_event(org["id"], status="cancelled", starts_in=-timedelta(hours=1))

    assert complete_past_events() == 1

    assert get_event(past).status == "completed"
    assert get_event(future).status == "published"
    assert get_event(cancelled_past).status == "cancelled"  # cancelled stays cancelled
    assert complete_past_events() == 0  # idempotent