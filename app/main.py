"""Application factory, lifespan, middleware and top-level routers.

Single FastAPI modular monolith (ADR-001) serving ``/api/v1`` JSON and the
server-rendered web UI, with the email outbox worker running in-process
(ADR-010, TD-06).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import ACCESS_LOG_EVENT, configure_logging, get_logger
from app.core.metrics import HTTP_REQUEST_DURATION, HTTP_REQUESTS
from app.core.rate_limit import RateLimiter
from app.db.engine import get_engine
from app.domains.admin.router import admin_router
from app.domains.bookings.router import bookings_router
from app.domains.bookings.worker import EmailWorker
from app.domains.calendar.router import calendar_router
from app.domains.resources.router import resource_types_router, resources_router
from app.domains.windows.router import exceptions_router, windows_router
from app.integrations.email.provider import NullEmailProvider, SmtpEmailProvider

logger = get_logger("optimism.main")

API_PREFIX = "/api/v1"


def run_migrations(settings: Settings) -> None:
    """Run ``alembic upgrade head`` (AUTO_MIGRATE; dev/staging per arc42 §7.5)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "app/migrations")
    command.upgrade(cfg, "head")
    logger.info("migrations_applied")


def run_migrations_once(settings: Settings) -> None:
    """Run migrations exactly once per cluster.

    With multiple gunicorn workers each running the lifespan, a PostgreSQL
    advisory lock serialises the upgrade; workers that lose the race skip it
    (the entrypoint already migrated before traffic in containers). On SQLite
    (single-process dev) it just runs.
    """
    engine = get_engine(settings)
    if engine.dialect.name == "postgresql":
        from sqlalchemy import text

        with engine.connect() as conn:
            locked = conn.execute(
                text("SELECT pg_try_advisory_lock(hashtextextended('optimism-migrations', 0))")
            ).scalar()
            if not locked:
                logger.info("migrations_skipped_lock_held")
                return
            try:
                run_migrations(settings)
            finally:
                conn.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended('optimism-migrations', 0))")
                )
    else:
        run_migrations(settings)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    if settings.auto_migrate:
        try:
            run_migrations_once(settings)
        except Exception:
            logger.exception("migration_failed")
            raise

    worker: EmailWorker | None = None
    if settings.email_worker_enabled:
        from app.integrations.email.provider import EmailProvider

        provider: EmailProvider
        if settings.smtp_host and settings.smtp_host != "localhost":
            provider = SmtpEmailProvider(settings)
        else:
            provider = NullEmailProvider()
        worker = EmailWorker(settings, provider)
        worker.start()
        app.state.email_worker = worker
        logger.info("email_worker_started", provider=type(provider).__name__)

    yield

    if worker is not None:
        worker.stop()
        logger.info("email_worker_stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="DoES Liverpool resource-booking system — FastAPI replacement (v1)",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.state.settings = settings
    app.state.rate_limiter = RateLimiter()

    register_exception_handlers(app)
    app.add_middleware(AccessLogMiddleware)  # type: ignore[arg-type]
    app.add_middleware(RequestIdMiddleware)  # type: ignore[arg-type]

    # --- API routers ---
    app.include_router(resources_router, prefix=API_PREFIX)
    app.include_router(resource_types_router, prefix=API_PREFIX)
    app.include_router(windows_router, prefix=API_PREFIX)
    app.include_router(exceptions_router, prefix=API_PREFIX)
    app.include_router(bookings_router, prefix=API_PREFIX)
    app.include_router(calendar_router, prefix=API_PREFIX)
    app.include_router(admin_router, prefix=API_PREFIX)

    # --- web UI (server-rendered; public + admin) ---
    from fastapi.staticfiles import StaticFiles

    from app.web.router import web_router

    static_dir = Path(__file__).parent / "web" / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(web_router)

    # --- observability ---
    register_observability(app)
    return app


def register_observability(app: FastAPI) -> None:
    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        """Liveness: the process is up (always 200)."""
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz(request: Request) -> Response:
        """Readiness: DB reachable, migrations applied, email worker alive."""
        settings: Settings = request.app.state.settings
        problems: list[str] = []
        try:
            engine = get_engine(settings)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            problems.append("database unreachable")
        try:
            engine = get_engine(settings)
            with engine.connect() as conn:
                has_migrations = conn.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
            if has_migrations is None:
                problems.append("migrations not applied")
        except Exception:
            problems.append("migrations not applied")
        worker: EmailWorker | None = getattr(request.app.state, "email_worker", None)
        if settings.email_worker_enabled and (worker is None or not worker.is_alive()):
            problems.append("email worker not alive")
        if problems:
            return JSONResponse(
                status_code=503, content={"status": "not ready", "problems": problems}
            )
        return JSONResponse(status_code=200, content={"status": "ready"})

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        """Prometheus text exposition (arc42 §8.2.2)."""
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# --- middleware --------------------------------------------------------------


class RequestIdMiddleware:
    """Attach a correlation/request id to every request (logs + problem bodies)."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex[:16]
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_wrapper(message):  # type: ignore[no-untyped-def]
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"X-Request-Id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")


class AccessLogMiddleware:
    """Structured access log + Prometheus metrics for every HTTP request."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.logger = structlog.get_logger("optimism.http")

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        request = Request(scope, receive)
        request_id = scope["state"].get("request_id")
        status_code = 500

        async def send_wrapper(message):  # type: ignore[no-untyped-def]
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
                # Propagate pagination total counts (admin lists, API_SPEC §1.6).
                total = getattr(request.state, "total_count", None)
                if total is not None:
                    headers = list(message.get("headers", []))
                    headers.append((b"X-Total-Count", str(total).encode("ascii")))
                    message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            path = scope.get("path", "")
            method = scope.get("method", "")
            HTTP_REQUESTS.labels(method=method, path=path, status=str(status_code)).inc()
            HTTP_REQUEST_DURATION.labels(method=method, path=path).observe(duration_ms / 1000)
            self.logger.info(
                ACCESS_LOG_EVENT,
                request_id=request_id,
                path=path,
                method=method,
                status=status_code,
                duration_ms=round(duration_ms, 2),
            )


app = create_app()
