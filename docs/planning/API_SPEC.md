# Optimism API — Target Contract v1 (FastAPI replacement)

> **Purpose.** This is the authoritative API contract the FastAPI implementation must satisfy.
> It is deliberately a **middle ground** between the legacy Node/Express API (`api/` on
> `master`) and the approved replacement plan ([IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md),
> [docs/arc42/](docs/arc42/), [summary.md](summary.md)): it preserves the legacy route names,
> JSON field names, response shapes, and message wording wherever that keeps the ported web and
> admin UI working nearly unchanged, and it bakes in **every explicitly-approved improvement**
> (auth on writes, RFC 7807 errors, corrected status codes, transactional capacity, exact-window
> booking matching, hashed cancellation tokens, idempotent cancellation, email outbox, fixed
> UTC, rate limiting, availability windows/exceptions).
>
> **Reading guide.** §1 conventions · §2 domain model · §3 public endpoints · §4 admin endpoints
> · §5–§7 exact algorithms (booking, calendar, cancellation/amendment) · §8 email & outbox ·
> §9 error catalog · §10 improvements applied vs legacy (parity matrix) · §11 default decisions
> taken in this spec · §12 deferred/open items.
>
> **Legacy equivalence.** Each endpoint lists its legacy counterpart
> (e.g. `← GET /api/resources`). Where the legacy behaviour was buggy or insecure, the v1
> behaviour is the corrected one and the difference is flagged; see §10.

---

## 1. Conventions and cross-cutting concerns

### 1.1 Base path and media types

- Base path: **`/api/v1`** (legacy was `/api`; decision #9 permits new URLs — the internal
  prefix is the approved one). All routes below are relative to `/api/v1`.
- Request bodies: `application/json`. All responses are JSON; errors use RFC 7807
  `application/problem+json` (§1.3).
