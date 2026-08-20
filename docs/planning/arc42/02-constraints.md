# 2. Constraints

## 2.1 Technical Constraints

| Constraint | Description | Impact |
|------------|-------------|--------|
| **Language/Framework** | Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic | Team expertise; ecosystem maturity |
| **Database** | PostgreSQL 16+ (production), ephemeral PostgreSQL in CI | Single source of truth; no SQLite compatibility layer |
| **ORM** | SQLAlchemy 2.x (sync) with typed models | Explicit typing; async not required for current load |
| **Templating** | Jinja2 (built into FastAPI/Starlette) | Server-rendered HTML; minimal JS |
| **Calendar JS** | FullCalendar (locally bundled, pinned version) | Only dynamic browser component |
| **Container** | Docker multi-stage (build → runtime), non-root user | Reproducible builds; security |
| **CI/CD** | GitHub Actions with pinned action SHAs | Supply-chain security |
| **Secrets** | Docker secrets / Kubernetes secrets / `.env` (dev only) | No secrets in images or repo |

## 2.2 Organizational Constraints

| Constraint | Description |
|------------|-------------|
| **Team size** | Small (1–2 developers); favor simplicity over micro-service split |
| **Release cadence** | Infrequent; stability over velocity |
| **Documentation** | arc42 + ADRs; keep in sync with code |
| **Legacy cutover** | Single cut-over (no feature flags); rollback plan required |
| **Budget** | No managed services (Auth0, SendGrid, etc.) unless justified; self-hosted SMTP |

## 2.3 Regulatory / Compliance Constraints

| Constraint | Status |
|------------|--------|
| GDPR / data protection | **Not applicable** per product owner (no personal-data retention/export requirements) |
| Accessibility | **WCAG 2.1 AA** target for public pages |
| Email deliverability | Use existing SMTP credentials; preserve current email wording |

## 2.4 Conventions & Standards

| Area | Standard |
|------|----------|
| Code style | Ruff (format + lint), import order, line length 100 |
| Type checking | mypy/pyright strict practical mode; no `Any` without comment |
| Testing | pytest, pytest-cov, HTTPX, Playwright; 80% branch coverage (90% critical) |
| Commits | Conventional Commits; ADR for each architectural decision |
| Branching | `main` protected; PRs require green CI, review, up-to-date |
| Versioning | SemVer; tag on release |

---

> **Traceability**: See [Evaluation §2, §6, §8.2](../../EVALUATION.md) and [Implementation Plan §1–§2](../../IMPLEMENTATION_PLAN.md).