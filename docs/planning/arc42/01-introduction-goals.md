# 1. Introduction and Goals

## 1.1 Requirements Overview

Optimism is the resource-booking system for **DoES Liverpool**, a community workshop and co-working space. The system allows members and visitors to book resources (rooms, laser cutters, hot desks) through a public web interface, while administrators manage resources, availability windows, and bookings via an admin panel.

The current implementation consists of two Node.js/Express applications (a JSON API and a server-rendered Nunjucks website) backed by PostgreSQL (production) or SQLite (development/test). The codebase has accumulated technical debt: outdated dependencies, insufficient test coverage, security gaps (unauthenticated write endpoints, no CSRF protection), and a split deployment that adds operational complexity.

## 1.2 Quality Goals

| Quality Attribute | Goal | Metric / Acceptance |
|-------------------|------|---------------------|
| **Security** | Eliminate unauthenticated writes, protect admin session, CSRF protection, rate limiting | All write endpoints require authentication/authorization; OWASP Top 10 addressed |
| **Maintainability** | Single deployable FastAPI monolith with typed code, automated tests, clear architecture | 80% branch coverage (90% for critical paths); Ruff/mypy clean; ADR log |
| **Reliability** | No overbooking under concurrency; email delivery durable; graceful degradation | Concurrency tests pass; email outbox retry with dead-letter; structured logging |
| **Usability** | Accessible public booking flow (WCAG 2.1 AA); responsive design | axe-core automated checks + manual review |
| **Operability** | JSON logs, Prometheus metrics, health endpoints, migration-before-traffic | `/healthz`, `/readyz`, `/metrics`; alerts on 5xx>1%, email backlog>100 |
| **Performance** | Sub-second response for calendar reads; booking creation <500ms p95 | Load test with 10 concurrent users |

## 1.3 Stakeholders

| Stakeholder | Interest |
|-------------|----------|
| DoES Liverpool members/visitors | Book resources easily, receive confirmations, cancel if needed |
| Administrators (shared credential) | Manage resources, windows, exceptions, view/cancel bookings |
| Developers/maintainers | Clean codebase, testable, deployable, documented |
| Operations | Single container, standard health checks, observable, backup/restore |

## 1.4 Scope of This Architecture

This document describes the **target architecture** for a complete rewrite in **Python/FastAPI** replacing the existing Node.js system. It covers:

- Domain model (resources, availability windows, exceptions, bookings)
- API (`/api/v1`) and server-rendered web UI (Jinja2)
- PostgreSQL database with declarative constraints
- Authentication (shared admin credential, secure sessions)
- Email outbox with retry/dead-letter
- Observability (JSON logs, Prometheus, alerts)
- Deployment (single Docker image, migration-before-traffic)

Out of scope: mobile app, public API for third parties, multi-tenant/SaaS features.

---

> **Traceability**: Detailed evaluation in [../../EVALUATION.md](../../EVALUATION.md), implementation plan in [../../IMPLEMENTATION_PLAN.md](../../IMPLEMENTATION_PLAN.md), decisions summary in [../../summary.md](../../summary.md).