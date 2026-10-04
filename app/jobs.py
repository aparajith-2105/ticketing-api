import asyncio
import logging

from sqlalchemy import update

from .database import SessionLocal
from .enums import EventStatus
from .models import Event
from .timeutil import utcnow

log = logging.getLogger("jobs")


def complete_past_events() -> int:
    """Flip published events whose start time has passed to 'completed'. Returns how many."""
    with SessionLocal() as db:
        res = db.execute(
            update(Event)
            .where(Event.status == EventStatus.PUBLISHED.value, Event.start_time <= utcnow())
            .values(status=EventStatus.COMPLETED.value)
            .execution_options(synchronize_session=False))
        db.commit()
        return res.rowcount


async def completion_loop(interval_seconds: int = 60) -> None:
    while True:
        try:
            changed = await asyncio.to_thread(complete_past_events)
            if changed:
                log.info("Marked %s event(s) as completed", changed)
        except Exception:
            log.exception("completion job failed")  # never let the loop die
        await asyncio.sleep(interval_seconds)