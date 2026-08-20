# 9. Architecture Decisions (ADR Log)

Each decision is recorded as an Architecture Decision Record (ADR) with status **Accepted**.

## ADR-001: Modular Monolith over Microservices
**Date**: 2026-08-06  
**Status**: Accepted  
**Context**: Current system has split API/Website Node.js apps. Domain is small (resources, windows, bookings).  
**Decision**: Build a single FastAPI application serving both `/api/v1` and server-rendered HTML.  
**Consequences**:  
- Simpler deployment, no CORS, shared auth/session  
- Clear module boundaries allow future extraction if needed  
- Avoids distributed-system complexity (network latency, eventual consistency)

## ADR-002: FastAPI + Pydantic + SQLAlchemy 2.x (Sync)
**Date**: 2026-08-06  
**Status**: Accepted  
**Context**: Team knows Python; need type safety, automatic OpenAPI, mature ORM.  
**Decision**: FastAPI (web), Pydantic v2 (validation/schemas), SQLAlchemy 2.x sync (ORM), Alembic (migrations).  
**Consequences**:  
- Sync ORM sufficient for expected load; async available later if needed  
- Strong typing across request → service → database  
- Alembic provides reviewable, reversible migrations

## ADR-003: PostgreSQL Only (No SQLite Compatibility)
**Date**: 2026-08-06  
**Status**: Accepted  
**Context**: Production uses PostgreSQL; SQLite in tests hides locking/constraint differences.  
**Decision**: Use PostgreSQL in all persistent environments; ephemeral PostgreSQL (testcontainers) in CI.  
**Consequences**:  
- Tests exercise real constraints, exclusion locks, advisory locks  
- No "works in SQLite, fails in Postgres" surprises  
- Slightly heavier CI (acceptable)

## ADR-004: Server-Rendered HTML (Jinja2) + Minimal JS
**Date**: 2026-08-06  
**Status**: Accepted  
**Context**: Current UI is mostly forms; only FullCalendar needs JS.  
**Decision**: Jinja2 templates for all pages; bundle FullCalendar locally; no SPA framework.  
**Consequences**:  
- Accessible, SEO-friendly, simple  
- Only calendar fetch/render requires client-side code  
- Avoids JS build pipeline, state management complexity

## ADR-005: Shared Admin Credential (Single Role)
**Date**: 2026-08-06  
**Status**: Accepted  
**Context**: Product owner confirmed one shared credential; no MFA/SSO needed.  
**Decision**: Bcrypt hash stored in secret; secure signed session cookie; CSRF protection; audit log with generic `shared_admin` actor.  
**Consequences**:  
- Simplicity; no user table, password reset, role management  
- Audit trail still captures *that* an admin action occurred  
- If requirements change, can extend to user table later

## ADR-006: Capacity = Booking Count (No Per-Booking Quantity)
**Date**: 2026-08-06  
**Status**: Accepted  
**Context**: Current system counts overlapping bookings; product owner confirmed this semantics.  
**Decision**: `capacity` = max simultaneous bookings for a window; no `quantity` column.  
**Consequences**:  
- Simpler model; concurrency control via row/advisory lock on window  
- If "quantity" needed later, schema change required

## ADR-007: Fixed UTC (UTC+00:00) All Year
**Date**: 2026-08-06  
**Status**: Accepted  
**Context**: Product owner specified GMT/UTC+00:00; no BST/DST.  
**Decision**: Store all `timestamptz` in UTC; render UTC explicitly; `availability_window.starts_at/ends_at` are `time` interpreted as UTC.  
**Consequences**:  
- No timezone ambiguity; tests must include summer date  
- If local-time display needed later, add `display_timezone` setting

## ADR-008: Availability Windows Replace Slots/Bitmask
**Date**: 2026-08-06  
**Status**: Accepted  
**Context**: Legacy `slots` + `day` bitmask + `resources_slots` join is opaque and allows overlaps.  
**Decision**: `availability_window` per resource per weekday with `starts_at`/`ends_at` (`time`); unique + exclusion constraint prevents overlaps. `availability_exception` for holidays/closures.  
**Consequences**:  
- Clearer querying, explicit overlap prevention  
- Migration must explode bitmask → rows (one per set bit)  
- Cross-midnight windows not supported (single-day assumption)

## ADR-009: Cancellation Window Configurable (Default 5 min)
**Date**: 2026-08-06  
**Status**: Accepted  
**Context**: Users may amend/cancel up to booking start; cutoff should be adjustable.  
**Decision**: `BOOKING_CANCELLATION_CUTOFF_MINUTES` env var (default 5). Enforced in `BookingService`.  
**Consequences**:  
- No hard-coded magic numbers; adjustable without deploy  
- GET shows confirmation; POST (CSRF) performs state change

## ADR-010: Email Outbox with Retry / Dead-Letter
**Date**: 2026-08-06  
**Status**: Accepted  
**Context**: Current fire-and-forget email fails silently; no durability.  
**Decision**: `email_outbox` table; background worker polls, sends via SMTP, exponential back-off (configurable), dead-letter after max attempts + alert.  
**Consequences**:  
- Booking creation never fails due to SMTP outage  
- Delivery guaranteed (or visible failure)  
- Worker can scale horizontally with `FOR UPDATE SKIP LOCKED`

## ADR-011: Rate Limiting on Public Endpoints
**Date**: 2026-08-06  
**Status**: Accepted  
**Context**: API is internal-only but public web UI calls booking creation/calendar reads.  
**Decision**: Token-bucket per IP via `RATE_LIMIT_BOOKING_CREATE` (default 10/min) and `RATE_LIMIT_CALENDAR_READ` (default 60/min).  
**Consequences**:  
- Defensive against abuse / accidental loops  
- Configurable without code change

## ADR-012: Observability – JSON Logs + Prometheus Metrics
**Date**: 2026-08-06  
**Status**: Accepted  
**Context**: Current logging is ad-hoc; no metrics.  
**Decision**: `structlog` JSON to stdout; correlation IDs; Prometheus `/metrics`; alerts on 5xx>1%, email backlog>100, DB pool exhaustion.  
**Consequences**:  
- Standard tooling (Grafana, Loki, Alertmanager) works out of the box  
- No PII in logs

## ADR-013: Single Cutover (No Feature Flags)
**Date**: 2026-08-06  
**Status**: Accepted  
**Context**: Product owner: "brand new project, cut over in one step".  
**Decision**: No feature flags; parallel run in staging, then single production cutover with rollback plan.  
**Consequences**:  
- Simpler codebase (no toggles)  
- Requires thorough staging validation and time-bounded rollback

## ADR-014: WCAG 2.1 AA for Public Pages
**Date**: 2026-08-06  
**Status**: Accepted  
**Context**: Accessibility requirement confirmed.  
**Decision**: Semantic HTML, keyboard navigation, color contrast, axe-core in CI + manual review.  
**Consequences**:  
- Automated regression; manual check for complex components (calendar)

## ADR-015: Email Wording Preserved
**Date**: 2026-08-06  
**Status**: Accepted  
**Context**: Product owner: "email should be preserved".  
**Decision**: Confirmation email subject/body must match current production exactly; treated as immutable unless future decision.  
**Consequences**:  
- Template stored in code; any change requires explicit approval

---

> **Traceability**: All decisions derive from [Evaluation §10](../../EVALUATION.md), [Summary §Key Decisions](../../summary.md), and conversation history.