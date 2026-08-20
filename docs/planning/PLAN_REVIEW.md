# Optimism FastAPI Replacement — Plan Review

> **Scope.** Structured review of the planning documents: [summary.md](summary.md) →
> [EVALUATION.md](EVALUATION.md) → [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) →
> [docs/arc42/](docs/arc42/). Reviewed 2026-08-06 against the current Node/Express codebase
> (`api/`, `website/`, `master` branch).
>
> **Outcome.** The plan is coherent, well-evidenced, and ready to implement **provided** the
> clarifications and open decisions in §3 are resolved. The contract gap identified in §3.1 is
> resolved by [API_SPEC.md](API_SPEC.md), which is the authoritative **target** API contract
> for the FastAPI implementation (middle ground between the legacy API and the approved plan).

## 1. Verdict

| Aspect | Assessment |
|---|---|
| Evidence (evaluation) | Strong — verified against the real codebase and disposable containers; test inventory is accurate (78 API tests, 1 Cypress spec, no unit/email/Postgres tests). |
| Requirements capture | Strong — all 10 product-owner questions answered; decisions propagated to schema (ADR-006/007/008), plan, and quality requirements. |
| Target architecture | Sound — modular monolith is right-sized; sync SQLAlchemy, PostgreSQL-only, outbox, advisory locks, RFC 7807, /api/v1 are all justified. |
| Delivery strategy | Sound — test-first, quality gates before code, release gates before cutover, single cutover with rollback. |
| Documentation coherence | Good — cross-links are consistent; minor inconsistencies listed in §3.3. |
| **Blocking gaps** | **One**: the current API contract was never specified at payload level (§3.1), and the "exact replication" instruction conflicts with decision #9 — resolved by the middle-ground spec (§2). |
| **Open product decisions** | Several (see §3.2) — none prevent writing the spec; they must be signed off before parity tests are finalised. |

## 2. Resolution of the "exact replication" question

The request to "exactly replicate" the current API conflicts with the approved plan
(decision #9: URLs/API contract need not be preserved; plan §5: `/api/v1`, RFC 7807 errors,
auth on writes). **Resolution agreed with the requester:** the replacement must be *very
similar* and work straight out of the gate, i.e. a **middle ground** between the two
implementations, and every explicitly-stated improvement in the plan must be implemented and
reflected in the spec. [API_SPEC.md](API_SPEC.md) is that middle-ground contract: it preserves
the legacy route names, JSON field names (camelCase), response shapes and message wording
wherever that helps the ported web/admin UI work unchanged, and it bakes in every approved
improvement (auth, RFC 7807, corrected status codes, transactional capacity, exact-window
matching, token hashing, idempotent cancellation, email outbox, UTC, rate limits,
availability windows/exceptions). A full legacy→v1 mapping and an improvements-applied table
are included so legacy tests can be translated 1:1.

## 3. Gaps, missing items, and decisions required

### 3.1 Contract gap (now resolved)

- **The current API was never specified at payload level.** EVALUATION §5.1 lists route names
  only — no payloads, field names, status codes, error strings, or response shapes. The API
  tests assert statuses, not response contracts. → Resolved by [API_SPEC.md](API_SPEC.md),
  which documents the legacy behaviour faithfully and defines the target contract. Build the
  plan §1 traceability matrix from its §10 (improvements applied) table.

### 3.2 Open product/design decisions (flag for sign-off; defaults taken in the spec)

1. **`minimumBookingTime` / `maximumBookingTime`** — in the legacy schema/API but never
   enforced. **Spec default:** dropped from v1 (superseded by exact-window matching). Confirm.
2. **Legacy bookings that don't exactly match a window** (legacy accepts any ordered start/end;
   seed contains a 2-day booking). **Spec default:** ETL maps each booking to the covering
   window; unmappable bookings are quarantined for admin review. Confirm the policy.
