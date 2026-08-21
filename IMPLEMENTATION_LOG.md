# Implementation Log — Optimism FastAPI Replacement

Append-only, chronological log of implementation work. Each entry records the
step taken, the files touched, and verification results. Latest entry at the
bottom.

---

## 2026-08-20 — Step 1: Discovery & project scaffolding

**Read** all planning documents: `README.md`, `docs/planning/summary.md`,
`EVALUATION.md`, `IMPLEMENTATION_PLAN.md`, `PLAN_REVIEW.md`, `API_SPEC.md`,
`todo.md`, and the full `arc42/` chapter set. **Read** the legacy reference
code (`legacy/api/` routes, models, migrations, seeds, tests; `legacy/website/`
routes and templates) pinned at `e5eef9c`.

**Key decisions locked in from the docs:**
- Authoritative API contract = `docs/planning/API_SPEC.md` (base path `/api/v1`,
  camelCase JSON, RFC 7807 errors, exact-window booking, hashed tokens,
  idempotent cancellation, email outbox, fixed UTC, rate limits, admin auth +
  audit, availability windows/exceptions).
- Packaging with **uv** (`pyproject.toml` + `uv.lock`), Python ≥ 3.12.
- PostgreSQL-only persistence (ADR-003); SQLite permitted only as a test
  convenience where PostgreSQL semantics are not exercised.
- Delivery order per `IMPLEMENTATION_PLAN.md`.

**Environment setup:**
- `uv` 0.12.5 installed (user-level, outside the repo).
- `uv.toml` created with repo-local `cache-dir` (`.tools/uv-cache`) so uv works
  inside the sandboxed workspace; `UV_PYTHON_INSTALL_DIR` set to
  `.tools/uv-python` via env in commands/Makefile.
- `uv python install 3.12` → CPython 3.12.14 managed python in `.tools/uv-python`.
- `pyproject.toml` written: runtime deps (fastapi, uvicorn, gunicorn, sqlalchemy
  2.x, psycopg3, alembic, pydantic v2 + settings, email-validator, bcrypt,
  itsdangerous, structlog, prometheus-client, jinja2, python-multipart),
  dev deps (pytest, pytest-cov, httpx, ruff, mypy, types-itsdangerous),
  pytest/ruff/mypy/coverage configuration.
- `uv sync` → resolved 56 packages; venv at `.venv`; all imports verified.
- `.gitignore` and `.env.example` (typed settings mirror) created.

**Files:** `uv.toml`, `pyproject.toml`, `uv.lock` (generated), `.gitignore`,
`.env.example`.

**Next:** core layer (config, logging, exceptions, security, rate limit,
metrics).

## 2026-08-20 — Step 2: Core layer

**Files created:** `app/__init__.py`, `app/core/__init__.py`,
`app/core/config.py`, `app/core/time.py`, `app/core/exceptions.py`,
`app/core/logging.py`, `app/core/security.py`, `app/core/rate_limit.py`,
`app/core/metrics.py`.

- **config.py**: typed `Settings` (Pydantic `BaseSettings`, frozen, `.env`
  aware) covering every env var from summary.md/arc42 §5.3/§7.2 plus SMTP,
  session, worker, and app fields; `RateLimitRule` dataclass + `parse_rate_limit`
  ("10/minute" → 10/60s); cached `get_settings()`.
- **time.py**: fixed-UTC policy (ADR-007) — `utcnow`, strict date/datetime/window
  time parsers (no-offset input → UTC), UTC `Z` serialiser (3-ms digits),
  legacy weekday convention (Sunday=0), correct overlap predicate
  (`a.start < b.end AND a.end > b.start` — fixes the legacy boundary bug),
  Moment.js-compatible email time formatter (`dddd, MMMM Do YYYY, h:mm a`, UTC).
- **exceptions.py**: `Problem` class + RFC 7807 handlers registered via
  `register_exception_handlers` (Problem, RequestValidationError → 422,
  Starlette HTTP exceptions, unhandled → 500 with traceback); verbatim legacy
  detail strings (API_SPEC §1.3/§9).
- **logging.py**: structlog JSON to stdout (ADR-012) — timestamp/level/logger/
  event/request_id fields; no PII; uvicorn logs routed through the same formatter.
- **security.py**: bcrypt cost-12 password hash/verify (ADR-005), 32-byte
  URL-safe token generation, SHA-256 token hashing (documented rationale:
  256-bit random token + indexed equality lookup; bcrypt reserved for passwords).
