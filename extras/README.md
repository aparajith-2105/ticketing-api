# Event Ticketing API

REST backend for event discovery, ticket booking and an organizer dashboard.
**Stack:** Python 3.12+, FastAPI, SQLAlchemy 2, PostgreSQL (SQLite for local dev/tests), JWT (PyJWT), bcrypt.

Live docs once running: **`/docs`** (Swagger UI) and **`/redoc`** (Redoc). OpenAPI JSON: `/openapi.json`.

## Quick start (local)

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows   (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env            # then put a real JWT_SECRET in .env
uvicorn app.main:app --reload
```
Open http://127.0.0.1:8000/docs. Generate a secret with
`python -c "import secrets; print(secrets.token_hex(32))"`.

## Run tests

```bash
python -m pytest -v
```
Tests use a throwaway SQLite database and never touch `tickets.db`.
To run the same suite (including the race tests) against PostgreSQL:
```bash
set TEST_DATABASE_URL=postgresql+psycopg2://tickets:tickets@localhost:5432/tickets_test   # Windows
python -m pytest -v
```
**Warning:** the test fixtures drop and recreate all tables, so point this at a disposable database.

## Deployment

### Docker Compose (API + PostgreSQL)
```bash
set JWT_SECRET=<long random string>        # Mac/Linux: export JWT_SECRET=...
docker compose up --build
```
API on http://localhost:8000/docs. Data persists in the `pgdata` volume.

### Render / Railway / Fly.io
1. Create a managed PostgreSQL instance and copy its connection string.
2. Deploy this repo using the `Dockerfile`.
3. Set environment variables: `DATABASE_URL` (use the `postgresql+psycopg2://` scheme) and `JWT_SECRET`.
4. Health check path: `/health`.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./tickets.db` | Database connection string |
| `JWT_SECRET` | `dev-only-change-me` | Signing key. **Must** be set in production |
| `ACCESS_TOKEN_MINUTES` | 15 | Access token lifetime |
| `REFRESH_TOKEN_DAYS` | 7 | Refresh token lifetime |
| `CANCELLATION_WINDOW_HOURS` | 24 | Attendees may cancel until this many hours before start |
| `BOOKING_RATE_LIMIT` / `BOOKING_RATE_WINDOW_SECONDS` | 5 / 60 | Booking attempts per user per window |

### Known scaling limits (honest notes)
- The rate limiter is in-process memory, so it is correct for one instance only. For several instances, move it to Redis.
- Tables are created at startup with `create_all`. A real deployment should use Alembic migrations.
- Refund status is recorded (`pending`), but no payment gateway is integrated.

---

## API specification

All times are **UTC** (ISO 8601). Prices are **integer cents**. Send `Authorization: Bearer <access_token>` on protected endpoints.

| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/auth/register` | public | Register as `attendee` or `organizer` |
| POST | `/auth/login` | public | Get access and refresh tokens |
| POST | `/auth/refresh` | public | Rotate refresh token (single use) |
| POST | `/auth/logout` | public | Revoke the refresh-token family |
| GET | `/auth/me` | any | Current user |
| GET | `/events` | public | Browse upcoming events (filters and pagination) |
| GET | `/events/{id}` | public | Event details and remaining capacity |
| POST | `/events` | organizer | Create event |
| GET | `/organizer/events` | organizer | List my events |
| PATCH | `/events/{id}` | organizer (owner) | Edit event (not after it started) |
| DELETE | `/events/{id}` | organizer (owner) | Delete event (only if it has no bookings) |
| POST | `/events/{id}/cancel` | organizer (owner) | Cancel event, mark all bookings for refund |
| GET | `/events/{id}/bookings` | organizer (owner) | All bookings for my event |
| GET | `/events/{id}/sales` | organizer (owner) | Tickets sold, revenue, remaining capacity |
| POST | `/bookings` | attendee | Book tickets (rate limited) |
| GET | `/bookings` | attendee | My booking history |
| GET | `/bookings/{id}` | attendee (owner) | One of my bookings |
| POST | `/bookings/{id}/cancel` | attendee (owner) | Cancel within the cancellation window |
| GET | `/health` | public | Liveness check |

### Filters on `GET /events`
`category` (concert, workshop, meetup, conference), `city` (case-insensitive), `date_from`, `date_to`,
`min_price`, `max_price` (cents), `q` (search title/description), `available_only` (bool),
`page` (default 1), `page_size` (default 20, max 100).
Only **published, upcoming** events are listed.

### Examples

**Register**
```http
POST /auth/register
{"email":"org@test.com","password":"Passw0rd123","full_name":"Olivia Organizer","role":"organizer"}
```
`201`
```json
{"id":1,"email":"org@test.com","full_name":"Olivia Organizer","role":"organizer","created_at":"2026-10-04T06:45:38"}
```
Password rules: 8 to 72 characters, at least one letter and one digit.

**Login**
```http
POST /auth/login
{"email":"org@test.com","password":"Passw0rd123"}
```
`200`
```json
{"access_token":"eyJ...","refresh_token":"eyJ...","token_type":"bearer","expires_in":900}
```

**Create event** (organizer)
```http
POST /events
{"title":"Rock Night","description":"Live band","category":"concert","city":"Madurai",
 "venue":"Town Hall","start_time":"2026-12-20T18:00:00Z","price_cents":50000,"capacity":3}
```
`201`
```json
{"id":1,"organizer_id":1,"title":"Rock Night","category":"concert","city":"Madurai","venue":"Town Hall",
 "start_time":"2026-12-20T18:00:00","price_cents":50000,"capacity":3,"tickets_sold":0,
 "status":"published","remaining_capacity":3, "...":"..."}
```

**Browse**
```http
GET /events?city=madurai&category=concert&max_price=60000&page=1&page_size=10
```
`200`
```json
{"items":[{"id":1,"title":"Rock Night","remaining_capacity":3,"...":"..."}],"total":1,"page":1,"page_size":10,"pages":1}
```

**Book**
```http
POST /bookings
{"event_id":1,"quantity":2}
```
`201`
```json
{"id":1,"event_id":1,"user_id":2,"quantity":2,"total_cents":100000,"status":"confirmed","refund_status":"none","created_at":"...","cancelled_at":null}
```
Quantity must be 1 to 10 per request.

**Sales summary** (organizer): `GET /events/1/sales`
```json
{"event_id":1,"status":"published","capacity":3,"tickets_sold":2,"remaining_capacity":1,
 "confirmed_bookings":1,"revenue_cents":100000,"refunds_pending_cents":0}
```

**Cancel event** (organizer): `POST /events/1/cancel` returns `200`
```json
{"event":{"id":1,"status":"cancelled","...":"..."},"bookings_marked_for_refund":1}
```
Every confirmed booking becomes `status: cancelled_by_organizer`, `refund_status: pending`.

### Error format

Every error uses the same shape:
```json
{"error":{"code":"INSUFFICIENT_CAPACITY","message":"Only 1 ticket(s) left","details":[{"remaining":1}]}}
```
Validation errors list each bad field in `details`: `[{"field":"body.password","message":"..."}]`.

### Error codes

| HTTP | Code | When |
|---|---|---|
| 401 | `NOT_AUTHENTICATED` | No bearer token sent |
| 401 | `INVALID_TOKEN` | Token malformed, expired, wrong type, or unknown refresh token |
| 401 | `INVALID_CREDENTIALS` | Wrong email or password (same message for both, to avoid user enumeration) |
| 401 | `TOKEN_REUSED` | Refresh token used twice, so the whole session family is revoked |
| 403 | `FORBIDDEN` | Role not allowed (for example an attendee creating an event) |
| 404 | `EVENT_NOT_FOUND` | Event missing **or owned by another organizer** (deliberately indistinguishable) |
| 404 | `BOOKING_NOT_FOUND` | Booking missing or belongs to someone else |
| 409 | `EMAIL_TAKEN` | Email already registered |
| 409 | `INSUFFICIENT_CAPACITY` | Not enough seats left (message says how many remain) |
| 409 | `EVENT_CANCELLED` | Booking an event that was cancelled |
| 409 | `EVENT_STARTED` | Booking an event that has started or completed |
| 409 | `EVENT_NOT_MODIFIABLE` | Editing an event that started, completed or was cancelled |
| 409 | `EVENT_NOT_CANCELLABLE` | Cancelling an event that is not upcoming and published |
| 409 | `EVENT_HAS_BOOKINGS` | Deleting an event that has bookings (cancel it instead) |
| 409 | `CAPACITY_BELOW_SOLD` | Lowering capacity under tickets already sold |
| 409 | `BOOKING_NOT_CANCELLABLE` | Booking already cancelled |
| 409 | `CANCELLATION_WINDOW_CLOSED` | Less than 24h before the event |
| 422 | `VALIDATION_ERROR` | Malformed, incomplete or inconsistent request |
| 429 | `RATE_LIMITED` | More than 5 booking attempts per minute; see `Retry-After` header |
| 500 | `INTERNAL_ERROR` | Unexpected server error (no internals leaked) |

---

## Data model

```
users 1 ──< events          (organizer_id, ON DELETE RESTRICT)
users 1 ──< bookings        (user_id,      ON DELETE RESTRICT)
events 1 ──< bookings       (event_id,     ON DELETE RESTRICT)
users 1 ──< refresh_tokens  (user_id,      ON DELETE CASCADE)
```

| Table | Columns |
|---|---|
| `users` | id PK, email UNIQUE, password_hash, full_name, role (attendee/organizer), created_at |
| `events` | id PK, organizer_id FK, title, description, category, city, venue, start_time, price_cents, capacity, tickets_sold, status (published/cancelled/completed), created_at, updated_at |
| `bookings` | id PK, user_id FK, event_id FK, quantity, total_cents, status (confirmed/cancelled_by_user/cancelled_by_organizer), refund_status (none/pending), created_at, cancelled_at |
| `refresh_tokens` | jti PK, user_id FK, family_id, revoked, expires_at, created_at |

**Constraints (enforced by the database itself):**
`capacity > 0`, `price_cents >= 0`, `quantity > 0`, and **`0 <= tickets_sold <= capacity`**.
That last rule is a safety net: even a buggy code path cannot oversell.

**Indexes:** `users(email)` unique; `events(organizer_id)`; composite `events(city, start_time)`,
`events(category, start_time)`, `events(status, start_time)` for the filtered public list;
`bookings(user_id, created_at)` for history; `bookings(event_id, status)` for the organizer dashboard;
`refresh_tokens(user_id)` and `(family_id)` for revocation.

**Cascade rules:** bookings, events and users use `RESTRICT`, so financial history cannot be erased by
deleting a parent. Events with bookings must be *cancelled*, not deleted. Refresh tokens use `CASCADE`
because they have no value without their user.

**Design choices:** money is stored as integer cents (no float rounding). `tickets_sold` is a counter on
the event so availability checks are one indexed row instead of a SUM over bookings.

---

## How overbooking is prevented

**The problem:** a naive flow is *read* `tickets_sold`, *check* there is room, then *write*. Two requests can
both read "1 seat left", both pass the check, and both write, selling a seat twice.

**The fix:** the check and the reservation happen in **one atomic SQL statement**:

```sql
UPDATE events
SET    tickets_sold = tickets_sold + :qty
WHERE  id = :event_id
  AND  status = 'published'
  AND  start_time > :now
  AND  tickets_sold + :qty <= capacity;
```

The booking row is inserted in the **same transaction**, then committed. If the statement updates **1 row**,
the seats are ours. If it updates **0 rows**, the request is rejected with a specific 409 (sold out,
cancelled, or started).

**Two people grab the last seat at the same time:**
1. Both send `UPDATE ... WHERE tickets_sold + 1 <= capacity` with `tickets_sold = capacity - 1`.
2. The database takes a row lock on the event for the first statement. The second waits.
3. The first sets `tickets_sold = capacity` and commits (booking created, `201`).
4. The second wakes up and re-evaluates its `WHERE` against the **new** value. `capacity + 1 <= capacity` is
   false, so 0 rows are updated and the API returns `409 INSUFFICIENT_CAPACITY`.

Exactly one wins and the other gets a clean error, with no double-sale and no lost update. This works on
PostgreSQL (row lock, `READ COMMITTED` re-check) and SQLite (single writer), with no explicit locking code.

**Defence in depth:** the `CHECK (tickets_sold <= capacity)` constraint would make the database reject an
oversell even if application code were wrong.

**The same pattern protects other flows:** cancelling a booking claims it with
`UPDATE bookings SET status=... WHERE id=? AND status='confirmed'`, so a double-click cannot release seats
twice. Refresh-token rotation uses the same "flip a flag atomically" trick.

**Tests:** `tests/test_concurrency.py` fires simultaneous requests from threads released by a barrier:
20 buyers for 5 seats (exactly 5 succeed, `tickets_sold == 5`), 2 buyers for the last seat, mixed
quantities, and concurrent reuse of one refresh token.

---

## Conflict and error-handling plan

- **One error shape** for everything: `{"error": {"code", "message", "details"}}`. Handlers are registered
  for validation errors, HTTP errors, our `ApiError`, and a catch-all (500 never leaks stack traces).
- **Validation first:** Pydantic rejects malformed payloads (bad email, weak password, unknown role or
  category, past `start_time`, non-positive capacity, quantity outside 1 to 10) with 422 and per-field details.
- **State conflicts return 409** with a specific code, so clients can react (sold out vs cancelled vs started).
- **Race-safe by construction:** conflicts are decided by atomic conditional updates, not read-then-write.
  Unique-email races are caught from the database `IntegrityError`.
- **Ownership failures return 404, not 403**, so one organizer cannot discover another's event IDs.
- **Transactions:** every multi-step write commits once, or rolls back fully on failure.

---

## Security guidelines

- **Passwords:** hashed with **bcrypt** (per-password salt, deliberately slow). Plaintext is never stored or
  logged, and hashes are never returned by the API (response schemas exclude them).
- **Authentication:** JWT bearer tokens. Access tokens are short-lived (15 min). Tokens carry a `type` claim,
  so a refresh token cannot be used as an access token.
- **Refresh-token rotation + revocation:** refresh tokens are single-use and tracked in `refresh_tokens`.
  Using one a second time revokes the entire token family (a stolen token is dead after one reuse). Logout
  revokes the family.
- **Authorization:** role checks on every endpoint (`require_role`), plus per-resource ownership checks for
  organizers (events) and attendees (bookings).
- **Input validation:** strict schemas, bounded string lengths, enums for categories/roles/statuses,
  pagination capped at 100. SQL is built through SQLAlchemy (parameterized), so no SQL injection.
- **No user enumeration:** login returns the same error for wrong password and unknown email.
- **Secrets:** `JWT_SECRET` and `DATABASE_URL` come from environment variables. `.env` is git-ignored;
  `.env.example` holds placeholders. Docker Compose refuses to start without `JWT_SECRET`. Rotate the
  secret if it leaks (this invalidates all tokens).
- **Abuse control:** booking attempts are rate limited per user (5/min, `429` + `Retry-After`).
- **Container:** runs as a non-root user, with a health check.
- **Before real production:** serve over HTTPS (TLS-terminating proxy), restrict CORS to your frontend,
  add login rate limiting, use a Redis-backed limiter for multi-instance deployments, add email
  verification and password reset, and use Alembic migrations.

---

## Test plan

Run `python -m pytest -v`.

| Area | Valid case (expected) | Invalid case (expected) |
|---|---|---|
| Register | 201, no password in response | 422 for bad email, short or weak password, bad role, empty name; 409 duplicate email (case-insensitive) |
| Login / tokens | 200 with token pair | 401 `INVALID_CREDENTIALS` (same message for both causes); refresh token rejected as access token |
| Refresh | Rotation returns a new pair | Replaying an old token gives 401 `TOKEN_REUSED` and revokes the family; after logout, refresh gives 401 |
| Create event | Organizer gets 201 | Attendee 403; anonymous 401; past date, capacity 0, negative price, unknown category, short title give 422 |
| Browse | Public; filters by city, category, price, date range, text, availability; hides past and cancelled events | Inconsistent filters give 422; `page_size` over 100 gives 422 |
| Ownership | Owner can edit, delete, cancel, view sales and bookings | Other organizer gets 404 on all five; attendee gets 403 |
| Edit | Owner can edit | After start gives 409; capacity below sold gives 409 |
| Delete | No bookings gives 204 | With bookings gives 409 |
| Cancel event | All bookings become `cancelled_by_organizer` and `refund pending`; new bookings get 409 `EVENT_CANCELLED` | Second cancel gives 409 |
| Booking | 201 with correct total; seats decrement | Over capacity gives 409 with remaining seats; started or cancelled event gives 409; unknown event gives 404; organizer gets 403; quantity 0 or 11 gives 422 |
| Cancel booking | Inside window gives 200, seats released, refund pending | Outside window gives 409; double cancel gives 409 (seats not released twice); someone else's booking gives 404 |
| Dashboard | Sales numbers match bookings and cancellations | n/a |
| Rate limit | 5 bookings succeed | 6th within a minute gives 429 with `Retry-After` |
| **Concurrency** | 20 buyers, 5 seats gives exactly 5 x 201 and 15 x 409; 2 buyers, last seat gives one winner; mixed quantities never exceed capacity; one refresh token used 5 times at once gives one 200 | `tickets_sold` never exceeds `capacity` |
