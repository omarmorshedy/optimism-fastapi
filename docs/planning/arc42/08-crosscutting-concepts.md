# 8. Crosscutting Concepts

## 8.1 Security

### 8.1.1 Authentication
- **Admin**: Single shared credential → bcrypt hash stored in secret (`ADMIN_PASSWORD_HASH`).
- **Session**: Signed cookie (`itsdangerous` or `starlette.middleware.sessions`) with `SESSION_SECRET`.
- **CSRF**: Double-submit cookie pattern (`fastapi-csrf-protect` or custom middleware) on all state-changing HTML forms and API write endpoints.
- **Rate Limiting**: Token-bucket per IP (configurable via `RATE_LIMIT_*` env vars) using `fastapi-limiter` (Redis-backed) or in-memory fallback for single instance.
- **Password Hashing**: `passlib` with bcrypt (cost 12).
- **Secrets**: Never in code, Docker args, or logs. Injected via Docker secrets / K8s secrets.

### 8.1.2 Authorization
| Role | Capabilities |
|------|--------------|
| `public` | Read resources, windows, exceptions; create booking; cancel own booking via token |
| `admin` (session) | Full CRUD on all entities; view all bookings; cancel/amend any booking |

Enforced via FastAPI dependencies:
- `get_current_admin_session` → raises 401/403
- `require_admin` on admin HTML routes
- API write routers check `current_admin` dependency

### 8.1.3 Data Protection
- **Cancellation tokens**: Only salted hash stored (`bcrypt`); raw token sent once in email.
- **Email outbox**: Stores only reference IDs, not email bodies.
- **Logs**: Structured JSON; **never** log passwords, tokens, email bodies, or full PII. Correlation IDs only.
- **HTTPS**: Enforced at ingress; `Secure` and `HttpOnly` cookies; `SameSite=lax`.

## 8.2 Observability

### 8.2.1 Structured Logging
- Library: `structlog` + stdlib `logging`
- Format: JSON, one line per event
- Fields:
  ```json
  {
    "timestamp": "2026-08-06T12:34:56.789Z",
    "level": "info",
    "logger": "app.domains.bookings.service",
    "event": "booking_created",
    "request_id": "abc123",
    "booking_id": 42,
    "resource_id": 1,
    "duration_ms": 45
  }
  ```
- **No PII**: `name`, `email`, `notes`, `token` never logged.

### 8.2.2 Metrics (Prometheus)
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `http_requests_total` | Counter | `method`, `path`, `status` | Request volume |
| `http_request_duration_seconds` | Histogram | `method`, `path` | Latency |
| `booking_created_total` | Counter | `resource_id`, `status` | Booking outcomes |
| `booking_cancelled_total` | Counter | `resource_id` | Cancellations |
| `email_outbox_pending` | Gauge | — | Pending emails |
| `email_sent_total` | Counter | `status` (sent/failed/dead_letter) | Email outcomes |
| `db_pool_usage` | Gauge | `pool` (main/worker) | Connection pool |
| `rate_limit_exceeded_total` | Counter | `endpoint` | Rate limit hits |

Exposed at `/metrics` (Prometheus text format).

### 8.2.3 Health & Readiness
| Endpoint | Purpose | Checks |
|----------|---------|--------|
| `GET /healthz` | Liveness (process alive) | Always 200 OK |
| `GET /readyz` | Readiness (ready for traffic) | DB reachable, migrations applied, email worker alive |

### 8.2.4 Alerting Rules (Prometheus Alertmanager)
| Alert | Expression | Severity |
|-------|------------|----------|
| `High5xxRate` | `rate(http_requests_total{status=~"5.."}[5m]) > 0.01` | critical |
| `BookingCreationFailures` | `increase(booking_created_total{status="failed"}[5m]) > 0` | warning |
| `EmailBacklog` | `email_outbox_pending > 100` | warning |
| `DBPoolExhaustion` | `db_pool_usage / db_pool_max > 0.9` | critical |

## 8.3 Error Handling

### 8.3.1 RFC 7807 Problem Details
All API errors return `application/problem+json`:
```json
{
  "type": "https://optimism.example.com/errors/overbooking",
  "title": "Resource fully booked",
  "status": 409,
  "detail": "The selected window has reached its capacity.",
  "instance": "/api/v1/bookings",
  "request_id": "abc123"
}
```
Global exception handler maps:
- `ValidationError` → 422
- `IntegrityError` (unique/exclusion) → 409
- `AuthenticationError` → 401
- `AuthorizationError` → 403
- `NotFound` → 404
- Unhandled → 500 (logged with traceback, correlation ID)

### 8.3.2 HTML Error Pages
- Rendered via Jinja templates (`error.html`) for web routes
- Show user-friendly message; log full detail server-side

## 8.4 Internationalization / Localization
- **Single locale**: English (UK) for v1
- Date/time formatting: UTC, ISO 8601 in API; `DD MMM YYYY, HH:mm` in UI (via `babel` or `moment.js` equivalent)
- Number formatting: `.` decimal, `,` thousands

## 8.5 Configuration Management
- **Single source**: `core.config.Settings` (Pydantic `BaseSettings`)
- **Validation**: Type coercion, enum checks, URL parsing
- **Defaults**: Sensible values (see [Configurable Constants](#configurable-constants))
- **Environment-specific**: `.env` for dev; secrets for staging/prod
- **No runtime mutation**: Settings are frozen after startup

## 8.6 Database Conventions
- **Naming**: `snake_case` tables/columns; `plural` table names
- **Primary Keys**: `BIGINT GENERATED ALWAYS AS IDENTITY` (or `UUID` if distributed later)
- **Timestamps**: `created_at` / `updated_at` (UTC, `timestamptz`) on all mutable tables
- **Soft Deletes**: `status` enum or `deleted_at` (no hard deletes)
- **Indexes**: Explicit on FK columns, query predicates (`resource_id, weekday, starts_at`), `token_hash`
- **Constraints**: Declarative (NOT NULL, CHECK, UNIQUE, EXCLUSION, FK)

## 8.7 Testing Conventions
| Layer | Tool | Naming | Coverage Target |
|-------|------|--------|-----------------|
| Unit | pytest | `test_<module>_<function>` | 90% branch (domain) |
| Integration | pytest + testcontainers | `test_<domain>_<scenario>` | 80% branch |
| API Contract | pytest + HTTPX | `test_api_<endpoint>_<case>` | 100% endpoints |
| E2E | Playwright | `test_<journey>_<step>` | All critical journeys |
| Mutation | mutmut | — | Critical domain rules |

Fixtures: typed factories in `tests/factories/`; no shared mutable state.

---

> **Traceability**: [Evaluation §7, §8.3](../../EVALUATION.md), [Implementation Plan §1, §8](../../IMPLEMENTATION_PLAN.md).