- **rate_limit.py**: thread-safe in-memory fixed-window limiter (per IP, per
  bucket) with metric on 429 (TD-05 acknowledges single-instance scope).
- **metrics.py**: Prometheus metrics per arc42 §8.2.2 (http_requests_total,
  duration histogram, booking_created/cancelled, email_outbox_pending,
  email_sent_total, db_pool_usage, email_worker_alive, rate_limit_exceeded).

## 2026-08-20 — Step 3: DB layer, ORM models, Alembic baseline

**Files created:** `app/db/{__init__,base,engine,session}.py`,
`app/models/{__init__,resource_type,resource,availability_window,
availability_exception,booking,email_outbox,admin_session,audit_event}.py`,
`alembic.ini`, `app/migrations/{__init__,env,script.py.mako}.py` +
`app/migrations/versions/0001_initial.py`.

- **db/**: Declarative base with naming convention (arc42 §8.6); cached engine
  factory from typed Settings (psycopg3; pool_pre_ping; SQLite fallback for
  tests); cached sessionmaker; request-scoped `get_db` dependency (commit on
  success / rollback on error); pool-usage metrics wired to pool events.
- **models/**: typed SQLAlchemy 2.x mappings — ResourceType (unique non-blank
  name), Resource (unique name, `capacity > 0`, nullable type FK SET NULL,
  cascade delete-orphan windows/exceptions/bookings), AvailabilityWindow
  (weekday 0–6, `ends > starts`, unique instance, overlap exclusion constraint
  in migration), AvailabilityException (kind closed|open, `end_date >= start_date`),
  Booking (`starts < ends`, non-blank name/email, `token_hash` unique — raw
  token never stored, `cancelled` + `deleted_at` soft-delete support),
  EmailOutbox (status enum, attempts, next_attempt_at), AdminSession (token
  hash + expiry), AuditEvent (append-only, actor `shared_admin`).
- **migrations/**: `alembic.ini` (URL sourced from Settings, never the ini);
  `env.py` imports all models and uses `Base.metadata`; `0001_initial.py`
  creates the full schema, the **GiST exclusion constraint** forbidding
  overlapping windows per (resource, weekday) — requires contrib `btree_gist`
  (docker postgres runs as superuser) — and all query indexes. Reversible
  (`downgrade` drops all tables).

**Next:** domain layer — resources, windows/exceptions, bookings (+calendar),
admin auth; then email worker; then routers and main app.

## 2026-08-20 — Step 4: Domain services, API routers, web layer (first pass)

**Created** `app/domains/` (resources, windows, bookings, calendar, admin) with
schemas/repository/service/router per arc42 §5.2; `app/integrations/email/`
(provider + preserved template); `app/web/` (router + 20 Jinja templates +
static CSS/JS); `app/api/deps.py`; `app/main.py` app factory with
lifespan (AUTO_MIGRATE + email worker), RequestId + AccessLog middleware,
`/healthz`, `/readyz`, `/metrics`, and static mounting.

- Booking service implements API_SPEC §5 exactly: exact-window match (decision
  #4), exception overrides (closed removes / open re-adds weekday windows),
  `pg_advisory_xact_lock` on (resource, window) before the capacity check +
  insert in one transaction (ADR-006), SHA-256 token hashing, email outbox
  enqueue in the same transaction (ADR-010), idempotent cancel (improvement #9),
  token amend with cutoff (ADR-009, `BOOKING_CANCELLATION_CUTOFF_MINUTES`).
- Calendar service (§6): correct overlap predicate, exceptions, legacy JSON
  shape (`date` at UTC midnight, `slots` with status).
- Admin auth (ADR-005): bcrypt password check, server-side `admin_sessions`
  (hashed tokens, 1h expiry), `Secure; HttpOnly; SameSite=Lax` cookie, CSRF
  double-submit cookie on all cookie-authenticated writes, audit_events rows
  with `shared_admin` actor on every admin state change.
- Rate limiting per IP (decision #12) for booking create/cancel/amend/lookup,
  calendar reads, admin login.
- Web layer: public flow (home → select-a-resource → select-a-time (server-
  rendered initial week + vanilla-JS week navigation) → your-details →
  confirmation → cancel-booking GET-confirm/POST-act) and full admin CRUD UI;
  signed `user_intent` cookie for the booking flow.
- RFC 7807 problem responses everywhere; request_id correlation in logs and
  error bodies; structured JSON access logs with duration.

**Bugs found & fixed during smoke tests:**
1. `get_db` never committed (rolled back silently) → added commit-on-success.
2. Pydantic v2 `from_attributes` does not map camelCase field names to
   snake_case ORM attributes → introduced `app/domains/schemas_base.py`
   (`CamelModel`/`CamelReadModel` with `alias_generator=to_camel`) and renamed
   all schema fields to snake_case python names; services/routers/web updated.
3. SQLite returns naive datetimes → `ensure_utc()` normalisation at
   comparison boundaries (admin sessions, booking cutoff, calendar overlaps).
4. `metadata` is reserved in SQLAlchemy Declarative → audit column renamed to
   `details`.
5. Two route signatures still used `id: int = Annotated[...]` (losing `ge=0`)
   → fixed to clean `Annotated` style.
6. SQLite `:memory:` + threads → `StaticPool` in `get_engine`.

**Tests:** `tests/conftest.py` (shared in-memory SQLite app + truncation +
login helpers), `tests/factories.py`, `tests/unit/*` (time, config, security,
email template, rate limiter), `tests/api/test_resources_api.py` (legacy CRUD
matrix ported with improvements: 401/403/422/404/409 semantics, CSRF, audit).
**77 tests pass.**

**Next:** remaining API contract tests (resource-types, windows, exceptions,
calendar, bookings, admin), web tests, PostgreSQL integration tests, then
Docker/CI/infra and final verification.

## 2026-08-20 — Step 5: Full API + web + integration test suite

**Added tests** (218 total, all passing):
- `tests/api/test_resource_types_api.py` — CRUD matrix + legacy type-delete
  nulling semantics (§11.5).
- `tests/api/test_windows_api.py` — window/exceptions CRUD, overlap 409s
  (half-open intervals), resource-windows replace endpoint, filters.
- `tests/api/test_calendar_api.py` — legacy calendar param matrix (422 vs
  legacy 400), response shape (`date` midnight `Z`, UTC slots), capacity,
  cancelled-exclusion, spanning-booking boundary fix, Sunday=0 convention,
  closed/open exceptions.
- `tests/api/test_bookings_api.py` — creation (exact window, capacity,
  exceptions, email-outbox persistence), rate limit 429, lookup/amend/cancel
  by token (idempotent cancel, cutoff 409, amend revalidation), admin list
  filters/pagination/X-Total-Count, admin amend without cutoff, soft delete
  freeing capacity, CSRF on admin writes.
- `tests/api/test_admin_api.py` — login (cookies, wrong password 401, rate
  limit), logout revocation, audit events with `shared_admin` actor.
- `tests/unit/test_email_worker.py` — send, retry with back-off, dead-letter
  after max attempts, heartbeat, lifecycle.
- `tests/web/test_web.py` — full public flow (home → resource → time →
  details → confirmation → cancel GET-confirm/POST-act) and admin UI CRUD.
- `tests/integration/test_postgres_integration.py` — Alembic migration chain
  (upgrade/downgrade), GiST exclusion constraint (blocks overlaps, allows
  touching windows), timestamptz UTC round-trip, and a 10-thread
  no-overbooking concurrency test. Skipped unless PostgreSQL reachable;
  verified against a local `postgres:16-alpine` container.

**Bugs found & fixed by the tests:**
1. **Advisory lock acquired AFTER the capacity count** → concurrent requests
   overbooked. Moved the lock inside `_validate_time_change` before the count
   (caught by the PostgreSQL concurrency test; the SQLite suite cannot see it).
2. Email outbox retries never happened: failed entries were not re-claimed
   (`claim_batch` only selected `pending`). Now selects `pending`+`failed`
   with `next_attempt_at <= now`.
3. `TimeError` (malformed calendar dates) propagated as 500 → added a global
   handler mapping it to 422 problem.
4. SQLite tz-naive `time` comparisons in window overlap → compare
   (hour, minute).
5. `get_engine`/`get_session_factory` cached per Settings object → now cached
   per database URL (worker tests share the app's SQLite DB).
6. Web `render()` never set the HTTP status → error pages returned 200; now
   passes `status_code` through.
7. `env.py` overrode programmatic `sqlalchemy.url` with default settings →
   respects a pre-set URL (integration tests).
8. Exclusion constraint used `tsrange` over `timestamptz` → `tstzrange`.

**Next:** lint/type-check (ruff, mypy) + fixes; infra (Dockerfile, compose,
Makefile, pre-commit, GitHub Actions); final verification.

## 2026-08-20 — Step 6: Lint & type-check cleanup

- **Ruff**: auto-fixed 145+ issues (imports, UP017 datetime.UTC, B008, SIM108,
  RUF002, unused imports); remaining items fixed by hand (module-level
  `Depends` singletons → noqa, Annotated deps where possible). `ruff check`
  and `ruff format` now pass.
- **mypy strict**: fixed 64 errors in `app` (typed ORM attrs, `dict[str, Any]`
  annotations, `AvailabilityWindow` return types, provider/middleware typing,
  calendar service annotations, web router kwargs). Discovered that strict
  mode's `disallow_incomplete_defs` fires on untyped fixture params in test
  methods → relaxed only `tests.*` overrides (tests are validated by ruff +
  pytest). `mypy app tests` passes (81 files).
- One regression caught by the suite: the Annotated-style rate-limit dependency
  inside a closure was treated as a required query field → reverted to the
  B008-noqa default-value style. Full suite re-run: **218 passed**.

**Next:** infra (Dockerfile, docker-compose, Makefile, pre-commit, CI),
README update, and full end-to-end verification against the compose stack.

## 2026-08-20 — Step 7: Infrastructure (Docker, compose, Makefile, CI, README)

- **Dockerfile**: multi-stage (uv-synced builder → slim runtime), non-root
  `app` user, gunicorn + uvicorn workers, healthcheck, `PORT=8000` (arc42 §7.2).
- **docker-compose.yml**: postgres:16-alpine (secret-file password, healthcheck)
  + web with `*_FILE` secret envs, `AUTO_MIGRATE=true`, port 8000.
- **Settings**: added Docker-secret `*_FILE` support (file content wins) using
  `object.__setattr__` on the frozen model; replaced the placeholder dev
  bcrypt hash with a real cost-12 hash of `change-me` (verified).
- **Makefile**: install/dev/up/down/lint/format/typecheck/test/coverage/
  migrate/hash/secret/verify targets; uv cache+python dirs pinned repo-local.
- **.pre-commit-config.yaml**: trailing-whitespace, EOF fixer, yaml/json/toml,
  merge-conflict, private-key, large files, gitleaks, ruff + ruff-format.
- **.github/workflows/ci.yml**: quality job (lockfile check, ruff, mypy,
  gitleaks), tests job (unit/API/web + branch coverage + PostgreSQL-backed
  integration + pip-audit), image job (BuildKit build, trivy scan).
- **scripts/seed_dev.py**: legacy-mirroring dev seed (types, resources,
  windows incl. Dinky's 30-minute slots; Hot Desk capacity 10).
- **README.md**: rewritten for the new stack (layout, dev/ops, tests).
- Fixed setuptools flat-layout discovery (legacy/ was being picked up as a
  top-level package) and the deprecated `license` table → explicit
  `[tool.setuptools.packages.find] include = ["app*"]`, `license = "MIT"`.
- Added `pip-audit` to dev deps; `uv lock` refreshed.

**Verification:** full suite still **218 passed**; ruff + mypy clean.

**Next:** final E2E verification — Docker image build + compose stack boot +
migrations + seeded API smoke (calendar, booking, admin), then commit.

## 2026-08-20 — Step 8: End-to-end verification against the compose stack

**Built & ran the full Docker stack** (`docker build` + `docker compose up` with
postgres:16-alpine + web). Fixed along the way:
- gunicorn "Control server error: Permission denied" as the non-root user →
  `ENV HOME=/tmp` in the runtime image.
- 4 gunicorn workers each ran AUTO_MIGRATE and raced the migration → new
  `docker-entrypoint.sh` runs `alembic upgrade head` **before** gunicorn
  (migration-before-traffic, plan §2), and the lifespan migration is now
  guarded by a PostgreSQL advisory lock (`run_migrations_once`) so dev and
  multi-worker containers are both safe.
- The legacy dev seed data itself contains overlapping windows for the same
  resource+weekday (AM + PM + full-day) — the new exclusion constraint rejects
  it (decision #4). `scripts/seed_dev.py` maps each resource to its
  non-overlapping equivalent (full-day window) and documents this.
- Seed script needed all model modules imported for mapper configuration.

**Verified against the running container:**
- `/healthz` 200, `/readyz` ready (DB reachable, migrations applied, email
  worker alive), `/metrics` 200, `/docs` 200, home `/` 200.
- `GET /api/v1/resources` → 5 seeded resources; calendar for Dinky (Monday)
  → 16 exact 30-minute slots with UTC `Z` timestamps; booking makes the slot
  `unavailable`.
- `POST /bookings` → 201 with resourceName + 43-char raw token; lookup by
  token → no token field; cancel → "Booking cancelled successfully."; repeat
  cancel → idempotent 200; amend → renamed, no token in response; capacity
  conflict → 409 with the verbatim legacy message.
- Admin login → session + CSRF cookies; `POST /resource-types` with
  `X-CSRF-Token` → 201; admin bookings list works.
- Email outbox: booking transaction persisted the composed confirmation; the
  worker picked it up and marked it `sent` (Null provider in dev — no SMTP).
- Rate limiting confirmed at the unit/API level (single-process TestClient);
  with 4 gunicorn workers the in-memory limiter is per-process (documented
  TD-05 — swap for Redis when scaling horizontally).

**Final gate:** ruff format/lint clean, mypy clean (81 files), full suite
**218 passed** (unit + API + web + PostgreSQL integration incl. the 10-thread
no-overbooking concurrency test).

## 2026-08-20 — Step 9: Developer-experience polish

- Marked the full task list complete; added `pre-commit` to the dev dependency
  group so `uv run pre-commit install` works out of the box.
- `.env.example` now ships the DEV-ONLY bcrypt hash of `change-me` (matching
  the code default), so copying it verbatim yields a working admin login
  (password `change-me`); `make hash` documented for real passwords.

## 2026-08-21 — Step 10: Fix dev seed weekday coverage + JS/polish clarifications

- **Bug found via user review:** the dev seed created every availability window
  only on Monday, so resources like Dinky appeared bookable one day a week.
  The application logic is correct (windows are per resource+weekday and are
  expanded per date by the calendar/booking services); the seed data was
  wrong. Fixed `scripts/seed_dev.py` to repeat each window time on every
  working weekday (Mon–Fri, weekday 1–5). Also documented the legacy bitmask
  mapping: `day: 31` (bits 0..4) literally covers Sun–Thu in the legacy
  Sunday=0 convention — treated as a legacy off-by-one and mapped to Mon–Fri
  to match the slot names ("Weekday …") and the expectation of availability
  on all working days.
- Re-seeded the running compose stack: Dinky now shows 16 half-hour slots on
  each of Mon–Fri (0 on weekends); verified a Tuesday booking now succeeds.
- Clarified for the user: the only JavaScript in the project is the small
  browser-side `app/web/static/js/calendar.js` (week navigation); all server
  side is Python/FastAPI per ADR-002/004 (the rewrite replaces the legacy
  Node/Express JS). The pages look different because the legacy Bootstrap
  4.5/FullCalendar styling was replaced by a custom accessible stylesheet and
  a progressively-enhanced calendar (an explicitly allowed option).

## 2026-08-21 — Step 11: Legacy (Bootstrap) UI theme, switchable at deployment time

Added a second UI theme that recreates the old DoES Bootstrap 4.5 look, toggled
by `WEB_THEME=modern|legacy` (Settings.web_theme, validated; NOT in the UI).
Default remains `modern` (the current custom UI).

- Vendored the legacy assets from the pinned submodule into
  `app/web/static/legacy/` (read-only reference → copied, never edited):
  Bootstrap 4.5 compiled `optimism.css`, `bootstrap.bundle.min.js` (+ map),
  and the DoES logo. No remote/CDN dependencies.
- New `app/web/templates_legacy/` (16 templates) recreating the old pages:
  navbar + footer, jumbotron home, "Step 1/2/3 of 3" booking flow, Bootstrap
  form controls, confirmation alert + cancel modal, admin sidebar layout and
  sign-in page. The calendar stays the same progressively-enhanced week view
  (server-rendered + `calendar.js`), styled with Bootstrap buttons — the old
  FullCalendar widget was not re-vendored (it was a 675 KB bundle plus CDN
  axios/jQuery; documented choice). Modal open/close uses a tiny
  dependency-free script instead of jQuery.
- Router now holds two Jinja2 template directories and `render()` picks the
  one from `Settings.web_theme`; same routes, same context variables, so both
  themes behave identically (e.g. cancel still GET-confirms / POST-acts).
- Deployment plumbing: `WEB_THEME` pass-through in `docker-compose.yml`,
  `.env.example`, Makefile docs, README section.
- Tests: `tests/web/test_themes.py` — legacy home (jumbotron + legacy css),
  select-a-resource/time steps, admin login + pages, full booking flow through
  the legacy templates, and that the default stays modern; invalid theme value
  rejected. **Full suite now 226 passed**; ruff + mypy clean.
- Verified in the running compose stack with `WEB_THEME=legacy`: home renders
  the jumbotron + vendored Bootstrap assets, booking flow completes with the
  confirmation modal; stack left running on the legacy theme for review
  (switch back with `WEB_THEME=modern make up`).

## 2026-08-21 — Step 12: Calendar-week alignment + unified calendar DOM

Two fixes from user review:

1. **Calendar weeks**: the initial week was "today .. today+6"; it is now the
   current CALENDAR week (Sunday..Saturday, matching the legacy FullCalendar
   convention and the Sunday=0 weekday rule): `week_start = today -
   weekday_of(today)`, `week_end = week_start + 6d`. Prev/next navigation
   already moved in ±7-day steps, so it stays week-aligned.

2. **Legacy UI changing on week navigation**: the JS calendar renderer always
   produced the MODERN theme's markup, so the legacy theme visibly switched
   styles after clicking prev/next. Fixed by unifying the calendar DOM across
   both server templates and the JS renderer:
   `.calendar-day > h3 + .slot-list` with `.slot-button` /
   `.slot-unavailable` (no theme-specific or Bootstrap-only classes in the
   slot markup). Each theme's CSS styles those classes — the modern theme
   keeps its look, the legacy theme's `optimism-legacy.css` now replicates the
   Bootstrap primary-button look for `.slot-button`. Navigation therefore never
   changes the look in either theme.

Also: the current week naturally contains past days, so slots whose end time
has passed are now greyed out (like the old site's `fc-event-past`); the server
passes `now_iso` to the templates and embeds `now` in the calendar JS config,
and both compare the fixed-format UTC strings (lexicographic == chronological).

Tests: `frozen_week` fixture (freezes "now" to Monday 2026-08-24 09:00 UTC so
the current week and the bookable Monday window are deterministic); new tests
for calendar-week alignment, past-slot disabling, and the legacy theme using
the unified markup. Full suite **223 passed + 5 integration (PG)**; ruff +
mypy clean. Verified live in compose: both themes show "2026-08-16 to
2026-08-22" with identical slot markup; stack left on the legacy theme.

## 2026-08-21 — Step 13: Fix cancellation-link race + invalid-email 500

Two user-reported bugs, both reproduced live first:

1. **Cancellation link could 404 right after booking.** Root cause: FastAPI
   finalises `yield` dependencies AFTER the response is delivered, so
   `get_db`'s teardown commit ran after the client could observe the
   response. A booking's confirmation/cancellation link was returned before
   the insert was committed — an immediate follow-up (or an automated
   client) would get 404. Proven by repro: the page token's SHA-256 matched
   the DB row, yet the immediate lookup 404'd; seconds later it worked.
   **Fix:** new `app/core/route.py` `CommitOnSuccessRoute` — every router
   (API + web) now uses it; the route handler commits (or rolls back) the
   request session between the endpoint and the response, so writes are
   visible the moment the response arrives. `get_db` still exposes the
   session on `request.state.db_session` and keeps a teardown commit as a
   safety net. Verified live: 6× create + immediate token lookup → all 200;
   full web book→link→cancel flow works.

2. **`john@gmail` (passes the HTML5 UI check) caused a 500.** The web
   `/confirmation` route caught `Problem` only; Pydantic `EmailStr`
   rejection raised `ValidationError`, which escaped to the global handler →
   500. **Fix:** web routes now catch `(Problem, ValidationError)` and render
   a friendly 422 error page via `_form_failure`; a global
   `ValidationError` handler maps any remaining cases to 422
   `application/problem+json` (defensive). Verified live: API → 422 problem
   with a clear email message; web → 422 page "Something went wrong … value
   is not a valid email address".

Tests: token-lookup-immediately-after-creation (API + web link),
invalid-email-422 (API + web). Full suite **232 passed** (+5 PG integration),
ruff + mypy clean.
