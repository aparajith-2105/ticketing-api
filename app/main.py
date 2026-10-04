import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from .database import Base, engine
from .errors import register_handlers
from .jobs import completion_loop
from .routers import auth, bookings, events


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    task = asyncio.create_task(completion_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="Event Ticketing API",
    version="1.0.0",
    description="Browse events, book tickets, and manage events as an organizer. "
                "All times are UTC. Prices are integer cents. Click **Authorize** and paste "
                "the `access_token` from `/auth/login`.",
    lifespan=lifespan,
)
register_handlers(app)
app.include_router(auth.router)
app.include_router(events.router)
app.include_router(bookings.router)


@app.get("/health", tags=["Meta"])
def health():
    return {"status": "ok"}