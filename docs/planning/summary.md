# Summary of Decisions and Conversation

This document captures the key decisions made during the planning phase for rewriting the Optimism booking system in FastAPI/SQLAlchemy, as well as pointers to the detailed evaluation and implementation plan.

## Key Decisions (from product owner)

| Question | Decision |
|----------|----------|
| **1. Production database** | The authoritative production database is the **PostgreSQL container** used in the current Docker‑Compose setup. Data volume is minimal (approximately the size of the seed data). No formal backup/restore process is currently in place, and none is required for the initial release. Cut‑over downtime can be kept short; exact limits to be confirmed. |
| **2. Administrator authentication** | Administrators use **one shared credential**. The replacement will use a salted password hash stored in secret management, secure server-side/revocable sessions, CSRF protection, rate limiting, and a generic shared‑admin audit actor. No individual roles/MFA/SSO unless the decision changes. |
| **3. Meaning of `capacity`** | `capacity` means the **maximum number of simultaneous booking records** for a given resource/window (current behaviour). Users do **not** specify a quantity; each booking consumes one unit of capacity. |
| **4. Slot overlapping** | A slot is a **fixed resource‑specific availability window**. A booking must exactly match its start/end times and cannot be flexibly placed inside it. **Overlapping windows for the same resource and weekday are NOT permitted**. However, a resource may have multiple **non‑overlapping** windows (e.g., separate morning and afternoon slots) to reflect multiple availabilities at the same time of day. |
| **5. One‑off exceptions (holidays, special events)** | One‑off exceptions such as holidays, closures, and special events **ARE required** in the first release. An `availability_exceptions` table (or equivalent) will be included to override recurring windows. |
| **6. Booking lifecycle & cancellation** | Users may **view, amend, or cancel** a booking up to the time the booking would start. The cutoff (e.g., “start time minus X minutes”) should be a configurable variable so it can be adjusted in the future. |
| **7. Data‑privacy & compliance** | There are **no GDPR or similar data‑retention, export/deletion, consent, or audit requirements** that the system must enforce. |
| **8. API exposure** | The API should **not** be exposed to the public; it will be internal‑only behind the web application. |
| **9. URL/API contract & email preservation** | The existing URLs/API contract **do not need to be preserved**. However, the **email confirmation wording and subject should be preserved** to maintain user expectations. |
| **10. Frontend technology choice** | A server‑rendered responsive website is acceptable; a JavaScript SPA or mobile app is **not** required. |
| **11. Slot single‑day assumption** | Slots are confined to a single UTC day (00:00–24:00); crossing‑midnight windows are **not supported** in the first release. |
| **12. Rate limiting** | A defensive rate limit will be applied on public‑facing endpoints (e.g., 10 req/min per IP for booking creation, 60 req/min for calendar reads). |
| **13. Email retry policy** | Exponential back‑off (1 min, 2 min, 4 min, 8 min, 16 min) up to 5 attempts; on final failure move to dead‑letter and alert. |
| **14. Observability** | Emit structured JSON logs to stdout; expose Prometheus `/metrics` endpoint; alert on 5xx > 1%, booking failures, email backlog > 100, DB pool exhaustion. |
| **15. Accessibility target** | WCAG 2.1 AA for the public site; automated axe‑core checks in CI plus manual review. |
| **16. Feature flag / rollout** | No feature flag needed; the new FastAPI service will be built as a brand‑new project and cut over in one step. |

### Configurable constants (environment variables with sensible defaults)

| Variable | Default | Description |
|---|---|---|
| `RATE_LIMIT_BOOKING_CREATE` | `10/minute` | Max booking‑creation requests per IP per minute. |
| `RATE_LIMIT_CALENDAR_READ` | `60/minute` | Max calendar‑availability read requests per IP per minute. |
| `BOOKING_CANCELLATION_CUTOFF_MINUTES` | `5` | Minutes before a booking’s start time after which amendments/cancellations are disallowed. |
| `EMAIL_RETRY_BASE_DELAY_SECONDS` | `60` | Initial back‑off delay (seconds) for email delivery retries. |
| `EMAIL_RETRY_MAX_ATTEMPTS` | `5` | Maximum number of email delivery attempts. |
| `EMAIL_RETRY_MAX_DELAY_SECONDS` | `960` | Cap on exponential back‑off (seconds); 960 s = 16 min. |
| `OBSERVABILITY_ALERT_5XX_RATE` | `0.01` | Alert threshold for 5xx response rate (1 %). |
| `OBSERVABILITY_ALERT_EMAIL_BACKLOG` | `100` | Alert when email outbox pending entries exceed this count. |
| `OBSERVABILITY_ALERT_DB_POOL_EXHAUSTION` | `true` | Enable alert on database connection pool exhaustion. |