- The API is **internal-only** (decision #8): not exposed to the public internet; all external
  traffic goes through the web application in the same process. No CORS headers are served.
- OpenAPI is generated automatically (`/openapi.json`, `/docs`) and is part of the deliverable.

### 1.2 IDs, dates, times, weekday

- **IDs:** non-negative integers (legacy `checkId` rule). Invalid ids → `422` (legacy `400`).
- **Booking datetimes:** ISO-8601 strings. A value **without an offset is interpreted as UTC**
  (ADR-007 — legacy used server-local time). Stored as `timestamptz`; responses always
  serialise in UTC with `Z` (e.g. `2022-03-17T09:30:00.000Z`).
- **Calendar dates:** `YYYY-MM-DD` (legacy format, strict ISO-8601 parsing; full datetime
  strings also accepted).
- **Window times:** `HH:mm` strings, interpreted as UTC clock times within a single day
  (single-day assumption, decision #11; cross-midnight windows rejected).
- **Weekday:** integer `0..6`, Sunday = 0 (keeps the legacy bitmask convention).

### 1.3 Error responses — RFC 7807 problem details

Every error is `application/problem+json`:

```json
{
  "type": "https://optimism.example/errors/conflict",
  "title": "Conflict",
  "status": 409,
  "detail": "This time slot is already fully booked. Please select another time.",
  "instance": "/api/v1/bookings",
  "request_id": "abc123"
}
```

Status mapping (legacy status shown where it differed):

| Condition | Status | Legacy |
|---|---|---|
| Request validation (bad id, bad/missing fields, malformed date, bad time) | `422` | `400` |
| Resource/booking/window not found | `404` | `404` |
| Capacity exceeded, window overlap, duplicate name, deletion blocked, cutoff passed, already-cancelled on amend | `409` | `409`/`400` |
| Not authenticated / invalid admin credentials | `401` | — (none) |
| Authenticated but not authorised | `403` | — (none) |
| Rate limit exceeded | `429` | — (none) |
| DB pool exhausted / unavailable | `503` | — |
| Unexpected error | `500` | `500` (plain text) |

`detail` strings reuse the legacy wording verbatim wherever the semantics are unchanged
(e.g. `"This time slot is already fully booked. Please select another time."`).

### 1.4 Authentication and authorisation

- **Public (no session):** read endpoints (resources, resource-types, calendar) and the
  booking create/amend/cancel/lookup token endpoints. Booking writes are **defended by rate
  limits** (§1.5), not by login.
- **Admin (session required):** every other write/delete and all booking-list/detail
  endpoints, windows and exceptions CRUD, resource/resource-type management.
- **Mechanism (ADR-005):** one shared credential; salted hash (`bcrypt`, cost 12) stored in
  secrets (`ADMIN_PASSWORD_HASH`). `POST /admin/login` sets a signed server-side session
  cookie (`Secure; HttpOnly; SameSite=Lax`, 1 h expiry, rotated on login, revocable via
  `admin_sessions` table). **CSRF protection** (double-submit cookie) is required on all
  state-changing requests authenticated by cookie, including API writes.
- **Audit (decision #2):** every admin state change appends an `audit_events` row
  (`action`, `actor: "shared_admin"`, resource/booking ids, outcome, timestamp).

### 1.5 Rate limiting (per IP; decision #12)

| Endpoint group | Limit | Env var | Default |
|---|---|---|---|
| Booking creation | 10 req/min | `RATE_LIMIT_BOOKING_CREATE` | `10/minute` |
| Booking cancel + amend + lookup | 10 req/min | `RATE_LIMIT_BOOKING_CANCEL` (new — resolves SEC-07) | `10/minute` |
| Calendar reads | 60 req/min | `RATE_LIMIT_CALENDAR_READ` | `60/minute` |
| Admin login | 5 req/min | `RATE_LIMIT_ADMIN_LOGIN` (new, defensive) | `5/minute` |

Excess requests → `429` problem response.

### 1.6 Pagination (admin lists only)

Optional `limit` (default 100, max 1000) and `offset` (default 0) query parameters on admin
list endpoints. The response remains a JSON **array**; the total count is returned in the
`X-Total-Count` response header. (Legacy had no pagination.)

### 1.7 Observability

- Structured JSON logs to stdout with `timestamp, level, request_id, path, method, status,
  duration_ms`; never log passwords, tokens, email bodies, or personal data.
- `GET /healthz` (liveness, always 200), `GET /readyz` (DB reachable, migrations applied,
  email worker alive), `GET /metrics` (Prometheus text format). Alerts per decision #14.

### 1.8 Cancellation cutoff (decision #6, ADR-009)

`BOOKING_CANCELLATION_CUTOFF_MINUTES` (default `5`). User amend/cancel are allowed only while
`now < booking.starts - cutoff`. Past the cutoff → `409`. Admin actions are exempt.

---

## 2. Domain model (API view)

JSON field names are camelCase (legacy-compatible). Database columns are snake_case.

### 2.1 Entities

**Resource** `{ id, resourceTypeId, name, capacity }`
- `resourceTypeId`: nullable integer. `name`: non-empty, **unique** (improvement: legacy
  allowed null/duplicates). `capacity`: positive integer — max simultaneous bookings per
  window instance (decision #3).
- **Dropped from v1:** `minimumBookingTime` / `maximumBookingTime` (legacy fields, never
  enforced; superseded by exact-window matching — see §11.1).

**ResourceType** `{ id, name }` — `name`: non-empty, unique (improvement).

**AvailabilityWindow** `{ id, resourceId, weekday, starts, ends, name }`
- One row = one recurring fixed UTC window for one resource on one weekday (ADR-008).
- `weekday`: 0–6 (Sunday=0). `starts`/`ends`: `HH:mm`, UTC, same day (`ends > starts`).
- `name`: nullable free-text label (kept from legacy `slots.name` for admin familiarity).
- **No overlapping windows** for the same `(resourceId, weekday)` (exclusion constraint) →
  `409` on conflict.

**AvailabilityException** `{ id, resourceId, startDate, endDate, kind, reason }`
- One-off override for a date range (inclusive), decision #5. `kind`: `closed` | `open`
  (`open` adds availability outside recurring windows; `closed` removes it). `reason`:
  optional. Date range non-empty (`endDate >= startDate`).

**Booking** `{ id, resourceId, email, name, notes, starts, ends, cancelled, createdAt }`
- `resourceId`: non-null (improvement — legacy allowed null). `starts`/`ends`: UTC datetimes,
  `ends > starts`. `cancelled`: boolean (kept from legacy for UI compatibility; internally the
  status model may use an enum). `notes`: required (legacy NOT NULL), may be empty string.
- **`token` is never present in list/detail responses** (improvement — legacy exposed it).
  The raw cancellation token is returned **once**, in the `POST /bookings` response only
  (§3.4), and only its hash is stored (ADR-005).

### 2.2 Booking and capacity rules (improved)

1. A booking must **exactly match** one availability window instance: its `starts`/`ends`
   equal a window's `weekday`/`starts`/`ends` expanded onto the booking date (decision #4).
2. Capacity = number of **active (non-cancelled) bookings for that exact window instance**;
   if it would reach `capacity`, creation/amendment → `409`.
3. Overlap counting uses the correct predicate:
   `existing.starts < requested.ends AND existing.ends > requested.starts` (fixes the legacy
   boundary-spanning bug).
4. Creation performs the capacity check and insert **in one transaction under an advisory
   lock** on the resource/window (no overbooking under concurrency — ADR-006, plan §4).
5. Recurring windows are expanded per date; exceptions override them (`closed` removes,
   `open` adds). Windows and bookings are all UTC.

### 2.3 Legacy → v1 endpoint mapping

| Legacy (current) | v1 (target) | Change |
|---|---|---|
| `GET /api/resources` | `GET /resources` | preserved |
| `GET /api/resources/:id` | `GET /resources/{id}` | preserved |
| `POST /api/resources` | `POST /resources` | admin-only; returns resource object (legacy returned `[{id}]`) |
| `PUT /api/resources/:id` | `PUT /resources/{id}` | admin-only |
| `DELETE /api/resources/:id` | `DELETE /resources/{id}` | admin-only; `404` when missing (legacy `204`); `409` when active bookings |
| `GET /api/resources/:id/slots` | `GET /resources/{id}/windows` | windows replace slots (ADR-008) |
| `PUT /api/resources/:id/slots` | `PUT /resources/{id}/windows` | now returns `204` (legacy never responded) |
| `GET/POST /api/resource-types`, `GET/PUT/DELETE /api/resource-types/:id` | same under `/resource-types` | admin write; read stays public |
| `GET/POST /api/slots`, `GET/PUT/DELETE /api/slots/:id` | `GET/POST /availability-windows`, `GET/PUT/DELETE /availability-windows/{id}` | replaced model (ADR-008) |
| — | `GET/POST /availability-exceptions`, `GET/PUT/DELETE /availability-exceptions/{id}` | new (decision #5) |
| `GET /api/calendar/:start/:end/:resourceId` | `GET /calendar/{startDate}/{endDate}/{resourceId}` | preserved shape; corrected algorithm |
| `GET /api/bookings` | `GET /bookings` | **admin-only** (legacy public data exposure) |
| `GET /api/bookings/:id` | `GET /bookings/{id}` | **admin-only**; no token field |
| `POST /api/bookings` | `POST /bookings` | public; corrected algorithm |
| `PUT /api/bookings/:id` | `PUT /bookings/{id}` | **admin-only** amend (legacy unauth) |
| `DELETE /api/bookings/:id` | `DELETE /bookings/{id}` | **admin-only**; soft delete |
| — | `POST /bookings/{id}/cancel` | new (admin cancel action, plan §7) |
| — | `GET /bookings/lookup/{token}` | new (decision #6: view) |
| — | `PUT /bookings/amend/{token}` | new (decision #6: amend) |
| `POST /api/bookings/cancel/:token` | `POST /bookings/cancel/{token}` | idempotent (legacy 400 on double-cancel) |
| — | `POST /admin/login`, `POST /admin/logout` | new (decision #2) |

---

## 3. Public endpoints

### 3.1 `GET /api/v1/resources` ← `GET /api/resources`

`200` — array of `Resource` (§2.1), ordered by `id`. Rate-limited? No (calendar reads are).

### 3.2 `GET /api/v1/resource-types` ← `GET /api/resource-types`

`200` — array of `ResourceType`, ordered by `id`.

### 3.3 `GET /api/v1/calendar/{startDate}/{endDate}/{resourceId}` ← `GET /api/calendar/...`

Availability for a resource over an inclusive date range, consumed by the calendar UI.
Rate limit: `RATE_LIMIT_CALENDAR_READ`. Algorithm in §6. Response shape **identical to
legacy** (the `slots` array entries are dated window instances):

```json
{
  "dates": [
    {
      "date": "2022-03-17T00:00:00.000Z",
      "resources": [
        {
          "resourceName": "Dinky",
          "slots": [
            { "starts": "2022-03-17T09:30:00.000Z", "ends": "2022-03-17T10:00:00.000Z", "status": "available" }
          ]
        }
      ]
    }
  ]
}
```

Errors: `422` invalid `startDate`/`endDate`/`resourceId` or `endDate <= startDate`; `404`
unknown resource.

### 3.4 `POST /api/v1/bookings` ← `POST /api/bookings`

Create a booking (public, rate limit `RATE_LIMIT_BOOKING_CREATE`). Request:

```json
{ "resourceId": 1, "starts": "2022-03-17T09:30:00", "ends": "2022-03-17T10:00:00",
  "email": "someone@example.org", "name": "A Name", "notes": "Some text" }
```

`201` — the created booking **plus** `resourceName` and the raw `token` (one-time only):

```json
{ "id": 42, "resourceId": 1, "email": "someone@example.org", "name": "A Name",
  "notes": "Some text", "starts": "2022-03-17T09:30:00.000Z", "ends": "2022-03-17T10:00:00.000Z",
  "cancelled": false, "createdAt": "2022-03-17T09:00:00.000Z",
  "resourceName": "Dinky", "token": "abc123…" }
```

Exact algorithm in §5. Errors: `422` validation (incl. "End time must be after start time."),
`404` unknown resource, `409` full window ("This time slot is already fully booked. Please
select another time."), `429` rate limit.

### 3.5 `GET /api/v1/bookings/lookup/{token}` — NEW (decision #6: "view")

`200` — booking (no token field) + `resourceName`, for the user-facing confirmation/amend
page. `404` unknown token.

### 3.6 `PUT /api/v1/bookings/amend/{token}` — NEW (decision #6: "amend")

Token-authenticated amendment (rate limit `RATE_LIMIT_BOOKING_CANCEL`). Request: subset of
`{ name, email, notes, starts, ends }`. Rules in §7. `200` — updated booking (no token);
`404` unknown token; `409` booking cancelled, cutoff passed, or the new time is unavailable;
`422` invalid fields.

### 3.7 `POST /api/v1/bookings/cancel/{token}` ← `POST /api/bookings/cancel/:token`

Rate limit `RATE_LIMIT_BOOKING_CANCEL`. **Idempotent** (improvement): cancelling an
already-cancelled booking succeeds with the same `200` response. `404` unknown token.

`200` — `{ "message": "Booking cancelled successfully.", "booking": { ... } }`
(the booking object without a token field).

---

## 4. Admin endpoints (session required; CSRF on writes; audited)

### 4.1 `POST /api/v1/admin/login`, `POST /api/v1/admin/logout` — NEW

- `POST /admin/login` `{ "password": "…" }` → `200` + session cookie; `401` on wrong
  password (generic message); `429` rate limited.
- `POST /admin/logout` → `204`, revokes the session.

### 4.2 Resources

- `POST /resources` — body `{ resourceTypeId?, name, capacity }` → `201` Resource.
  `409` duplicate name; `422` invalid.
- `PUT /resources/{id}` — partial update over the same fields → `200` Resource; `404`;
  `409` duplicate name.
- `DELETE /resources/{id}` — `204`; `404` when missing (legacy returned 204); `409` when the
  resource has active (non-cancelled) bookings (§11.4 default). Deletion cascades to the
  resource's windows, exceptions, and slot links.
- `GET /resources/{id}/windows` ← legacy `GET /resources/:id/slots` — `200` array of
  AvailabilityWindow for the resource; `404` unknown resource.
- `PUT /resources/{id}/windows` ← legacy `PUT /resources/:id/slots` — **replaces all**
  windows for the resource. Body: array of `{ weekday, starts, ends, name? }` (no ids).
  → `204` on success (legacy sent no response — defect fixed); `422` invalid entries;
  `409` overlap within the replacement set.

### 4.3 Resource types

`GET/POST /resource-types`, `GET/PUT/DELETE /resource-types/{id}` — mirrors §4.2 with
`ResourceType` (`{ name }`). `DELETE` nulls `resourceTypeId` on referencing resources, then
deletes (legacy behaviour, kept — §11.5). Duplicate/blank name → `409`.

### 4.4 Availability windows and exceptions

- `GET /availability-windows` — optional `?resourceId=` filter; `200` array. *(Admin list;
  the public availability read is the calendar endpoint.)*
- `POST /availability-windows` — `{ resourceId, weekday, starts, ends, name? }` → `201`;
  `409` overlap/duplicate for the same resource+weekday.
- `GET/PUT/DELETE /availability-windows/{id}` — `PUT` partial update (revalidates overlap);
  `DELETE` → `204`.
- `GET /availability-exceptions` (optional `?resourceId=`), `POST /availability-exceptions`
  (`{ resourceId, startDate, endDate, kind, reason? }` → `201`), `GET/PUT/DELETE
  /availability-exceptions/{id}` — same pattern; `409` on overlapping exception ranges for
  the same resource if that is the chosen constraint.

### 4.5 Bookings (admin)

- `GET /bookings` ← legacy public list — `200` array, ordered by `starts` desc. Optional
  filters: `resourceId`, `cancelled` (`true|false`), `email` (substring), `startsFrom`,
  `startsTo`. Pagination per §1.6. **No token field** (improvement).
- `GET /bookings/{id}` — `200` booking (no token); `404`.
- `PUT /bookings/{id}` — admin amend (partial update; times revalidated against windows and
  capacity like §5, but **cutoff does not apply** to admin) → `200`; `404`; `409`.
- `POST /bookings/{id}/cancel` — admin cancel → `200` (idempotent); `404`.
- `DELETE /bookings/{id}` — **soft delete** (§11.6): marks the booking deleted/cancelled and
  stops it counting toward capacity → `204`; `404` when missing.

---

## 5. `POST /bookings` — exact algorithm

1. Validate body (Pydantic): `resourceId, email, name, notes, starts, ends` required,
   `notes` string, `email` must be a valid email address (improvement — legacy accepted
   anything). Unknown fields / missing / malformed → `422`.
2. Resource exists → else `404` (`"Resource not found."`).
3. `ends > starts` (UTC) → else `422` (`"End time must be after start time."`).
4. Resolve the window instance: exactly one AvailabilityWindow for
   `(resourceId, weekday(starts))` whose `starts`/`ends` times equal the requested times →
   else `422` (booking must exactly match a window; decision #4). Apply availability
   exceptions for that date (`closed` removes the window, `open` may add one) → unavailable
   → `409`.
5. **In one transaction, under an advisory lock** on the resource/window:
   - count active (non-cancelled, non-deleted) bookings overlapping the window instance with
     the correct predicate `existing.starts < requested.ends AND existing.ends >
     requested.starts`;
   - if `count >= capacity` → `409` (`"This time slot is already fully booked. Please select
     another time."`);
   - insert the booking with a random URL-safe token (32 bytes) — **store only its hash**
     (ADR-005); persist the composed confirmation email in the **outbox** (ADR-010, §8.2);
   - commit.
6. Respond `201` with the booking (UTC ISO datetimes), `resourceName`, and the **raw token
   once** (for the confirmation page and the cancellation link in the email).
7. A background worker sends the email from the outbox with exponential back-off; the request
   never fails on SMTP problems (improvement — legacy fire-and-forget).

## 6. `GET /calendar/{startDate}/{endDate}/{resourceId}` — exact algorithm

1. Validate `startDate`, `endDate` (strict ISO-8601), `endDate > startDate`, `resourceId`;
   fetch resource → `404` if missing.
2. Load the resource's availability windows and any exceptions overlapping the range.
3. Load active bookings for the resource using the correct overlap predicate against the
   range (`starts < rangeEnd AND ends > rangeStart` — fixes the legacy boundary bug).
4. For each day in `[startDate, endDate]` (UTC): for each window whose `weekday` matches and
   that is not removed by a `closed` exception (plus any `open` exceptions), compute the
   instance `starts`/`ends` (date + window time in UTC).
5. `status = "available"` iff the count of active bookings overlapping the instance is
   `< capacity`, else `"unavailable"`.
6. Respond with the legacy shape (§3.3): `{ dates: [{ date, resources: [{ resourceName,
   slots: [{ starts, ends, status }] }] }] }`.

## 7. Cancellation and amendment rules

- **User cancel (`POST /bookings/cancel/{token}`):** allowed iff booking exists, is not
  already cancelled, and `now < starts - BOOKING_CANCELLATION_CUTOFF_MINUTES` (else `409`).
  Idempotent: repeat calls return `200` with the same message. Marks `cancelled = true`;
  booking stops counting toward capacity.
- **User amend (`PUT /bookings/amend/{token}`):** same preconditions; `name`/`email`/`notes`
  may change freely; `starts`/`ends` changes are re-validated exactly like creation (§5,
  including capacity and exceptions). Response `200` with the updated booking (no token).
- **Admin cancel/amend:** no cutoff, no token needed; amend still re-validates time changes
  against windows and capacity.
- **Web flow (CSRF):** `GET /cancel-booking/{token}` renders a confirmation page;
  `POST /bookings/cancel/{token}` performs the state change (fixes the legacy GET-cancels
  hazard; plan §4).

## 8. Email confirmation and outbox

### 8.1 Content (preserved verbatim — ADR-015, decision #9)

- **Subject:** `Booking Confirmation - {resourceName}`
- **Body (plain text):**

  ```
  Welcome {booking.name}!

  Your booking has been confirmed.

  Booking Details:
  - Resource: {resourceName}
  - Start: {startTime}
  - End: {endTime}
  - Notes: {booking.notes}        (line present only when notes is non-empty)

  If you need to cancel this booking, please use the following link:
  {cancellationUrl}

  Thank you for your booking!
  ```

- `startTime`/`endTime` = `moment(booking.starts/ends).format('dddd, MMMM Do YYYY, h:mm a')`
  **rendered in UTC** (ADR-007; legacy rendered server-local — §11.8).
- `cancellationUrl = {OPTIMISM_WEBSITE_BASE_URL}/cancel-booking/{rawToken}`.
- `from` = `OPTIMISM_EMAIL_ORG_FROM_ADDR`, `to` = `booking.email`, `bcc` =
  `OPTIMISM_EMAIL_ORG_NOTIFY_ADDR` (legacy behaviour preserved).

### 8.2 Outbox and retry (ADR-010, decision #13)

- The composed email payload is persisted in `email_outbox` **inside the booking
  transaction** (stores the rendered body — §3.3 of the review).
- Worker sends via SMTP; on failure retries with exponential back-off:
  `EMAIL_RETRY_BASE_DELAY_SECONDS` (60), `EMAIL_RETRY_MAX_ATTEMPTS` (5),
  `EMAIL_RETRY_MAX_DELAY_SECONDS` (960). After the final failure → `dead_letter` + alert.
- No cancellation email in v1 (§11.7).

## 9. Error catalog (problem types)

| `type` suffix | `status` | Used for |
|---|---|---|
| `validation` | 422 | malformed ids/dates/fields, end≤start, non-window times |
| `not-found` | 404 | unknown resource, booking, token, window |
| `conflict` | 409 | capacity, window overlap, duplicate name, deletion blocked, cutoff passed, cancelled-on-amend |
| `unauthorized` | 401 | missing/invalid session, bad login |
| `forbidden` | 403 | admin endpoint without admin session |
| `rate-limited` | 429 | §1.5 limits |
| `unavailable` | 503 | DB pool exhaustion |
| `internal` | 500 | unhandled errors (logged with request_id) |

## 10. Improvements applied vs legacy (parity matrix)

Every legacy behaviour that the approved plan changes is listed here; this is the input for
the traceability matrix required by IMPLEMENTATION_PLAN.md §1. `[P]` = preserved, `[C]` =
changed/improved, `[N]` = new.

| # | Legacy behaviour | v1 behaviour | Verdict |
|---|---|---|---|
| 1 | All endpoints unauthenticated; CORS `*`; `GET /api/bookings` exposes names/emails/tokens | Writes admin-authenticated; bookings list/detail admin-only; no token exposure | [C] |
| 2 | `PUT /api/resources/:id/slots` never responds | Returns `204` | [C] |
| 3 | DELETE of missing id → `204` | → `404` | [C] |
| 4 | Plain-text error strings, inconsistent statuses | RFC 7807 problem+json; `422` for validation | [C] |
| 5 | Capacity check without lock; overbookable | Advisory lock + transaction (no overbooking) | [C] |
| 6 | Overlap query `starts >= start AND ends <= end` (hides boundary-spanning) | Correct `starts < end AND ends > start` predicate | [C] |
| 7 | Arbitrary booking times; slots/min-max never enforced | Booking must exactly match a window | [C] |
| 8 | Raw token stored plaintext, returned in lists | Hash stored; raw token returned once at creation | [C] |
| 9 | Double-cancel → 400 | Idempotent cancel → 200 | [C] |
| 10 | Hard booking delete; resource delete nulls `resourceId`; type delete nulls `resourceTypeId` | Admin-only; soft booking delete; resource delete blocked with active bookings; type delete nulls (kept) | [C] |
| 11 | `minimumBookingTime`/`maximumBookingTime` unused | Dropped from API | [C] |
| 12 | Fire-and-forget email, no retry; server-local times | Outbox + back-off/dead-letter; UTC rendering | [C] |
| 13 | No timezone policy | Fixed UTC (timestamptz) | [C] |
| 14 | `/api/...` URLs, no versioning | `/api/v1/...` | [C] |
| 15 | Reusable `slots` + bitmask + `resources_slots` | Per-resource `availability_windows` + `availability_exceptions` | [C] |
| 16 | `GET /api/bookings` unfiltered, unpaginated | Admin filters + pagination | [C] |
| 17 | GET cancels a booking via the web page | GET shows confirmation; POST cancels | [C] |
| 18 | No rate limits | 10/min create, 60/min calendar, 10/min cancel/amend, 5/min login | [N] |
| 19 | No amend/lookup endpoints | `GET /bookings/lookup/{token}`, `PUT /bookings/amend/{token}`, `POST /bookings/{id}/cancel`, admin login/logout | [N] |
| 20 | Calendar JSON shape, resource/resource-type fields, booking fields (`resourceId`, `cancelled`, `notes`…), email wording, id rule (integer ≥ 0), weekday Sunday=0 | **Preserved** to keep the ported UI working unchanged | [P] |

## 11. Default decisions taken in this spec (confirm with product owner)

Where the plan left a choice open, this spec fixes a default so implementation can start.
Flag any you disagree with.

1. **`min`/`max` minutes dropped** (superseded by exact-window matching).
2. **Capacity counts bookings per exact window instance** (ADR-006); spanning legacy bookings
   are mapped to their covering window during ETL; unmappable bookings quarantined for admin
   review.
3. **User amend flow** via `PUT /bookings/amend/{token}` (+ `GET /bookings/lookup/{token}`).
4. **Resource deletion:** `409` while active bookings exist; otherwise cascade windows/
   exceptions and delete.
5. **Resource-type deletion** keeps legacy nulling of `resourceTypeId`.
6. **Booking delete is soft** (no hard delete, per arc42 §8.6).
7. **No cancellation email** in v1 (preserves legacy).
8. **Email times rendered in UTC** (ADR-007), same wording.
9. **Pagination:** `limit`/`offset` + `X-Total-Count` on admin lists.
10. **Extra rate limits:** `RATE_LIMIT_BOOKING_CANCEL` (10/min), `RATE_LIMIT_ADMIN_LOGIN`
    (5/min).
11. **Admin booking export** deferred out of v1.

## 12. Deferred / open items

- Admin booking **export** (plan §7) — no requirement detail yet.
- Backup/restore automation — explicitly out of v1 (decision #1); release gates require at
  least a one-time pre-cutover backup (see PLAN_REVIEW §3.3).
- Exact ETL mapping rules for legacy data (nulls, duplicate names, orphan bookings,
  bitmask → windows) — data-level concern, see IMPLEMENTATION_PLAN.md §3; the API contract
  above is unaffected.
- External URL scheme and DNS/proxy cutover — deployment concern (arc42 §7).
- The web layer (Jinja pages, FullCalendar, WCAG 2.1 AA, `/cancel-booking/{token}` page) is
  out of scope for this API document but consumes §3/§4 endpoints.

---

> **Traceability:** derived from [EVALUATION.md](EVALUATION.md) §5.1/§7/§10,
> [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) §1–§8, [summary.md](summary.md) decisions
> #1–#16, [docs/arc42/](docs/arc42/) (esp. §5.2.5, §8), and the legacy code in `api/`.
> Review context: [PLAN_REVIEW.md](PLAN_REVIEW.md).
