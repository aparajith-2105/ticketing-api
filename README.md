# Event Ticketing API

Backend for an event ticketing platform: attendees browse and book tickets, organizers manage their own events and sales. **FastAPI + SQLAlchemy 2 + PostgreSQL + JWT**, with role-based authorization and overbooking-proof booking.Deployed with **Render**.

| | |
|---|---|
| **Live API (Swagger)** | https://ticketing-api-2qo4.onrender.com/docs |
| **Source** | https://github.com/aparajith-2105/ticketing-api |
| **Tests** | `python -m pytest -v` → **56 passed**, incl. concurrent-booking race tests |

> Free hosting tier: after inactivity the first request can take **~1 minute** to wake up. The free database expires ~30 days after creation.

## Try it in 2 minutes

In the live `/docs`, use **Try it out** on each endpoint (you pick the role when registering):

1. `POST /auth/register` `{"email":"org@test.com","password":"Passw0rd123","full_name":"Olivia","role":"organizer"}` → `POST /auth/login`. Copy the `access_token`, click **Authorize**, paste it (valid 15 min).
2. `POST /events` `{"title":"Rock Night","category":"concert","city":"Madurai","venue":"Town Hall","start_time":"2026-12-20T18:00:00Z","price_cents":50000,"capacity":3}` → `201` (date must be in the future).
3. Register `fan@test.com` with `"role":"attendee"`, log in, re-**Authorize** with the new token.
4. `POST /bookings` `{"event_id":1,"quantity":2}` → `201`. Repeat → **`409 INSUFFICIENT_CAPACITY`** ("Only 1 ticket(s) left").
5. As attendee `POST /events` → `403`. As a second organizer `PATCH /events/1` → `404` (not theirs).
6. As the first organizer: `GET /events/1/sales`, `GET /events/1/bookings`, `POST /events/1/cancel` (all bookings become `refund_status: pending`).

## Requirements checklist

| Requirement | How | Code |
|---|---|---|
| Register with role, JWT + refresh tokens | `/auth/register`, `/auth/login`, `/auth/refresh` | `routers/auth.py`, `security.py` |
| Validation + structured errors | Pydantic; one shape `{error:{code,message,details}}` | `schemas.py`, `errors.py` |
| RBAC on every endpoint; organizers only touch own events | `require_role` + ownership check (others get `404`) | `deps.py`, `routers/events.py` |
| Browse/filter (category, city, dates, price) + pagination | `GET /events` | `routers/events.py` |
| Book tickets, **no overbooking under concurrency** | One atomic conditional `UPDATE` + DB `CHECK` | `routers/bookings.py`, `models.py` |
| Reject started/cancelled events | `409 EVENT_STARTED` / `EVENT_CANCELLED` | `routers/bookings.py` |
| History, cancel within window (24h) | `GET /bookings`, `POST /bookings/{id}/cancel` | `routers/bookings.py` |
| Organizer CRUD, bookings, sales summary | `/events`, `/events/{id}/bookings`, `/events/{id}/sales` | `routers/events.py` |
| Cancel event → refund status on all bookings | `POST /events/{id}/cancel` | `routers/events.py` |
| Indexes, cascade rules | See Data model | `models.py` |
| OpenAPI + Swagger/Redoc | Live at `/docs`, `/redoc` | |
| Tests incl. race | `tests/` (56) | `test_concurrency.py` |
| Dockerfile + deploy docs | Below | `Dockerfile`, `docker-compose.yml` |

## Bonus challenges

| Bonus | Status |
|---|---|
| Booking rate limit (5/min per user, `429` + `Retry-After`) | Done (in-memory; use Redis to scale out) |
| Refresh-token rotation + revocation (reuse revokes the whole family) | Done, tested |
| Background job marking past events `completed` (`app/jobs.py`, every 60s) | Done, tested |
| Search (`q` on `GET /events`, title/description) | Partial: substring match, no full-text index |
| Confirmation email, Redis cache | Not done |

## Endpoints

| Method | Path | Role |
|---|---|---|
| POST | `/auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout` | public |
| GET | `/auth/me` | any |
| GET | `/events` (filters: `category`, `city`, `date_from`, `date_to`, `min_price`, `max_price` in cents, `q`, `available_only`, `page`, `page_size` ≤ 100), `/events/{id}` | public |
| POST | `/events` | organizer |
| GET | `/organizer/events`, `/events/{id}/bookings`, `/events/{id}/sales` | organizer (owner) |
| PATCH / DELETE | `/events/{id}` (no edits after start; no delete if bookings exist) | organizer (owner) |
| POST | `/events/{id}/cancel` | organizer (owner) |
| POST / GET | `/bookings`, `/bookings/{id}`; POST `/bookings/{id}/cancel` | attendee |

Times are UTC; prices are integer cents. Request/response schemas and examples are in Swagger.

**Error format:** `{"error":{"code":"INSUFFICIENT_CAPACITY","message":"Only 1 ticket(s) left","details":[]}}`

