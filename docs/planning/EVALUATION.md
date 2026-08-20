# Optimism: Current-State Evaluation

> **Scope and date.** Static review and disposable-container verification on 2026-08-06. No application code, configuration, data, or existing untracked files were changed. This is an evidence-based inventory, not a claim that every production path has been exercised.

## 1. Executive summary

Optimism is DoES Liverpool's resource-booking system. It has two Node/Express applications: a JSON API and a server-rendered Nunjucks website. PostgreSQL is used in Docker production; SQLite is used in development and tests. The core product is small enough that a Python/FastAPI **modular monolith** is preferable to a replacement set of microservices.

The replacement should use FastAPI, Pydantic request/response models, SQLAlchemy 2.x, Alembic, PostgreSQL, structured logging, and a single deployable web application. Retain a small amount of browser JavaScript for the calendar; Python cannot replace code that runs in the browser. FastAPI/Jinja templates plus a current, locally bundled FullCalendar (or a progressively-enhanced calendar) is the lowest-complexity frontend choice. See [§8](#8-recommended-target-architecture), [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md), and [docs/arc42/](docs/arc42/).

The existing product has important functional and security gaps: unfinished slot and booking administration, unauthenticated write APIs, plaintext single-user admin authentication, no CSRF protection, inadequate booking-time validation, and a capacity race. The migration must first establish the intended business rules with stakeholders rather than treating all current behaviour as a specification. See [§7](#7-risks-defects-and-uncertain-behaviour).

## 2. Repository and runtime inventory

| Area | Current implementation | Assessment |
|---|---|---|
| API | Express 4, CommonJS, Knex 1, Moment, Nodemailer | Separate API at `/api`; versions and conventions are dated. |
| Website | Express, Nunjucks, Axios, express-session, Bootstrap 4.5, FullCalendar 5 | Server-side rendered public and admin UI; JavaScript is limited mainly to the calendar. |
| Data | PostgreSQL 17 in Compose; SQLite (`better-sqlite3`) locally/test | Same schema is used across engines, creating semantic and deployment differences. |
| Schema migration | Knex migrations | Two migrations: original schema and booking cancellation token/status. |
| Styling/assets | Vendored Bootstrap SCSS and generated CSS; remote jQuery, Axios, Bootstrap Icons | Sass compilation emits many deprecation warnings; third-party resources are partly remote. |
| Testing | Mocha/Supertest integration tests; one Cypress smoke spec | No unit tests, browser journey coverage, email tests, or deployment health checks. |
| Deployment | Docker Compose and GitHub Actions SSH deployment | Production DB password is literal in Compose; migrations run *after* containers start. |

The root `package.json` declares workspaces but has no root lockfile, while `api/package-lock.json` exists. The README still says Node 14-or-earlier is required because of `node-sass`, although the Dockerfiles use Node 20 and Dart Sass. This is an example of documentation and tooling drift.

## 3. Verified execution

| Check | Result | Notes |
|---|---|---|
| Official-style API test image build | Passed | `docker build --build-arg=NODE_ENVIRONMENT=testing --build-arg=TEST_FOLDER=test -t optimism-api-evaluation ./api` built with Node 20. |
| API integration suite | **Passed: 78 tests** | The suite exercises baseline CRUD, calendar parameter validation, and transactional resource/slot deletion. Expected error-path logs are printed. |
| Website Docker build/CSS compilation | Passed with warnings | Image builds, but Sass reports numerous deprecations from Bootstrap 4-era source. |
| Disposable website runtime home page | Passed | `/` rendered “Booking resources at DoES Liverpool”; `/admin` redirected to login. |
| Full public browser journey / production Compose stack | Not completed | Compose requires real secret files; the temporary multi-container test did not reliably complete resource selection after the home-page check. It must be repeated against an ephemeral PostgreSQL environment as a formal acceptance suite. |
| Cypress | Not run | Only a home-page smoke spec exists; the root dependencies were not installed because no root lockfile supports `npm ci`. |

The passing API suite is useful regression evidence, but it does **not** validate the actual booking workflow, email delivery, cancellation, authentication, concurrent booking, PostgreSQL behaviour, or the admin UI.

### 3.1 Existing test-suite analysis

#### API tests: Mocha + Chai + Supertest

`npm run test-api` invokes Mocha recursively over `api/`, sets `NODE_ENV=testing`, suppresses logs, and uses a 3.5-second test timeout. Each integration-test `beforeEach` migrates the in-memory SQLite database, rolls it back, migrates it again, and loads the testing seeds. Tests import the Express app directly through Supertest; they do not make a network request to a separately running server. The app nevertheless starts a listener on import, which is a test-design flaw.

| Source | What it asserts | Gaps / replacement interpretation |
|---|---|---|
| `api/test/integration/general.js` | For resources, slots, resource types, and bookings: valid/invalid/nonexistent GET IDs; valid, missing-field, primary-key-present, and extra-field POST payload status; PUT success/mismatched/invalid/nonexistent IDs; delete existing/missing IDs. It also confirms created items can be fetched and one resource update persists. | This is status-focused CRUD coverage, not full field/response-contract validation. Port these first as parametrised FastAPI API tests, but correct intended semantics where current tests assert invalid behaviour (notably missing deletes return 204). |
| `api/test/integration/calendar.js` | Calendar returns 200 for one valid date/resource request; 400 for malformed dates, invalid resource ID, or reversed dates; 404 for missing resource. | Add exact slot/weekday/capacity/cancelled/interval-boundary/DST response assertions. |
| `api/test/integration/resources.js` | Resource deletion nulls `resourceId` on its bookings and removes resource-slot links; induced failure from renaming `bookings` preserves the resource. | This captures legacy deletion semantics and transaction atomicity. Product owner must approve whether to preserve nulling versus restrict/soft-delete/cascade. Test the selected policy. |
| `api/test/integration/slots.js` | Slot deletion removes resource-slot links; induced missing join table rolls back deletion. | Same transaction-atomicity requirement; description incorrectly calls the join table `resources_types`. |
| `api/test/helpers.js` | Builds common payload/status matrices. The booking fixture includes legacy token/cancelled fields. | Move fixtures to factories; avoid shared magic IDs and test each externally observable field. |

There are **no tests** for the new booking collision/capacity/token/email/cancellation code despite it being core behaviour, no test for resource-slot replacement, no test for resource-type deletion side effects, no database migration test, and no test run against PostgreSQL. SQLite's in-memory database is recreated per process; it cannot exercise production transaction/locking semantics.

#### Browser tests: Cypress

There is exactly one spec, `cypress/e2e/home_page.cy.js`, configured with `baseUrl: http://localhost:3000`. Its three independent checks load `/`, assert its heading with an unusually short 100 ms timeout, and click the hero link to assert the exact localhost URL. `cypress/support/commands.js` contains only generated comments; fixtures are unused. No configured script starts dependencies or invokes Cypress in CI.

This is a smoke check, not functional UI coverage. It covers none of resource selection, calendar loading/clicking, form validation, booking, cancellation, admin authentication, resource/type/slot administration, accessibility, responsive behaviour, or error paths. The replacement should use Playwright rather than carry Cypress solely for this small suite, unless the team explicitly prefers Cypress.

#### Current quality gates

ESLint and JSDoc rules exist but no lint script is defined. CI only builds a testing API Docker image and runs its Mocha suite on pushes to `develop`; deployment CI does not run tests before SSH deployment. There is no coverage measurement/threshold, formatter, type checker, pre-commit configuration, Python test tooling, frontend test pipeline, Compose integration test, image smoke test, dependency/secret scanning, or required-status policy. See [Implementation Plan: testing-first delivery](IMPLEMENTATION_PLAN.md#1-testing-first-baseline-and-quality-gates--blocker).

### 3.2 Required replacement test pyramid

1. **Unit/domain tests:** fast, deterministic tests for schemas, duration/slot rules, interval overlap, capacity, cancellation, date/time-zone/DST handling, and email-outbox state transitions.
2. **Repository/database integration tests:** PostgreSQL-backed tests for constraints, Alembic upgrades, indexes, transaction rollback, selected deletion policy, and concurrent capacity allocation.
3. **API integration/contract tests:** FastAPI `TestClient`/HTTPX tests mirroring every approved legacy contract scenario, plus authentication, authorisation, CSRF, validation, error schema, pagination, and sensitive-data redaction.
4. **Browser end-to-end tests:** Playwright journeys through public booking/cancellation and each admin workflow against a disposable full Docker/PostgreSQL stack.
5. **Non-functional tests:** migration/restore rehearsal, concurrency/load checks, accessibility, security checks, image/container health checks, and dependency/secret scanning.

The first written tests must be the approved equivalent of the legacy scenarios above, expressed as the desired contract rather than a bug-for-bug port. New behaviour is then implemented test-first. Full task ordering, tooling, and CI policy are in [Implementation Plan §1](IMPLEMENTATION_PLAN.md#1-testing-first-baseline-and-quality-gates--blocker).

## 4. Domain model and data behaviour

### 4.1 Tables

| Entity | Fields / relationships | Current behaviour |
|---|---|---|
| `resource_types` | `id`, nullable `name`; 1-to-many resources | Categorises resources, e.g. room, laser cutter, hot desk. Deletion sets associated `resource_type_id` to null in application code. |
| `resources` | type FK, `name`, `capacity`, `min_minutes`, `max_minutes`; many-to-many slots; one-to-many bookings | A bookable item. Deletion nulls booking resource IDs and deletes slot links in an application transaction. |
| `slots` | `name`, day bitmask, start/end SQL `time`; many-to-many resources | Reusable weekly opening/bookable time interval. Bit `2 ** weekday` is used, where Sunday is 0. |
| `resources_slots` | composite resource/slot key | Assigns availability slots to resources. |
| `bookings` | nullable resource FK, email, name, notes, start/end datetime, unique nullable token, `cancelled` | A booking/cancellation record; cancelled bookings remain. |

Seed examples indicate single-capacity rooms, capacity-10 hot desks, weekday availability, and 30-minute meeting slots. The schema has few meaningful database constraints: names and resource type names can be null/duplicated, capacity/time ranges are not checked, and FK delete behaviour is implicit rather than explicit.

### 4.2 Recommended target relational model

This is a proposed **target**, not an instruction to migrate before the unresolved capacity/deletion/retention decisions are approved. It replaces the reusable `slots` plus bitmask design because the confirmed rule is that a slot is a fixed, resource-specific availability window.

| Table | Essential columns and constraints | Reasoning |
|---|---|---|
| `resource_types` | `id`, unique non-blank `name`, `created_at`, `updated_at` | Optional grouping of resources. Retain only if it remains useful to administrators/public selection. |
| `resources` | `id` (UUID or bigint—choose once), optional `resource_type_id`, unique non-blank `name`, positive `capacity`, active flag, timestamps | A bookable place/item. Do not encode booking rules in nullable columns without constraints. `capacity` remains provisional pending [Question 3](#10-questions-requiring-product-owner-answers). |
| `availability_windows` | `id`, non-null `resource_id`, `weekday` (0–6), `starts_at`/`ends_at` as `time`, `active`, timestamps; `ends_at > starts_at`; unique `(resource_id, weekday, starts_at, ends_at)` | One row describes one recurring fixed UTC weekly window for one resource. It replaces `slots` and `resources_slots`; individual weekday rows are clearer and queryable than the current day bitmask. Overlap prevention/allowance must follow the approved policy. |
| `availability_exceptions` *(recommended)* | `id`, `resource_id`, date or UTC datetime range, `kind` (`closed`/`open`), optional reason, timestamps; range constraints/indexes | Represents holidays, one-off closure/opening changes without corrupting recurring windows. Include only after the product decision on closures. |
| `bookings` | `id`, non-null `resource_id`, optionally `availability_window_id`, `starts_at`/`ends_at` as `timestamptz`, `status`, contact name/email, notes, any approved quantity, timestamps, cancellation fields | The durable record of a dated booking. Application/service validation proves it exactly matches a valid fixed window. A non-null resource FK prevents the present orphaning-on-delete behaviour unless an approved archival policy says otherwise. |
| `booking_cancellation_tokens` *(or columns on `bookings`)* | booking FK, **hash** of random token, created/used/expired timestamps; unique token hash | Store only a cryptographic hash, never a raw bearer cancellation URL token. The one-time/raw token is shown in the confirmation/email only. |
| `email_outbox` | id, booking FK, message type, payload/reference, attempts, status, next-attempt/sent timestamps, safe provider ID | Makes confirmation delivery durable and retryable; booking creation is not coupled to SMTP availability. |
| `admin_sessions` *(if server-side sessions are used)* | opaque session ID/hash, expiry, created/last-used timestamps, optional IP/user-agent metadata | A single shared administrator password does not require an `admin_users` table, but sessions must be secure, revocable, and not in-process memory. Store the shared credential as a salted password hash in secret management. |
| `audit_events` *(recommended)* | id, occurred time, action, actor type (`shared_admin`/system), resource/booking IDs, safe metadata | Shared credentials cannot provide person-level attribution; this at least records administrative actions and outcomes. Do not put secrets or full personal data in metadata. |

**Time policy confirmed by the product owner:** booking timestamps and calendar display operate in fixed UTC/GMT (`UTC+00:00`) all year. Store `timestamptz` in PostgreSQL and render UTC explicitly; do not substitute `Europe/London`, which changes to BST during summer. Availability `time` and weekday are interpreted as UTC. Tests must include a summer date to prove that the UI does not shift to BST.

**Single‑day slot assumption:** a slot’s `starts_at` and `ends_at` are `time` values within the same UTC day (00:00–24:00). Crossing‑midnight windows (e.g., 22:00–02:00) are **not supported** in the first release. If such windows become a requirement later, the model can be extended to store a date or duration.

**Booking/capacity policy still open:** a booking needs a transactionally safe allocation strategy. If capacity means one whole window per booking, `capacity` is the maximum simultaneous bookings for the same resource/window. If it means people/desks, add `quantity` with `quantity > 0` and enforce the sum of overlapping active booking quantities ≤ capacity under a resource/window lock. The answer to Question 3 determines this schema and its concurrency tests.

### 4.3 Configurable constants (environment variables)

The following runtime constants are exposed as environment variables with sensible defaults. They can be overridden in deployment without code changes.

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

All values are read at application startup via a typed `Settings` class (Pydantic BaseSettings) and validated.

### 4.4 Availability and booking rules currently implemented

1. An availability calendar receives inclusive start/end dates and one resource ID.
2. It finds the resource's assigned slots and expands slots whose weekday bit is enabled.
3. For every calendar slot it counts overlapping, non-cancelled bookings and labels the slot `available` if count is below resource capacity.
4. Booking creation repeats an overlap/capacity check, creates a random cancellation token, saves the booking, and sends a confirmation email asynchronously.
5. `POST /api/bookings/cancel/:token` marks a matching booking cancelled.

The apparent intended rules—not reliably enforced rules—are booking within published slots and a duration between each resource's minimum and maximum minutes. See [§7](#7-risks-defects-and-uncertain-behaviour) before preserving these semantics.

## 5. Functional inventory

### 5.1 API contract

All routes are unauthenticated and JSON-oriented except error bodies, which are plain strings.

| Endpoint | Function |
|---|---|
| `GET/POST /api/resources`, `GET/PUT/DELETE /api/resources/:id` | List and CRUD resources. |
| `GET /api/resources/:id/slots` | List assigned slots. |
| `PUT /api/resources/:id/slots` | Replaces all slot links, but does not send a success response. |
| `GET/POST /api/resource-types`, `GET/PUT/DELETE /api/resource-types/:id` | List and CRUD resource types. |
| `GET/POST /api/slots`, `GET/PUT/DELETE /api/slots/:id` | List and CRUD slots. |
| `GET/POST /api/bookings`, `GET/PUT/DELETE /api/bookings/:id` | List and CRUD bookings. POST adds collision check, token, and email. |
| `POST /api/bookings/cancel/:token` | Cancel a booking by bearer-like URL token. |
| `GET /api/calendar/:startDate/:endDate/:resourceId` | Weekly/dated availability data consumed by FullCalendar. |

### 5.2 Public frontend

The public UI is a three-step server-rendered booking flow:

1. **Home (`/`)**: marketing/jumbotron page with “Start your booking”. Some placeholder “View details” links do nothing.
2. **Choose resource (`/select-a-resource`)**: fetches resources and resource types from the API, then displays a resource card/link.
3. **Choose time (`/select-a-time?resource=:id`)**: creates a server session, renders a FullCalendar week, and has browser JavaScript fetch calendar JSON as weeks change. A user clicks one available, future event; hidden start/end fields are posted onward.
4. **Enter details (`POST /your-details`)**: checks only that resource ID matches the session and that fields exist; displays a name/email/notes form.
5. **Confirmation (`POST /confirmation`)**: posts to API, displays booking details and a cancellation modal/link.
6. **Cancellation (`GET /cancel-booking/:token`)**: immediately performs the state-changing cancellation and renders success/failure.

The frontend is mostly HTML forms; only dynamic calendar data/click handling needs JavaScript. That supports the server-rendered recommendation in [§8](#8-recommended-target-architecture).

### 5.3 Admin frontend

`/admin/*` is protected only by a session boolean. Login compares submitted plaintext values against environment/Docker-secret values.

| Screen | Status |
|---|---|
| Dashboard | Placeholder text only. |
| Resource types | List, create, edit, and confirm/delete work through API calls. |
| Resources | List, create, edit, and confirm/delete work in principle; list performs N+1 API calls for type and slots. |
| Slots | List renders, but create posts to the **resource-types** endpoint; no start/end fields; checkbox name is constant `123`; edit/delete/confirmation routes are absent or templates empty/broken. |
| Bookings | Placeholder text only; no administration. |

## 6. Current architecture and operations

The website calls the API over HTTP even when both containers are deployed together. The public browser calls the API directly for calendar data, so CORS is enabled globally. Website session state is in the default in-process `MemoryStore`, and its session secret is hard-coded in source.

Production Compose exposes website port 3000 and API port 3001 only on loopback. It mounts a host PostgreSQL data directory and reads email/admin credentials from Docker secrets. GitHub Actions SSHes to the host, writes secret files, pulls code, rebuilds/restarts containers, then runs Knex migrations. There is no rollback, health check, backup verification, or migration-before-traffic sequencing.

## 7. Risks, defects, and uncertain behaviour

### Critical/high priority

- **Unauthorised modification:** every API write/delete endpoint is public; CORS permits all origins. The website's admin guard does not protect the API.
- **Admin/session security:** a hard-coded session secret, plaintext single credential comparison, in-memory session storage, `resave`/`saveUninitialized` enabled, and no CSRF protection. There is no login throttling or audit trail.
- **Booking integrity:** capacity is checked and inserted without a transaction/lock, so concurrent requests can overbook. Calendar availability and creation fetch bookings using `starts >= range AND ends <= range`; bookings spanning a queried boundary are omitted. The proper overlap predicate is `booking.starts < range_end AND booking.ends > range_start`.
- **Missing rule enforcement:** API accepts arbitrary starts/ends that are merely ordered; it does not enforce assigned slots, day mask, minimum/maximum duration, sensible capacity, time zone policy, email format, or that resource/slot IDs exist in association updates.
- **Cancellation via GET:** following, previewing, or scanning a cancellation URL causes cancellation; this is unsafe and violates HTTP semantics.
- **Data exposure:** unauthenticated `GET /api/bookings` exposes all names, emails, notes, and cancellation tokens.

### Material functional/quality issues

- `PUT /api/resources/:id/slots` completes DB work but never returns HTTP success.
- Slot administration is incomplete and its create handler targets the wrong resource. Booking administration is absent.
- Some route handlers send a 400 for invalid IDs but continue executing, risking a second response/error.
- Deletes return `204` with JSON in the not-found case; a 204 must not contain a response body. API error shape/status consistency is poor.
- Confirmation and detail pages trust hidden form values. The session check only compares resource ID; it does not prove the selected time was available.
- Email failures are deliberately non-fatal (reasonable), but there is no durable outbox, retry, monitoring, or delivery state.
- The app mutates incoming booking payloads to add token/status and has no type system or API schema/documentation.
- Dates are handled by Moment and ISO strings without an explicit application time zone or DST policy.
- Dependencies are old, duplicated across workspaces, and Docker `npm install` is non-reproducible; the API build reported 23 dependency vulnerabilities (including 1 critical) during evaluation.

### Decisions that must not be guessed

- Whether a booking is for one person, one capacity unit, or a quantity; current capacity counts bookings, not attendees.
- Whether slots are fixed selectable intervals, opening windows in which arbitrary durations may be chosen, or both. Seed data contains overlapping windows and 30-minute intervals.
- Expected handling for holidays, exceptions, buffers/setup time, recurring bookings, and bookings that cross midnight.
- Retention/GDPR policy for personal data, cancelled records, and email/audit logs.

## 8. Recommended target architecture

### 8.1 Shape

Build one FastAPI application, initially serving both `/api/v1` and Jinja HTML pages. This eliminates website-to-API HTTP calls, CORS, duplicated error handling, and the two-process deployment while preserving a clean API boundary for a future JS client. Use PostgreSQL in every persistent environment; use ephemeral PostgreSQL in CI, not SQLite compatibility testing as the principal signal.

Suggested package boundaries:

```text
app/
  main.py                 # application factory, routers, middleware
  core/                   # typed settings, security, logging, time-zone policy
  db/                     # SQLAlchemy engine/session, models, Alembic
  domains/
    resources/            # models, schemas, repository/service, router
    slots/
    bookings/             # availability, transaction/locking, cancellation, email outbox
    admin/                # authentication/authorisation
  web/                    # Jinja routes, templates, static assets
  integrations/email/
  tests/                  # unit, API, UI, integration
```

### 8.2 Technology choices

- **FastAPI + Pydantic v2:** typed request/response contracts, validation, automatic OpenAPI, dependency injection.
- **SQLAlchemy 2.x + Alembic + psycopg:** explicit typed ORM models and reviewed migrations. Prefer synchronous SQLAlchemy initially unless a measured workload requires async; simplicity is more valuable here.
- **PostgreSQL:** the production source of truth. Add constraints, indexes, transactions, and migration/back-up procedures.
- **Jinja2 + HTML forms + vanilla JS:** retain familiar, accessible server-rendered pages. Use a modern maintained calendar asset locally bundled with a pinned lockfile. Do not build a SPA unless requirements justify its operational cost.
- **Authentication:** choose a proper admin identity provider or securely stored password hashes plus server-side sessions. Enforce roles in both HTML and API routes; use CSRF protection for cookie-authenticated writes.
- **Email outbox:** persist email work in the booking transaction; a worker/retry mechanism sends it and records result. Use a provider abstraction.
- **Operations:** `pyproject.toml` and locked dependencies, Ruff, mypy/pyright, pytest, Docker multi-stage build, health/readiness endpoints, structured JSON logs, error tracking, and CI against PostgreSQL.

### 8.3 Implementation conventions (mandatory)

- Every Python function/method has parameter and return annotations; all external request/response and persistence data use explicit Pydantic/SQLAlchemy types. No `Any` without a documented boundary reason.
- Keep routers thin; put business rules in typed services and persistence in repositories/query modules. Inject clock, settings, database session, and email gateway for testability.
- Validate at the boundary and enforce invariant constraints in PostgreSQL. Use UTC `timestamptz` internally and document the display/business time zone.
- Log structured events with request/correlation ID, event name, resource/booking IDs, outcome, and safe error context. Never log passwords, tokens, email bodies, or unnecessary personal data.
- Use consistent problem responses, explicit HTTP statuses, pagination for lists, and OpenAPI examples.
- Format/lint/type-check in CI; write unit tests for rules, integration tests for database/API, and browser tests for all public/admin journeys.

## 9. Acceptance baseline for replacement

The replacement is not complete when CRUD pages render. It must demonstrate: authenticated/authorised administration; resource/type/slot CRUD and assignment; resource listing; calendar availability; valid booking; no overbooking under concurrent requests; confirmation/outbox email; safe cancellation confirmation and idempotency; validation/error behaviour; migration of a production data copy; accessibility/responsiveness; backup/restore; observability; and a documented rollback. The ordered work and exit criteria are in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## 10. Questions requiring product-owner answers

1. What is the authoritative production database, data volume, uptime window, backup/restore process, and acceptable cutover downtime?
2. **Answered:** administrators use one shared credential. The replacement will use a salted password hash from secret management, secure server-side/revocable sessions, CSRF protection, rate limiting, and a generic shared-admin audit actor; it will not create individual roles/MFA/SSO unless this decision changes.
3. **Answered:** `capacity` means the maximum number of simultaneous booking records for a given resource/window (the current behaviour). Users do not specify a quantity; each booking consumes one unit of capacity.
4. **Answered:** a slot is a fixed resource-specific availability window. A booking must exactly match its start/end times and cannot be flexibly placed inside it. Overlapping windows for the same resource and weekday are **not permitted**; however, a resource may have multiple non‑overlapping windows (e.g., separate morning and afternoon slots) to reflect multiple availabilities at the same time of day.
5. **Answered:** one‑off exceptions such as holidays, closures, and special events **are required** in the first release. The `availability_exceptions` table (or equivalent) will be included to override recurring windows.
6. **Answered:** Users may view, amend, or cancel a booking up to the time the booking would start. The cutoff time (e.g., “start time minus X minutes”) should be treated as a configurable variable so it can be adjusted in the future. No GDPR obligations apply.
7. **Answered:** There are no GDPR or similar data‑retention, export/deletion, consent, or audit requirements that the system must enforce.
8. **Answered:** The API should **not** be exposed to the public; it will be internal‑only behind the web application.
9. **Answered:** The existing URLs/API contract do **not** need to be preserved. However, the email confirmation wording and subject **should be preserved** to avoid breaking user expectations.
10. **Answered:** A server‑rendered responsive website is acceptable; a JavaScript SPA or mobile app is **not** required.