3. **Capacity counting.** Legacy counts *overlapping* bookings per slot (a spanning booking
   consumes capacity in every slot it overlaps). **Spec default (per ADR-006/decision #3):**
   capacity = count of active bookings for the exact window instance. Confirm how spanning
   legacy bookings are counted during migration.
4. **User amend flow.** Decision #6 promises view/amend/cancel, but the plan defines no amend
   endpoint. **Spec default:** `GET /bookings/lookup/{token}` and
   `PUT /bookings/amend/{token}` (token-authenticated, cutoff-enforced) added. Confirm.
5. **Cancellation email.** Legacy sends none; plan is silent. **Spec default:** none in v1
   (preserve legacy). Confirm.
6. **Hard vs soft delete.** Legacy `DELETE /bookings/{id}` hard-deletes; arc42 §8.6 says no
   hard deletes. **Spec default:** admin booking delete is a soft delete. Confirm.
7. **Deletion policy for resources/resource-types.** Legacy nulls booking `resourceId` and
   `resource_type_id`. **Spec default:** resources with active bookings → 409 (no delete);
   otherwise delete (cascading windows/exceptions/links); resource types still null
   `resourceTypeId` on resources then delete. Confirm — plan §1 requires explicit sign-off.
8. **Email clock rendering.** Legacy formats times server-local; ADR-007 mandates UTC.
   **Spec default:** same wording, times rendered in UTC. Confirm the clock-time change.
9. **Pagination.** Plan §5/§8.3 mention pagination with no details. **Spec default:** minimal
   `limit`/`offset` on admin list endpoints, array response + `X-Total-Count` header. Confirm.
10. **Rate limits.** Plan lists booking-create and calendar-read only, but SEC-07 promises a
    cancel limit. **Spec default:** add `RATE_LIMIT_BOOKING_CANCEL` (10/min) and
    `RATE_LIMIT_ADMIN_LOGIN` (5/min). Confirm.
11. **Admin booking export** (plan §7: "cancel, amend, export"). No requirement detail.
    **Spec default:** deferred out of v1. Confirm.

### 3.3 Plan inconsistencies to tidy (non-blocking)

- SEC-07 mentions a rate limit on cancel that §5's env-var list omits (see §3.2.10).
- Release gates (plan §9) require backup/restore rehearsal while the product decision says
  backup/restore is not required for v1 — reconcile as a one-time pre-cutover backup.
- arc42 §5.2.5 lists `GET/PUT /resources/{id}/windows` but the runtime view §6.1.1 shows a
  query-param availability endpoint; the spec resolves this by keeping the legacy
  `GET /calendar/{start}/{end}/{resourceId}` shape as the single availability-read endpoint.
- The outbox is specified to store "reference IDs only", but the email body contains booking
  details — the spec requires the outbox to store the composed payload (or a deterministic
  template reference) so sends are correct even if the booking is later amended.
- Minor doc errors: slots.js test comment calls the join table `resources_types`;
  EVALUATION says 204-with-body (Express actually strips 204 bodies); calendar test's
  "start > end" case pairs an invalid resource id with the date check (date check fires first).

## 4. Action items

| # | Action | Owner | Status |
|---|---|---|---|
| 1 | Write middle-ground API target contract | — | **Done** → [API_SPEC.md](API_SPEC.md) |
| 2 | Record plan-review decisions in [summary.md](summary.md) | — | **Done** |
| 3 | Sign off §3.2 default decisions (1–11) | Product owner | Open |
| 4 | Build legacy→v1 traceability matrix from API_SPEC §10 | Dev | Open |
| 5 | Reconcile backup/restore vs release gates (one-time pre-cutover backup) | Product owner + Ops | Open |
| 6 | Proceed with plan §1 test-first baseline against the API_SPEC contract | Dev | Open |

---

> **Traceability:** decisions derive from [summary.md](summary.md), [EVALUATION.md](EVALUATION.md)
> §10, [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md), and [docs/arc42/](docs/arc42/).
