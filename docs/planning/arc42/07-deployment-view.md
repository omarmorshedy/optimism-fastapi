# 7. Deployment View

## 7.1 Deployment Architecture

```mermaid
C4Deployment
title Deployment – Optimism FastAPI

Container(web, "Optimism Container", "FastAPI + Jinja + Worker", "Docker")
ContainerDb(db, "PostgreSQL", "Primary DB", "Docker / Managed")
ContainerExt(smtp, "SMTP Relay", "Email delivery", "External")
Node(infra, "Infrastructure", "Docker Host / K8s", "Linux")
Rel(web, db, "TCP 5432", "SQLAlchemy")
Rel(web, smtp, "TCP 587/465", "aiosmtplib")
Rel(infra, web, "Manages", "systemd / kubelet")
Rel(infra, db, "Manages", "systemd / cloud SQL")
```

## 7.2 Docker Image (Multi-Stage)

```dockerfile
# ---- Build Stage ----
FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml poetry.lock* ./
RUN pip install --no-cache-dir poetry && poetry install --only main --no-root
COPY . .
RUN poetry install --only main --no-root

# ---- Runtime Stage ----
FROM python:3.12-slim AS runtime
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# Non-root user
RUN addgroup --system app && adduser --system --ingroup app app
COPY --from=builder /app /app
USER app
EXPOSE 8000
ENV PORT=8000
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "4", "-b", "0.0.0.0:8000", "app.main:app"]
```

### Build Arguments / Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@db:5432/optimism` |
| `SMTP_HOST` | SMTP server hostname | `smtp.example.com` |
| `SMTP_PORT` | SMTP port | `587` |
| `SMTP_USER` | SMTP username | `user` |
| `SMTP_PASS` | SMTP password | `***` (secret) |
| `SMTP_TLS` | Use STARTTLS | `true` |
| `ADMIN_PASSWORD_HASH` | bcrypt hash of shared admin password | `$2b$12$...` (secret) |
| `SESSION_SECRET` | Random secret for session signing | `***` (secret) |
| `RATE_LIMIT_*` | See [Configurable Constants](#configurable-constants) | |
| `BOOKING_CANCELLATION_CUTOFF_MINUTES` | | `5` |
| `EMAIL_RETRY_*` | | |
| `OBSERVABILITY_ALERT_*` | | |
| `AUTO_MIGRATE` | Run Alembic on startup (dev/staging only) | `true` |
| `LOG_LEVEL` | `INFO` / `DEBUG` | `INFO` |

Secrets (`SMTP_PASS`, `ADMIN_PASSWORD_HASH`, `SESSION_SECRET`) **must** be provided via Docker secrets, Kubernetes secrets, or a secret manager – never baked into the image.

## 7.3 Docker Compose (Development / Staging)

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: optimism
      POSTGRES_USER: optimism
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    volumes:
      - pgdata:/var/lib/postgresql/data
    secrets:
      - db_password
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U optimism"]
      interval: 5s
      timeout: 3s
      retries: 10

  web:
    build: .
    environment:
      DATABASE_URL: postgresql://optimism:{{SECRET}}@db:5432/optimism
      SMTP_HOST: smtp.example.com
      SMTP_PORT: "587"
      SMTP_USER_FILE: /run/secrets/smtp_user
      SMTP_PASS_FILE: /run/secrets/smtp_pass
      ADMIN_PASSWORD_HASH_FILE: /run/secrets/admin_hash
      SESSION_SECRET_FILE: /run/secrets/session_secret
      AUTO_MIGRATE: "true"
      LOG_LEVEL: DEBUG
    ports:
      - "8000:8000"
    depends_on:
      db:
        condition: service_healthy
    secrets:
      - smtp_user
      - smtp_pass
      - admin_hash
      - session_secret

volumes:
  pgdata:

secrets:
  db_password:
    file: ./secrets/db_password.txt
  smtp_user:
    file: ./secrets/smtp_user.txt
  smtp_pass:
    file: ./secrets/smtp_pass.txt
  admin_hash:
    file: ./secrets/admin_hash.txt
  session_secret:
    file: ./secrets/session_secret.txt
```

## 7.4 Production Deployment (Kubernetes Example)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: optimism
spec:
  replicas: 2
  selector:
    matchLabels:
      app: optimism
  template:
    metadata:
      labels:
        app: optimism
    spec:
      containers:
        - name: web
          image: registry.example.com/optimism:1.2.3
          ports:
            - containerPort: 8000
          envFrom:
            - secretRef:
                name: optimism-secrets
          readinessProbe:
            httpGet:
              path: /readyz
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 20
          resources:
            requests:
              cpu: "100m"
              memory: "128Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"
---
apiVersion: v1
kind: Service
metadata:
  name: optimism
spec:
  selector:
    app: optimism
  ports:
    - port: 80
      targetPort: 8000
```

### Required Kubernetes Secrets (`optimism-secrets`)

| Key | Source |
|-----|--------|
| `DATABASE_URL` | `postgresql://user:pass@postgres:5432/optimism` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_TLS` | SMTP credentials |
| `ADMIN_PASSWORD_HASH` | `bcrypt` hash (generated once) |
| `SESSION_SECRET` | 32-byte random |
| `RATE_LIMIT_*`, `BOOKING_CANCELLATION_CUTOFF_MINUTES`, `EMAIL_RETRY_*`, `OBSERVABILITY_ALERT_*` | ConfigMap or secret |

## 7.5 Migration Strategy

| Environment | Migration Trigger |
|-------------|-------------------|
| **Development** | `AUTO_MIGRATE=true` on container start |
| **Staging** | `AUTO_MIGRATE=true` on container start |
| **Production** | **Separate job** before deployment: `alembic upgrade head` (via CI/CD pipeline) |

**Rollback**: `alembic downgrade -1` (each migration must be reversible). Keep previous image tagged for instant rollback.

## 7.6 Backup & Restore (Initial Manual Process)

| Action | Command |
|--------|---------|
| **Backup** | `pg_dump -h <host> -U optimism optimism > optimism_$(date +%F).sql` |
| **Restore** | `psql -h <host> -U optimism optimism < backup.sql` |
| **Verify** | Run migration dry-run: `alembic upgrade head --sql` |

Automation of backup/restore is **out of scope for v1** (per product decision).

## 7.7 Network & Security

- **Ingress**: TLS termination at load balancer / ingress controller
- **Internal**: `web` ↔ `db` on private network only
- **Egress**: `web` → SMTP (port 587/465) only
- **No public exposure** of database or API ports

---

> **Traceability**: [Evaluation §6, §8.2](../../EVALUATION.md), [Implementation Plan §2, §9](../../IMPLEMENTATION_PLAN.md).