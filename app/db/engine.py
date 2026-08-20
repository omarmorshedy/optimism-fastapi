"""SQLAlchemy engine and session factory (sync, psycopg3; ADR-002/ADR-003).

Engines and session factories are cached by database URL (not by Settings
object identity) so equivalent Settings instances share one pool.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.metrics import DB_POOL_MAX, DB_POOL_USAGE

# Make the engine's connection pool metrics observable (ADR-012).
_engine_under_metrics: Engine | None = None


def _publish_pool_metrics(engine: Engine) -> None:
    global _engine_under_metrics
    if _engine_under_metrics is engine:
        return
    _engine_under_metrics = engine
    pool = engine.pool
    # Only QueuePool-style pools expose checkedout(); singleton/static pools
    # (SQLite test convenience) report 0 usage.
    if not hasattr(pool, "checkedout"):
        DB_POOL_USAGE.set(0)
        return

    @event.listens_for(pool, "checkout")
    def _on_checkout(_dbapi_conn: object, _rec: object, _proxy: object) -> None:
        DB_POOL_USAGE.set(pool.checkedout())

    @event.listens_for(pool, "checkin")
    def _on_checkin(_dbapi_conn: object, _rec: object) -> None:
        DB_POOL_USAGE.set(pool.checkedout())


@lru_cache
def _get_engine_for_url(url: str) -> Engine:
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        # Share one connection across threads (StaticPool) so :memory: databases
        # are visible to every request thread (test convenience, ADR-003 note).
        from sqlalchemy.pool import StaticPool

        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    _publish_pool_metrics(engine)
    pool_size = getattr(engine.pool, "size", None)
    if callable(pool_size):
        pool_size = pool_size()
    DB_POOL_MAX.set(int(pool_size or 10))
    return engine


def get_engine(settings: Settings | None = None) -> Engine:
    """Return the (cached) engine for the given typed settings."""
    settings = settings or get_settings()
    return _get_engine_for_url(settings.database_url)


@lru_cache
def _get_session_factory_for_url(url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=_get_engine_for_url(url), autoflush=False, expire_on_commit=False)


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    settings = settings or get_settings()
    return _get_session_factory_for_url(settings.database_url)


@contextmanager
def session_scope(settings: Settings | None = None) -> Iterator[Session]:
    """Yield a session and close it afterwards (for worker threads / scripts)."""
    factory = get_session_factory(settings)
    session = factory()
    try:
        yield session
    finally:
        session.close()
