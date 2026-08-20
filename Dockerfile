# ---- Build stage ----
FROM python:3.12-slim AS builder
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# uv for reproducible dependency resolution (uv.lock).
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/
ENV UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ---- Runtime stage ----
FROM python:3.12-slim AS runtime
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    HOME=/tmp \
    PATH="/app/.venv/bin:$PATH"
# Non-root user (plan §2 / arc42 §7.2).
RUN addgroup --system app && adduser --system --ingroup app app
COPY --from=builder /app/.venv /app/.venv
COPY --chown=app:app . /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"]
ENTRYPOINT ["/app/docker-entrypoint.sh"]
