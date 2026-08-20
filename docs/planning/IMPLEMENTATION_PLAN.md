# Optimism FastAPI Replacement: Implementation Plan

**Do not begin implementation until the decisions in [Evaluation §10](EVALUATION.md#10-questions-requiring-product-owner-answers) are answered and this plan is approved.** The current system's behaviour is incomplete and unsafe in places, so it is not a sufficient specification. The full architecture is documented in [docs/arc42/](docs/arc42/). **The authoritative API contract for this delivery is [API_SPEC.md](API_SPEC.md)** — the middle ground between the legacy API (preserved routes, fields, and response shapes) and the approved improvements (auth, RFC 7807, corrected status codes, transactional capacity, exact-window booking, hashed tokens, idempotent cancellation, email outbox, fixed UTC, rate limits, availability windows/exceptions); every improvement listed there is in scope.

## Guiding decisions

- Build a **single FastAPI modular monolith** serving versioned JSON APIs and server-rendered web pages. Rationale: the current frontend is primarily forms plus one dynamic calendar; a SPA adds no demonstrated value. See [Evaluation §5.2](EVALUATION.md#52-public-frontend) and [§8.1](EVALUATION.md#81-shape).
- Use FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, psycopg, and PostgreSQL in all durable environments. See [Evaluation §8.2](EVALUATION.md#82-technology-choices).
- Use Jinja2, accessible HTML, and minimal locally bundled JavaScript for calendar interaction. Browser behaviour necessarily requires JavaScript; “Python frontend” should mean Python-rendered HTML, not an attempt to eliminate browser JS.
- Treat security, booking correctness, test coverage, and data migration as release gates—not cleanup work after UI implementation. See [Evaluation §7](EVALUATION.md#7-risks-defects-and-uncertain-behaviour) and [§9](EVALUATION.md#9-acceptance-baseline-for-replacement).
- Implement the API exactly as specified in **[API_SPEC.md](API_SPEC.md)**: legacy-compatible camelCase fields and route shapes (so the ported web/admin UI works nearly unchanged), with every approved improvement applied. The legacy→v1 mapping (§2.3) and the improvements-applied parity matrix (§10) are the reference for translating legacy tests.

## Definition of done for every implementation item

- Functions and methods have complete input and output type annotations; HTTP schemas are explicit Pydantic request/response models; persistence models are typed SQLAlchemy 2.x mappings.
- Code is formatted, linted, and type checked; routers contain HTTP concerns only; domain services contain business rules; database access is isolated and tested.
- Structured logs include correlation/request ID, action, safe identifiers, and outcome. Never log passwords, cancellation tokens, email bodies, or unnecessary PII.
- Tests cover success, validation, authorisation, failure, and regression cases. Update OpenAPI and user/admin documentation with behaviour changes.
- No secret is committed, hard-coded, emitted in logs, or passed through Docker build arguments.

## Ordered delivery checklist

### 0. Discovery and requirements sign-off — blocker

- [ ] Hold structured stakeholder sessions and answer every question in [Evaluation §10](EVALUATION.md#10-questions-requiring-product-owner-answers).
- [ ] Write a versioned business-rules specification: capacity semantics; slot/window model; duration/granularity; time zone/DST; closures; cancellation/amendment; notification; retention; roles; API compatibility. Default answers for the open points are proposed in [API_SPEC.md §11](API_SPEC.md#11-default-decisions-taken-in-this-spec-confirm-with-product-owner) and [PLAN_REVIEW.md §3.2](PLAN_REVIEW.md#32-open-productdesign-decisions-flag-for-sign-off-defaults-taken-in-the-spec) — obtain product-owner sign-off on them here.
- [ ] Inventory production database schema, row counts, bad/null values, token/email uniqueness, and all consumers of existing URLs/API/email links. Take and restore-test a production backup copy in an isolated environment.
- [ ] Convert findings into acceptance scenarios, including known omissions in [Evaluation §7](EVALUATION.md#7-risks-defects-and-uncertain-behaviour).

**Why first:** current slot/admin functionality is unfinished and key booking meanings are ambiguous. Coding before this would preserve accidental behaviour or silently change policy.

### 1. Testing-first baseline and quality gates — blocker

The approved equivalents of every legacy test in [Evaluation §3.1](EVALUATION.md#31-existing-test-suite-analysis) are the **first implementation deliverable**, before domain/API/UI production code. Write them as desired behaviour—not a bug-compatible translation—and mark each legacy test as preserve, deliberately change, or obsolete in a traceability matrix. Use the **improvements-applied parity matrix in [API_SPEC.md §10](API_SPEC.md#10-improvements-applied-vs-legacy-parity-matrix)** (and the legacy→v1 endpoint mapping in [§2.3](API_SPEC.md#23-legacy--v1-endpoint-mapping)) as the basis for that matrix.

- [ ] Create `tests/` with `unit/`, `integration/`, `api/`, `e2e/`, `contract/`, factories, and shared typed fixtures. Use pytest, pytest-cov, HTTPX/Starlette test client, freezegun/time-machine (or injected clock), and testcontainers or Docker Compose PostgreSQL.
- [ ] Add the four legacy CRUD test matrices first: resources, slots, resource types, and bookings. Assert response body schema/fields as well as status. Preserve valid/malformed/missing/nonexistent/mismatched identifier coverage. Decide and document corrected missing-delete behaviour (normally 404, not legacy 204). Request/response schemas and status codes are defined in [API_SPEC.md §2–§4](API_SPEC.md#2-domain-model-api-view); note the legacy `slots` endpoints are replaced by availability windows (mapping in [§2.3](API_SPEC.md#23-legacy--v1-endpoint-mapping)).
- [ ] Add legacy calendar input tests first: valid request, malformed start/end, reversed range, invalid and missing resource. Then write expected-value tests for weekday bitmask conversion/replacement, assigned slots, capacity, cancelled bookings, overlap at query boundaries, and business time zone/DST — asserting the response shape defined in [API_SPEC.md §3.3/§6](API_SPEC.md#33-get-apiv1calendarstartdateenddateresourceid--get-apicalendar).
- [ ] Add approved resource and slot deletion-policy tests first: relationship effects and transaction rollback. Do not assume the current “null booking resource/delete links” policy without phase-0 sign-off.
- [ ] Add the currently absent core booking tests *before* booking implementation: valid creation, all rejected inputs, resource existence, slot/duration policy, capacity, cancellation-token uniqueness, cancellation confirmation/idempotency, email-outbox persistence/failure/retry, and concurrent requests that cannot exceed capacity.
- [ ] Add API authorisation tests before protected endpoints: anonymous access, role boundaries, session security, CSRF, rate limiting, token privacy, list filtering/pagination, and PII redaction.
- [ ] Add Playwright smoke/UI tests before templates: home; resource choice; calendar data/error/keyboard selection; invalid and successful details/confirmation; cancellation confirmation; login/logout; and all approved admin CRUD flows. Run against full disposable PostgreSQL-backed containers, never mocks alone.
- [ ] Add Alembic upgrade/downgrade and legacy-data-import tests, backup/restore rehearsal checks, container `/healthz`/`/readyz` smoke checks, and a migration-before-traffic deployment test.

#### Coverage policy

- [ ] Measure branch coverage with `pytest --cov=app --cov-branch --cov-report=term-missing --cov-report=xml`.
- [ ] Begin with an enforceable **80% branch coverage** minimum for domain/services and application package; raise to **90%** after the first stable release. Maintain 100% coverage for critical availability, capacity, authorisation, cancellation, and migration branches. Coverage is a backstop, not evidence of correctness; mutation/property-based tests are appropriate for interval and date rules.
- [ ] Publish XML coverage to the CI provider/coverage service; fail pull requests below the threshold or when changed critical code lacks tests. Do not set a superficial global threshold that allows new untested security/booking code to hide behind legacy code.

#### Local pre-commit policy

- [ ] Configure `pre-commit` with: trailing-whitespace, end-of-file-fixer, check-yaml/json/toml, check-merge-conflict, detect-private-key, check-added-large-files, and `gitleaks` (or equivalent secret scanner).
- [ ] Run Ruff format/check, import/order policy, and mypy/pyright on Python; run template/static checks where applicable. Add dependency manifest/lock consistency checks.
- [ ] Keep hooks fast: unit tests may run locally where practical; run full PostgreSQL, browser, image, and load suites in CI or an explicit `make verify` command. Hooks are not a substitute for CI.

#### Required GitHub Actions pipeline

- [ ] **Pull request:** checkout with pinned action SHAs; set up locked Python; verify dependency lock; run pre-commit, Ruff format/check, type check, unit tests with coverage threshold, and upload coverage artifact.
- [ ] **Pull request:** start ephemeral PostgreSQL; run Alembic migration/import tests, repository/API integration tests, and security/secret/dependency scans (for example Gitleaks, pip-audit, and an OS image scanner).
- [ ] **Pull request:** build the production Docker image with BuildKit cache; inspect it for vulnerabilities; start the image/Compose stack; wait for readiness; run health/API smoke and Playwright E2E tests; collect logs/screenshots/traces as artifacts on failure.
- [ ] **Main/develop:** repeat the required suite, publish a versioned immutable image only after success, and retain SBOM/provenance if the deployment platform supports it.
- [ ] **Production deployment:** require successful test/build workflow, approved environment, backup verification, migration job completion before traffic, post-deploy health/E2E smoke check, and automatic/operable rollback. Do not use the current test-bypassing SSH workflow described in [Evaluation §3.1](EVALUATION.md#31-existing-test-suite-analysis).
- [ ] Protect the integration branch: require these status checks, review, and up-to-date branch; never permit deployment credentials in build logs or unreviewed workflows.

**Why first:** the existing 78 API tests define only a small regression floor, while booking correctness and the UI are untested. A test-first executable specification prevents the replacement from reproducing known defects or silently dropping behaviour.

### 2. Establish delivery foundation

- [ ] Create a separate replacement branch/directory; leave the Node system deployable until cutover.
- [ ] Initialise Python project with pinned/locked dependencies (`pyproject.toml` plus chosen lock tool), Python version policy, `.env.example`, and secret-management instructions.
- [ ] Add FastAPI application factory, typed `Settings`, configuration validation, `/healthz` and `/readyz`, JSON structured logging, correlation IDs, and safe global error handling.
- [ ] Add Ruff, formatter, type checker (mypy or pyright in strict practical mode), pytest, coverage, pre-commit, and CI checks.
- [ ] Add Docker multi-stage image, non-root runtime user, ephemeral PostgreSQL service for CI, and deployment configuration that runs migrations before routing traffic.

**Why:** this corrects reproducibility and operational drift identified in [Evaluation §§2, 6](EVALUATION.md#2-repository-and-runtime-inventory).

### 3. Model the database and migration strategy

- [ ] Define typed SQLAlchemy models and Alembic baseline from the approved target model in [Evaluation §4.2](EVALUATION.md#42-recommended-target-relational-model): resource types, resources, resource-specific `availability_windows`, bookings, cancellation-token hash, shared-admin sessions, email outbox, and audit events. Do **not** copy the old reusable `slots`/`resources_slots` bitmask model without a documented reason.
- [ ] Add PostgreSQL constraints: non-empty/unique names where approved; positive capacity (booking count); `ends_at > starts_at`; weekday 0–6; exclude overlapping windows for same resource and weekday (using an exclusion constraint or service validation); unique resource/week-day/time availability windows; non-null booking resource; approved foreign-key deletion policy; useful indexes; and unique cancellation-token hashes.
- [ ] Implement the confirmed fixed UTC (`UTC+00:00`) policy: store booking timestamps as `timestamptz`, availability weekday/time in UTC, and render calendar timestamps explicitly in UTC. Do not use `Europe/London` or silently observe BST. Add tests for a summer date.
- [ ] Capacity is booking count (no per‑booking quantity); enforce that the number of active, non‑cancelled bookings for a given window does not exceed its capacity using a transactionally safe lock or advisory lock.
- [ ] Include one‑off exceptions such as holidays and special events via an `availability_exceptions` table (or equivalent) that can override recurring windows.
- [ ] **Cancellation window:** store a configurable cutoff (e.g., minutes before start) in settings via `BOOKING_CANCELLATION_CUTOFF_MINUTES` (default: `5`); enforce that amendments and cancellations are only allowed when the current time is before `starts_at - cutoff`.
- [ ] Design a reversible/import-tested ETL migration from the current PostgreSQL database; reconcile orphaned bookings and null/invalid legacy data explicitly.
- [ ] Write migration dry-run, validation counts/checksums, rollback, and restore runbooks. (Note: backup/restore process is not required for the initial release per product decision.)

**Why:** the present schema lacks invariants and uses application-side relationship cleanup; current production data is the migration source. See [Evaluation §4](EVALUATION.md#4-domain-model-and-data-behaviour).

### 4. Implement domain services before routes

- [ ] Implement typed repositories/query services for resources, resource types, slots, and bookings.
- [ ] Implement an availability service with a tested interval-overlap query (`existing.start < requested.end AND existing.end > requested.start`) and explicit cancelled-status handling.
- [ ] Implement the signed-off duration, slot membership, weekday, capacity/quantity, past-time, closure, and time-zone rules.
- [ ] Prevent concurrent overbooking using a documented PostgreSQL transaction strategy (for example, advisory/resource lock or an allocation model with row locking); load-test it.
- [ ] Implement safe, idempotent cancellation and permitted amendment flow. A GET may display a confirmation page; a CSRF-protected POST performs the state change.
- [ ] Persist notification work in an outbox within the booking transaction; add retry/monitoring worker and provider abstraction.
- [ ] **Email retry policy:** use exponential back‑off configured via environment variables:
    - `EMAIL_RETRY_BASE_DELAY_SECONDS` (default: `60`)
    - `EMAIL_RETRY_MAX_ATTEMPTS` (default: `5`)
    - `EMAIL_RETRY_MAX_DELAY_SECONDS` (default: `960` i.e., 16 min)
  After the final failure, move the outbox entry to a dead‑letter state and emit an alert/log entry for manual follow‑up.

**Why:** booking integrity defects are the greatest functional risk. See [Evaluation §§4.2, 7](EVALUATION.md#42-availability-and-booking-rules-currently-implemented).

### 5. Build secure versioned API

- [ ] Publish `/api/v1` endpoints with Pydantic schemas, consistent RFC 7807-style error responses, status codes, pagination/filtering, and generated OpenAPI — **exactly as specified in [API_SPEC.md](API_SPEC.md) §1–§4** (conventions/errors/auth/rate limits in §1, entities in §2, public endpoints in §3, admin endpoints in §4).
- [ ] The API is **internal‑only**; it must not be exposed to the public internet or external clients. All external traffic goes through the web application.
- [ ] **Rate limiting:** apply a defensive rate limit on public‑facing endpoints using configurable environment variables:
    - `RATE_LIMIT_BOOKING_CREATE` (default: `10/minute` per IP)
    - `RATE_LIMIT_CALENDAR_READ` (default: `60/minute` per IP)
  Implement with a lightweight middleware (e.g., `fastapi-limiter` or custom dependency).
- [ ] Implement read/availability/create/cancellation endpoints as required by the product; never expose booking lists, notes, emails, or tokens publicly.
- [ ] Implement protected admin endpoints for all resource types, resources, slots, resource-slot assignment, and bookings required by the signed-off specification.
- [ ] Add authentication/authorisation to both API and web routes, password hashing or approved identity provider, secure server-side sessions/cookies, CSRF protection, rate limits, audit logging, and secret rotation.
- [ ] **Email preservation:** the booking confirmation email subject and body must match the current production email (as evaluated in [Evaluation.md](#)). Treat the email content as immutable unless a future product decision changes it.
- [ ] Add API contract tests against the contract in [API_SPEC.md](API_SPEC.md); the legacy→v1 mapping in [§2.3](API_SPEC.md#23-legacy--v1-endpoint-mapping) is the reference for translating legacy tests, and the parity matrix in [§10](API_SPEC.md#10-improvements-applied-vs-legacy-parity-matrix) records which legacy behaviours were deliberately changed. No adapter/deprecation layer is required for legacy endpoints/URLs (decision #9; the middle-ground spec already preserves the routes and fields the ported UI depends on).

**Why:** the current API permits anonymous writes and exposes personal data. See [Evaluation §5.1](EVALUATION.md#51-api-contract) and [§7](EVALUATION.md#7-risks-defects-and-uncertain-behaviour).

### 6. Rebuild public web experience

- [ ] Implement home, resource choice, time choice, details, confirmation, cancellation confirmation/result, and safe error pages as Jinja templates.
- [ ] Use semantic HTML, keyboard-accessible controls, server-side validation/error redisplay, responsive design, and accessibility tests (target WCAG 2.1 AA; automated axe‑core checks in CI, plus manual review).
- [ ] Add minimal JavaScript to fetch/render calendar availability and select a slot. Pin and locally bundle a maintained calendar dependency; provide an accessible non-JavaScript fallback if feasible.
- [ ] Keep selected booking intent server-side or use tamper-resistant, short-lived signed state; revalidate availability server-side when creating the booking.
- [ ] Preserve/rewrite legacy public URLs and cancellation links according to the approved compatibility decision. The calendar JSON shape is preserved per [API_SPEC.md §3.3](API_SPEC.md#33-get-apiv1calendarstartdateenddateresourceid--get-apicalendar), and cancellation is a POST-performed, idempotent state change with the confirmation page rendered by GET per [API_SPEC.md §7](API_SPEC.md#7-cancellation-and-amendment-rules).

**Why:** this retains the simple proven UX while removing the separate Express website/API hop and hidden-field trust. See [Evaluation §5.2](EVALUATION.md#52-public-frontend).

### 7. Build complete admin experience

- [ ] Implement admin dashboard and authenticated CRUD for resource types, resources, slots (including day/start/end), and resource-slot assignment.
- [ ] Implement booking list/detail/search/filter and only approved administrative actions (cancel, amend, export), with authorisation and audit logs.
- [ ] Avoid the current resource-list N+1 pattern by serving view models/query joins deliberately.
- [ ] Add clear deletion impact previews and enforce chosen deletion policy rather than silently nulling/deleting links.

**Why:** slot creation is currently wired to the wrong API, slot edit/delete is absent, and booking admin is a placeholder. See [Evaluation §5.3](EVALUATION.md#53-admin-frontend).

### 8. Extend, secure, and observe_con_observe

- [ ] Unit-test availability, bitmask/recurrence conversion (or its replacement), validation, time zones/DST, capacity, cancellation, and email-outbox rules.
- [ ] Run API/database integration tests against PostgreSQL; include migrations from a representative legacy database.
- [ ] Add Playwright browser journeys for public booking/cancellation and each admin role/CRUD flow; include accessibility checks (WCAG 2.1 AA via axe‑core).
- [ ] Add concurrency tests proving capacity cannot be exceeded; test email provider failures/retries without losing bookings.
- [ ] Add dependency/security scanning, secret scanning, CSRF/auth/rate-limit tests, log-redaction tests, and performance smoke tests.
- [ ] **Observability:** emit structured JSON logs to stdout (fields: `timestamp`, `level`, `request_id`, `path`, `method`, `status`, `duration_ms`). Expose a Prometheus `/metrics` endpoint for scrape‑based monitoring. Configure alerts for: 5xx rate > 1%, booking creation failures, email outbox backlog > 100, DB connection pool exhaustion.
- [ ] Configure dashboards/alerts for request failures, booking conflicts, outbox failures, authentication events, database health, and migration results.

**Why:** current evidence is 78 API integration tests and a single Cypress home-page spec, insufficient for release. See [Evaluation §3](EVALUATION.md#3-verified-execution).

### 9. Parallel run, cutover, and retirement

- [ ] Deploy a non-production environment from production-like PostgreSQL data and run stakeholder acceptance scenarios from phase 0.
- [ ] Run legacy and replacement in parallel/read-only as appropriate; compare availability and booking outcomes using a documented reconciliation process.
- [ ] Rehearse database migration, backup/restore, rollback, health checks, email configuration, and DNS/proxy/URL transition.
- [ ] Schedule cutover: stop legacy writes, final backup, migrate/validate, deploy/migrate before traffic, smoke-test, monitor, and communicate.
- [ ] Keep a time-bounded rollback plan and immutable legacy backup; after agreed retention, revoke legacy secrets and retire Node containers/dependencies.

**Why:** current deployment restarts before migrations and has no tested rollback or health gates. See [Evaluation §6](EVALUATION.md#6-current-architecture-and-operations).

## Release gates

Do not cut over until all apply:

1. Requirements and legacy-compatibility choices are signed off.
2. Representative production-data migration validates and restore is proven.
3. All [Evaluation §9](EVALUATION.md#9-acceptance-baseline-for-replacement) scenarios pass, including concurrency.
4. Security review approves authentication, authorisation, CSRF, secret handling, token handling, PII retention, and logs.
5. CI is green for formatting, lint, types, unit/API/browser/integration tests, and security scans.
6. Operations has dashboards, alerts, backups, migration/cutover/rollback runbooks, and an owner on launch day.