| HTTP | Codes |
|---|---|
| 401 | `NOT_AUTHENTICATED`, `INVALID_TOKEN`, `INVALID_CREDENTIALS`, `TOKEN_REUSED` |
| 403 | `FORBIDDEN` (wrong role) |
| 404 | `EVENT_NOT_FOUND` (missing **or not yours**), `BOOKING_NOT_FOUND` |
| 409 | `EMAIL_TAKEN`, `INSUFFICIENT_CAPACITY`, `EVENT_CANCELLED`, `EVENT_STARTED`, `EVENT_NOT_MODIFIABLE`, `EVENT_NOT_CANCELLABLE`, `EVENT_HAS_BOOKINGS`, `CAPACITY_BELOW_SOLD`, `BOOKING_NOT_CANCELLABLE`, `CANCELLATION_WINDOW_CLOSED` |
| 422 | `VALIDATION_ERROR` (per-field `details`) |
| 429 | `RATE_LIMITED` |
| 500 | `INTERNAL_ERROR` (no internals leaked) |

## Data model

`users 1─< events` · `users 1─< bookings` · `events 1─< bookings` · `users 1─< refresh_tokens`

| Table | Key columns |
|---|---|
| `users` | email (unique), password_hash, full_name, role |
| `events` | organizer_id, title, description, category, city, venue, start_time, price_cents, capacity, tickets_sold, status |
| `bookings` | user_id, event_id, quantity, total_cents, status, refund_status, cancelled_at |
| `refresh_tokens` | jti, user_id, family_id, revoked, expires_at |

- **DB constraints:** `capacity > 0`, `price_cents >= 0`, `quantity > 0`, and **`0 <= tickets_sold <= capacity`**.
- **Indexes:** `events(city,start_time)`, `(category,start_time)`, `(status,start_time)`, `(organizer_id)`; `bookings(user_id,created_at)`, `(event_id,status)`; `refresh_tokens(user_id)`, `(family_id)`.
- **Cascades:** `RESTRICT` on users/events/bookings so history can't be deleted (cancel instead of delete); `CASCADE` for refresh tokens.

## How overbooking is prevented

A read-check-write flow lets two requests both see "1 seat left" and both sell it. Instead, check and reserve happen in **one atomic statement**:

```sql
UPDATE events SET tickets_sold = tickets_sold + :qty
WHERE id = :id AND status = 'published' AND start_time > :now
  AND tickets_sold + :qty <= capacity;
```

The booking row is inserted in the same transaction. **1 row updated** → seats are ours; **0 rows** → clean `409`.

**Two people grab the last seat:** the database locks the event row for the first `UPDATE`; the second waits, then re-evaluates its `WHERE` on the new value, sees no room, updates 0 rows and gets `409 INSUFFICIENT_CAPACITY`. Exactly one wins. The `CHECK (tickets_sold <= capacity)` constraint is a second safety net. Booking cancellation and refresh-token rotation use the same atomic "claim" pattern.

**Proof:** `tests/test_concurrency.py` releases simultaneous requests with a barrier: 20 buyers for 5 seats (exactly 5 succeed), 2 buyers for the last seat, mixed quantities, and one refresh token used 5 times at once.

## Error handling and security

- Validation first (422 with field details); state conflicts return specific `409` codes; races are decided by atomic updates, not read-then-write; multi-step writes commit once or roll back.
- Passwords hashed with **bcrypt**; never returned. Access tokens expire in 15 min and carry a `type` claim (a refresh token can't be used as an access token).
- Role checks on every endpoint plus ownership checks; foreign events return `404`. Login gives the same error for unknown email and wrong password.
- SQL is parameterized (SQLAlchemy); pagination capped at 100; booking rate-limited.
- Secrets come from environment variables (`JWT_SECRET`, `DATABASE_URL`); `.env` is git-ignored; container runs as non-root.
- **Production TODO:** HTTPS proxy, restrict CORS, login rate limiting, Redis limiter for multi-instance, Alembic migrations, email verification.

## Run, test, deploy

```bash
python -m venv .venv && .venv\Scripts\activate     # Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                               # set JWT_SECRET (python -c "import secrets; print(secrets.token_hex(32))")
uvicorn app.main:app --reload                        # http://127.0.0.1:8000/docs
python -m pytest -v                                  # 56 tests, temp SQLite DB
```

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./tickets.db` | Use a `postgresql://...` URL in production |
| `JWT_SECRET` | dev value | **Must** be set in production |
| `CANCELLATION_WINDOW_HOURS` | 24 | Attendee cancellation cutoff |
| `BOOKING_RATE_LIMIT` / `BOOKING_RATE_WINDOW_SECONDS` | 5 / 60 | Booking attempts per user |

- **Docker Compose (API + PostgreSQL):** `set JWT_SECRET=...` then `docker compose up --build` → http://localhost:8000/docs.
- **Live deployment:** Render (Docker runtime, built from this `Dockerfile`) + managed PostgreSQL. Env vars `DATABASE_URL` (internal URL) and `JWT_SECRET`; health check path `/health`.
- To run tests against PostgreSQL: set `TEST_DATABASE_URL` (the tests drop and recreate tables, so use a disposable DB).

## Project layout

`app/` (`main.py`, `config.py`, `database.py`, `models.py`, `schemas.py`, `security.py`, `deps.py`, `errors.py`, `ratelimit.py`, `jobs.py`, `pagination.py`, `routers/{auth,events,bookings}.py`) · `tests/` (auth, events, bookings, concurrency, jobs) · `Dockerfile` · `docker-compose.yml`
