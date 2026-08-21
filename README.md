# Optimism — FastAPI Replacement (implementation repo)

Fresh implementation of [DoES Liverpool](https://doesliverpool.com)'s
resource-booking system ("Optimism") as a single **FastAPI modular monolith**
(ADR-001), replacing the legacy Node/Express API + website split. The legacy
codebase lives in `legacy/` (git submodule, pinned at `e5eef9c`) as **read-only
behavioural reference**.

## Documentation

The authoritative planning/reference docs live in `docs/planning/`:

| File | What it is |
|---|---|
| `API_SPEC.md` | **Authoritative API contract** for the FastAPI implementation (`/api/v1`, RFC 7807, exact-window booking, hashed tokens, email outbox, rate limits, admin auth). |
| `IMPLEMENTATION_PLAN.md` | Test-first delivery order, quality gates, checklist. |
| `EVALUATION.md` | Current-state evaluation of the legacy system. |
| `PLAN_REVIEW.md`, `summary.md`, `todo.md` | Planning decisions and open items. |
| `arc42/` | 12-chapter architecture documentation (incl. ADR log). |
| `IMPLEMENTATION_LOG.md` | Append-only log of the implementation work. |

## What is implemented

- **API** (`/api/v1`, internal-only): resources, resource-types, availability
  windows & exceptions, bookings (create/lookup/amend/cancel + admin list with
  filters/pagination), calendar availability, admin login/logout — exactly per
  `API_SPEC.md`.
- **Business rules**: exact-window matching, one-off exceptions (closed/open),
  transactional capacity under a PostgreSQL advisory lock (no overbooking),
  idempotent cancellation, configurable cancellation cutoff, SHA-256-hashed
  cancellation tokens (raw token returned once), fixed UTC (ADR-007).
- **Security**: shared-admin bcrypt credential, server-side revocable sessions,
  CSRF double-submit cookie on all admin writes, per-IP rate limits,
  append-only audit log with `shared_admin` actor.
- **Email outbox** (ADR-010): confirmation composed verbatim per ADR-015,
  persisted in the booking transaction, worker with exponential back-off and
  dead-letter after max attempts.
- **Web UI**: server-rendered public booking flow (home → resource → time →
  details → confirmation → cancel) with a progressively-enhanced week
  calendar, plus a full admin UI (login, dashboard, resources, resource types,
  windows, exceptions, bookings). Two UI themes are available, chosen at
  deployment time via `WEB_THEME` (not in the UI):
  - `WEB_THEME=modern` (default) — the current custom accessible stylesheet;
  - `WEB_THEME=legacy` — the Bootstrap 4.5 look of the old DoES site
    (vendored assets, same routes and data).
- **Observability**: structured JSON logs with request IDs, `/healthz`,
  `/readyz`, Prometheus `/metrics` (ARC 42 §8.2).

## Layout

```text
app/
  main.py            # application factory, lifespan, middleware
  core/              # config (Settings), logging, security, exceptions, rate limit, metrics, time
  db/                # SQLAlchemy engine/session, declarative base
  models/            # typed ORM models
  domains/           # resources, windows, bookings, calendar, admin (schemas/repo/service/router)
  integrations/email # provider abstraction + preserved confirmation template
  web/               # Jinja templates, static assets, web router
  migrations/        # Alembic versions
tests/               # unit, api, web, integration (+factories)
scripts/             # seed_dev.py (legacy-mirroring dev data)
```

## Development

Requires [uv](https://docs.astral.sh/uv/) and Python ≥ 3.12.

```bash
cp .env.example .env          # then edit DATABASE_URL + secrets
make install                  # uv sync (creates .venv)
make secret                   # write docker-compose secret files (dev defaults)
make dev                      # uvicorn app.main:app --reload on :8000
```

The web UI is at `http://localhost:8000`; interactive API docs at `/docs`;
admin login uses the password configured via `ADMIN_PASSWORD_HASH`
(`change-me` for the dev default — generate a real hash with `make hash`).

### Docker (dev/staging)

```bash
make secret                   # once: writes ./secrets/*.txt
make up                       # docker compose up -d --build (migrations auto-run)
docker compose exec web uv run python scripts/seed_dev.py   # optional seed data
```

To use the old Bootstrap look instead of the default UI:

```bash
WEB_THEME=legacy make up      # or: WEB_THEME=legacy docker compose up -d
```

### Tests & quality gates

```bash
make verify                   # ruff format+lint, mypy, full pytest suite
make test-integration         # PostgreSQL tests (migrations, concurrency) — needs a PG
make coverage                 # branch coverage report (80% floor)
```

The full suite runs against an in-memory SQLite database (test convenience);
PostgreSQL-specific behaviour (Alembic migrations, GiST exclusion constraint,
advisory-lock concurrency) is exercised by `tests/integration` against
`TEST_DATABASE_URL` (default `localhost:5432/optimism_test`).

## Deployment notes

- Migrations run before traffic: `alembic upgrade head` in CI/startup
  (`AUTO_MIGRATE=true` for dev/staging; a separate job before traffic in
  production, arc42 §7.5).
- Secrets (`ADMIN_PASSWORD_HASH`, `SESSION_SECRET`, SMTP credentials) are
  injected via Docker secrets / env; never commit them. Docker `*_FILE`
  variants are supported.
- The API is internal-only; no CORS headers are served; the same-process web
  UI is the only consumer (ADR-001).

## Maintenance

- Planning docs are copies of the working originals in
  `/home/doesliverpool-0/dev/optimism`; refresh with `cp` when they change.
- Bump the legacy reference: `git -C legacy fetch && git -C legacy checkout <commit>`.
