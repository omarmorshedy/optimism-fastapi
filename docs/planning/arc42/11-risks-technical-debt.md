# 11. Risks and Technical Debt

## 11.1 Identified Risks

| ID | Risk | Likelihood | Impact | Mitigation | Owner |
|----|------|------------|--------|------------|-------|
| R-01 | **Legacy data migration fails** – orphan bookings, null FKs, bitmask conversion errors | Medium | High | - Dedicated ETL script with dry-run & validation counts<br>- Staging rehearsal with production snapshot<br>- Quarantine table for anomalies | Dev |
| R-02 | **Concurrency bug allows overbooking** – advisory lock misused or skipped | Low | Critical | - Explicit lock in `BookingService.create_booking`<br>- Integration test with 20 parallel threads<br>- DB exclusion constraint as safety net | Dev |
| R-03 | **Email delivery silently fails** – SMTP credentials rotate, worker not updated | Medium | High | - Secrets injected at runtime (no restart needed for SMTP creds)<br>- Dead-letter alert triggers on max retries<br>- Health check `/readyz` verifies worker alive | Ops |
| R-04 | **Rate limiting misconfigured** – legitimate users blocked or abuse not stopped | Low | Medium | - Defaults conservative (10/min booking, 60/min calendar)<br>- Configurable via env; documented in runbook<br>- Metric `rate_limit_exceeded_total` alerts on spikes | Dev/Ops |
| R-05 | **Cancellation token leakage** – raw token logged or exposed in URL history | Low | High | - Only bcrypt hash stored<br>- Raw token never logged (structlog processor strips)<br>- Token sent only in email (one-time) | Dev |
| R-06 | **Timezone bug** – UTC vs local confusion in calendar rendering | Medium | Medium | - Fixed UTC policy (ADR-007)<br>- Tests include summer date (BST)<br>- All `timestamptz` stored as UTC; UI renders UTC explicitly | Dev |
| R-07 | **Accessibility regression** – calendar component not keyboard accessible | Medium | Medium | - axe-core in CI on every PR<br>- Manual review checklist for calendar updates<br>- FullCalendar v6+ has good a11y support | Dev |
| R-08 | **Dependency vulnerability** – CVE in FastAPI, SQLAlchemy, etc. | Medium | Medium | - Dependabot + `pip-audit` in CI<br>- Pinned versions in `poetry.lock`<br>- Monthly patch window | Dev |
| R-09 | **Single point of failure (DB)** – no HA in v1 | Medium | High | - Documented manual failover runbook<br>- Backup/restore tested quarterly<br>- Plan for managed PG (Cloud SQL, RDS) in v2 | Ops |
| R-10 | **Scope creep** – stakeholders request recurring bookings, waitlists, etc. | High | Medium | - Strict v1 scope (see [Context & Scope](../03-context-scope.md))<br>- New requests → backlog, evaluated post-v1 | PM |

## 11.2 Technical Debt (Known & Accepted)

| ID | Debt Item | Reason for Acceptance | Remediation Plan |
|----|-----------|----------------------|------------------|
| TD-01 | **No automated backup/restore** | Product decision: "not required for initial release" | Add scheduled `pg_dump` + restore test in v1.1 |
| TD-02 | **Single admin credential** | Product decision: "shared credential sufficient" | Extend to user table + roles if needed later |
| TD-03 | **Cross-midnight slots not supported** | No current requirement; seed data has none | Add `duration` or `end_day` column if requested |
| TD-04 | **No recurring bookings** | Out of scope v1 | Design `booking_series` table when needed |
| TD-05 | **In-memory rate limiter (single instance)** | Simplicity; single container in v1 | Switch to Redis-backed `fastapi-limiter` when scaling horizontally |
| TD-06 | **Email worker runs in same process** | Low volume; avoids extra infrastructure | Extract to separate service if volume grows |
| TD-07 | **No API versioning strategy beyond `/v1`** | v1 only for now | Adopt URL versioning (`/api/v2`) + deprecation policy later |
| TD-08 | **Admin audit log only captures `shared_admin`** | Single credential; no individual attribution | Add `actor_id` when multi-user auth introduced |
| TD-09 | **Static asset hashing manual** | Low churn; CSS/JS rarely change | Integrate `vite` or `webpack` if frontend grows |
| TD-10 | **No automated DB performance indexing review** | Small dataset; indexes defined upfront | Add `pg_stat_statements` review in quarterly ops |

## 11.3 Risk / Debt Tracking

- All risks logged in GitHub Issues with label `risk` and linked to this document.
- Technical debt items tracked as `tech-debt` issues with milestone `v1.1` or `v2.0`.
- Quarterly review: update likelihood/impact, close resolved, add new.

---

> **Traceability**: [Evaluation §7 (Risks)](../../EVALUATION.md), [Implementation Plan §9 (Release Gates)](../../IMPLEMENTATION_PLAN.md), conversation history.