All values are read at application startup via a typed `Settings` class (Pydantic `BaseSettings`) and validated.

## Related Documents

- **[EVALUATION.md](EVALUATION.md)** – Full evaluation of the existing system: functionality, technology stack, test coverage, risks, defects, and recommended target architecture. Includes the complete list of open questions (see §10).
- **[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)** – Step‑by‑step, test‑first migration plan. Covers quality gates, testing strategy, database modeling, API, web and admin implementation, observability, and cutover procedures.
- **[docs/arc42/](docs/arc42/)** – **arc42 architecture documentation** (12 chapters): Introduction & Goals, Constraints, Context & Scope, Solution Strategy, Building Block View, Runtime View, Deployment View, Crosscutting Concepts, Architecture Decisions (ADR log), Quality Requirements, Risks & Technical Debt, Glossary.

## Motivation

The existing Optimism codebase relies on aging Node/Express stacks, ad‑hoc validation, duplicated workspaces, and insufficient test coverage. Migrating to a modern Python/FastAPI monolith with SQLAlchemy, Alembic, and strong typing will:

- Eliminate the split API/website deployment and associated CORS/session complexity.
- Provide compile‑time safety via Pydantic and SQLAlchemy typing.
- Enable robust testing (unit, API integration, browser end‑to‑end) and measurable coverage.
- Replace fragile application‑side relationship cleanup with declarative database constraints.
- Offer a clear path for secure authentication, CSRF protection, and proper error handling.
- Align the technology stack with current best practices and the team’s operational capabilities.

## Next Steps

All key questions have now been answered. Proceed to implement the test‑first baseline described in IMPLEMENTATION_PLAN.md §1 **against the API contract in [API_SPEC.md](API_SPEC.md)**, then follow the ordered delivery checklist. Confirm the default decisions listed in API_SPEC §11 before finalising the parity tests.

## Progress Log (recent activity)

- **Planning phase complete.** Produced [EVALUATION.md](EVALUATION.md) (current‑state evaluation), [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) (test‑first delivery plan), [docs/arc42/](docs/arc42/) (12‑chapter architecture documentation with ADR log), and this summary. All product‑owner questions answered (decisions #1–#16 above).
- **Issue #71 implemented** (separate worktree `optimism-issue-71`): website‑side calendar proxy added, browser no longer calls the API directly, API port no longer published in Docker Compose. See [todo.md](todo.md).
- **Plan review performed** → [PLAN_REVIEW.md](PLAN_REVIEW.md). Outcome: plan is coherent and ready to implement once the contract question and the flagged product decisions are settled. Key clarification agreed: the API is **not** to be replicated exactly — the replacement must be *very similar* and work straight out of the gate, i.e. a **middle ground** between the legacy API and the approved improvements.
- **Target API contract written** → [API_SPEC.md](API_SPEC.md). It is the authoritative spec for the FastAPI implementation: legacy‑compatible route names, camelCase fields and response shapes (so the ported web/admin UI works nearly unchanged), with every explicitly‑approved improvement applied (auth on writes, RFC 7807 errors, corrected status codes, transactional capacity, exact‑window booking, hashed cancellation tokens, idempotent cancellation, email outbox, fixed UTC, rate limits, availability windows/exceptions). Includes a legacy→v1 endpoint mapping and an improvements‑applied parity matrix (§10).
- **Pending:** product‑owner sign‑off on the default decisions in API_SPEC §11 (min/max minutes dropped, capacity per window, user amend endpoints, deletion policies, soft delete, no cancellation email, UTC email rendering, pagination, extra rate limits, export deferred) and on the PLAN_REVIEW §3.2 open questions.

