# 10. Quality Requirements

Quality requirements are expressed as **quality attribute scenarios** (QAS) following the pattern:  
**Source → Stimulus → Artifact → Environment → Response → Measure**.

## 10.1 Security

| ID | Scenario | Measure |
|----|----------|---------|
| SEC-01 | Unauthenticated user attempts POST `/api/v1/bookings` | 401 Unauthorized; no booking created |
| SEC-02 | Authenticated admin session attempts to access another admin's data (N/A – single shared) | N/A |
| SEC-03 | Malicious user submits 100 booking requests/sec from one IP | Rate limit → 429 after `RATE_LIMIT_BOOKING_CREATE` (default 10/min) |
| SEC-04 | Attacker steals session cookie | Cookie `Secure; HttpOnly; SameSite=lax`; short expiry (1h); rotation on login |
| SEC-05 | CSRF attack on booking creation | Double-submit cookie validated; 403 on mismatch |
| SEC-06 | SQL injection via resource ID parameter | Pydantic validation + SQLAlchemy parameterized queries; 422 on invalid type |
| SEC-07 | Cancellation token brute-force | Token = 32-byte URL-safe random; bcrypt hash stored; rate limit on cancel endpoint |
| SEC-08 | Log injection / PII leakage | Structured JSON logger; explicit allow-list of fields; correlation IDs only |

## 10.2 Reliability / Availability

| ID | Scenario | Measure |
|----|----------|---------|
| REL-01 | Concurrent booking requests for same window (10 parallel) | Advisory lock ensures capacity never exceeded; max 1 succeeds per slot |
| REL-02 | SMTP server down for 30 min | Email outbox queues; worker retries with exponential back-off; no booking failure |
| REL-03 | Database primary fails (if managed HA) | Not in scope v1 (single DB); documented runbook for manual failover |
| REL-04 | Migration fails halfway | Alembic transactions (where possible); reversible migrations; rollback via `downgrade -1` |
| REL-05 | Email worker crashes | Supervised by process manager (gunicorn/ systemd / k8s restart); `FOR UPDATE SKIP LOCKED` prevents duplicate sends |
| REL-06 | Graceful degradation: calendar read fails | 503 with RFC 7807; UI shows friendly error; booking creation unaffected |

## 10.3 Performance

| ID | Scenario | Measure |
|----|----------|---------|
| PERF-01 | Calendar availability read (1 week, 1 resource) | p95 < 200 ms; p99 < 500 ms |
| PERF-02 | Booking creation (including capacity check + email enqueue) | p95 < 500 ms |
| PERF-03 | Admin resource list (50 resources + windows) | p95 < 300 ms |
| PERF-04 | Static asset delivery (CSS, JS) | Cache-Control `max-age=31536000, immutable`; hashed filenames |
| PERF-05 | Database connection pool | `pool_size=10`, `max_overflow=5`; alert at >90% utilization |

## 10.4 Maintainability

| ID | Scenario | Measure |
|----|----------|---------|
| MAINT-01 | New developer onboards | `make dev` → running stack in <5 min; docs in `docs/arc42/` |
| MAINT-02 | Add new domain entity (e.g., `equipment`) | Follow `domains/` template; <1 hour for CRUD + tests |
| MAINT-03 | Change validation rule (e.g., max booking length) | Single location in service + schema; tests updated |
| MAINT-04 | Upgrade dependency (FastAPI, SQLAlchemy) | Pinned versions; dependabot PRs; CI runs full suite |
| MAINT-05 | Debug production issue | Correlation ID in logs + metrics; JSON logs queryable in Loki |

## 10.5 Testability

| ID | Scenario | Measure |
|----|----------|---------|
| TEST-01 | Unit test domain rule (overlap detection) | Pure functions; no DB; <1 ms each |
| TEST-02 | Integration test booking concurrency | Testcontainers PostgreSQL; 20 parallel threads; assert no overbooking |
| TEST-03 | API contract test (OpenAPI) | `schemathesis` or custom HTTPX tests against running app |
| TEST-04 | E2E test public booking flow | Playwright + real DB; headless CI; <2 min |
| TEST-05 | Coverage enforcement | `pytest --cov=app --cov-branch --cov-fail-under=80` (90% for critical) |

## 10.6 Usability / Accessibility

| ID | Scenario | Measure |
|----|----------|---------|
| USE-01 | Screen reader user books a resource | axe-core 0 violations; manual NVDA/VoiceOver test |
| USE-02 | Keyboard-only user completes booking | Tab order logical; focus visible; no keyboard traps |
| USE-03 | Mobile viewport (375px) | Responsive CSS; no horizontal scroll; tap targets ≥44px |
| USE-04 | Colour-blind user sees status | Status conveyed by text + icon, not colour alone |
| USE-05 | Error message clarity | RFC 7807 `detail` + UI shows plain-language message |

## 10.7 Operability

| ID | Scenario | Measure |
|----|----------|---------|
| OPS-01 | Deploy new version | `docker compose pull && docker compose up -d` (or `kubectl rollout`); zero-downtime |
| OPS-02 | Rollback | `docker compose up -d --force-recreate` previous tag (or `kubectl rollout undo`) < 2 min |
| OPS-03 | Run migration | CI job `alembic upgrade head` before traffic; dry-run in staging |
| OPS-04 | Rotate secrets | Update secret in manager; restart pods; no code change |
| OPS-05 | Capacity planning | Metrics `db_pool_usage`, `http_request_duration_seconds` feed Grafana dashboards |

## 10.8 Quality Requirement Priorities

| Priority | Attributes |
|----------|------------|
| **Must** | Security (SEC-01..08), Reliability (REL-01..02), Observability (OPS-01..05) |
| **Should** | Performance (PERF-01..03), Maintainability (MAINT-01..03), Usability (USE-01..03) |
| **Nice** | Performance (PERF-04..05), Maintainability (MAINT-04..05), Usability (USE-04..05) |

---

> **Traceability**: [Evaluation §7, §9](../../EVALUATION.md), [Implementation Plan §1, §8, §9](../../IMPLEMENTATION_PLAN.md).