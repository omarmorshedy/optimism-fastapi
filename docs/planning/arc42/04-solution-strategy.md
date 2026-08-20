# 4. Solution Strategy

## 4.1 Architectural Style

**Modular Monolith** – a single FastAPI application serving:
- Versioned JSON API (`/api/v1`)
- Server-rendered HTML (Jinja2) for public + admin UI
- Background worker (email outbox) via `asyncio` task or separate process

Rationale:
- Current split API/Website adds CORS, duplicate auth, deployment complexity
- Domain is small; a well-moduled monolith avoids distributed-system overhead
- Clear module boundaries allow future extraction if needed

## 4.2 Core Design Principles

| Principle | Application |
|-----------|-------------|
| **Type safety everywhere** | Pydantic for I/O, SQLAlchemy typed models, mypy strict |
| **Explicit over implicit** | Declarative DB constraints, typed settings, no magic globals |
| **Test-first** | Legacy tests ported as contracts; new behaviour TDD |
| **Security by default** | AuthN/AuthZ on all write endpoints, CSRF, rate limits, secret management |
| **Observability built-in** | Structured JSON logs, correlation IDs, Prometheus metrics, health endpoints |
| **Single deployment artifact** | One Docker image; migrations run before traffic |

## 4.3 Technology Stack Summary

| Layer | Choice | Justification |
|-------|--------|---------------|
| Web framework | FastAPI | Type-safe, automatic OpenAPI, DI, async-ready |
| Validation | Pydantic v2 | Schema + runtime validation, serialization |
| ORM | SQLAlchemy 2.x (sync) | Mature, typed, Alembic integration |
| Migrations | Alembic | Versioned, reversible, reviewable |
| Templating | Jinja2 | Built-in, familiar, minimal logic in templates |
| Calendar JS | FullCalendar (bundled) | Only dynamic component; accessible |
| Auth | Shared credential + secure session cookie | Simplicity; salted hash in secrets |
| Email | `aiosmtplib` + outbox table | Durable, retryable, decoupled from request |
| Logging | `structlog` + stdlib `logging` | JSON, correlation IDs, no PII |
| Metrics | `prometheus-client` | `/metrics` endpoint, standard |
| Testing | pytest, HTTPX, Playwright, testcontainers | Unit, API, E2E against real PostgreSQL |
| CI | GitHub Actions (pinned SHAs) | Reproducible, secure supply chain |
| Container | Multi-stage Docker, non-root | Small runtime image, security |

## 4.4 Key Architectural Patterns

| Pattern | Where Applied |
|---------|---------------|
| **Repository / Service layer** | `domains/{resources,windows,bookings}/` – DB access isolated |
| **Unit of Work** | SQLAlchemy session per request; transaction boundaries explicit |
| **Outbox pattern** | `email_outbox` table + background worker |
| **Advisory lock / row lock** | Booking creation to prevent overbooking |
| **Typed Settings** | Pydantic `BaseSettings` for all env-configurable constants |
| **Problem Details (RFC 7807)** | All API error responses |
| **Health/Readiness separation** | `/healthz` (liveness), `/readyz` (DB, migrations, email worker) |

## 4.5 Migration Strategy (Legacy → New)

1. **Branch** new FastAPI project; keep Node deployable
2. **Port tests first** (legacy contracts → desired behaviour)
3. **Implement domain + API + Web** behind feature parity
4. **ETL migration** from legacy PostgreSQL → new schema (Alembic baseline + data script)
5. **Parallel run** in staging with production-like data
6. **Cut-over**: stop legacy writes → final backup → migrate → deploy new → smoke test → monitor
7. **Rollback**: keep legacy image + DB snapshot for time-bounded rollback

---

> **Traceability**: [Evaluation §8](../../EVALUATION.md), [Implementation Plan §0–§9](../../IMPLEMENTATION_PLAN.md).