# 12. Glossary

| Term | Definition |
|------|------------|
| **Availability Window** | A recurring, fixed UTC time interval on a specific weekday during which a resource can be booked. Replaces the legacy `slots` + bitmask model. |
| **Availability Exception** | A one-off override of recurring windows for a specific date or date range (e.g., holiday closure, special opening). Kind: `closed` or `open`. |
| **Booking** | A confirmed reservation of a resource for a specific UTC start/end datetime, matching exactly one availability window. Consumes 1 unit of the window's `capacity`. |
| **Cancellation Token** | A cryptographically random, URL-safe string generated at booking creation. Only its bcrypt hash is stored; the raw token is sent once in the confirmation email and used to cancel/amend the booking. |
| **Capacity** | The maximum number of simultaneous bookings allowed for a given availability window. In v1, each booking consumes exactly 1 unit (no per-booking quantity). |
| **Cutover** | The moment production traffic is switched from the legacy Node.js system to the new FastAPI system. Performed as a single step with a time-bounded rollback plan. |
| **Dead Letter** | An email outbox entry that has exhausted all retry attempts (`EMAIL_RETRY_MAX_ATTEMPTS`) and is marked for manual investigation. |
| **ETL (Extract-Transform-Load)** | The process of migrating data from the legacy PostgreSQL schema (`resource_types`, `resources`, `slots`, `resources_slots`, `bookings`) into the new schema (`availability_windows`, `availability_exceptions`, etc.). |
| **Exclusion Constraint** | A PostgreSQL constraint (`EXCLUDE USING gist ... WITH &&`) that prevents overlapping `availability_window` rows for the same resource and weekday. |
| **Idempotent Cancellation** | Cancelling an already-cancelled booking via the same token returns success without error; the booking remains cancelled. |
| **Internal API** | The `/api/v1` JSON endpoints. Not exposed to the public internet; only the web UI (server-side) and admin UI call them. |
| **Modular Monolith** | A single deployable application (FastAPI) with clear internal module boundaries (`domains/`, `core/`, `db/`, `web/`), as opposed to a distributed microservice architecture. |
| **Observability** | The combination of structured JSON logging, Prometheus metrics, health/readiness endpoints, and alerting that enables operating the system in production. |
| **Outbox Pattern** | Durable email delivery: the booking transaction inserts a row into `email_outbox`; a background worker sends the email and updates the row status. |
| **Rate Limiting** | Token-bucket algorithm applied per client IP on public-facing endpoints (booking creation, calendar reads) to prevent abuse. Configurable via environment variables. |
| **RFC 7807 (Problem Details)** | Standard format for HTTP API error responses (`application/problem+json`) with fields `type`, `title`, `status`, `detail`, `instance`. |
| **Resource** | A bookable entity (room, laser cutter, hot desk) belonging to a `resource_type`, with a `capacity` and linked availability windows. |
| **Resource Type** | Optional grouping/category for resources (e.g., "room", "laser-cutter", "hot-desk"). |
| **Session (Admin)** | A signed, secure cookie (`Secure; HttpOnly; SameSite=lax`) establishing an authenticated administrator session. Backed by `admin_sessions` table with expiry. |
| **Single-Day Assumption** | All `availability_window` start/end times are `time` values within a single UTC day (00:00–24:00). Crossing-midnight windows are not supported in v1. |
| **Structured Logging** | JSON log lines with fixed fields (`timestamp`, `level`, `logger`, `event`, `request_id`, …) emitted to stdout; no PII. |
| **UTC+00:00 (GMT) Fixed** | All timestamps stored as `timestamptz` in UTC; calendar renders UTC; no DST/BST conversion. |
| **Worker (Email)** | Background asyncio task that polls `email_outbox`, sends via SMTP, implements exponential back-off, and moves failed entries to dead-letter after max attempts. |

---

## Acronyms

| Acronym | Expansion |
|---------|-----------|
| ADR | Architecture Decision Record |
| API | Application Programming Interface |
| CI | Continuous Integration |
| CSRF | Cross-Site Request Forgery |
| DB | Database |
| DST | Daylight Saving Time |
| E2E | End-to-End (testing) |
| ETL | Extract, Transform, Load |
| FK | Foreign Key |
| HA | High Availability |
| HTML | HyperText Markup Language |
| HTTP | HyperText Transfer Protocol |
| HTTPS | HTTP Secure |
| IP | Internet Protocol |
| JS | JavaScript |
| JSON | JavaScript Object Notation |
| JWT | JSON Web Token |
| ORM | Object-Relational Mapping |
| PII | Personally Identifiable Information |
| PR | Pull Request |
| SMTP | Simple Mail Transfer Protocol |
| SQL | Structured Query Language |
| TLS | Transport Layer Security |
| UTC | Coordinated Universal Time |
| UV | Uvicorn (ASGI server) |
| WCAG | Web Content Accessibility Guidelines |

---

> **Traceability**: Terms used throughout [EVALUATION.md](../../EVALUATION.md), [IMPLEMENTATION_PLAN.md](../../IMPLEMENTATION_PLAN.md), [summary.md](../../summary.md), and all arc42 chapters.