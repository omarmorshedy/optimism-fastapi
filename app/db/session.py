"""Request-scoped database session dependency.

Commits on success, rolls back on exception (arc42 §5.2.2). Used by
repositories only; routers/services never touch the engine directly.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.engine import get_session_factory


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency yielding a session for the lifetime of a request.

    Commits on success, rolls back on exception (arc42 §5.2.2).
    """
    settings: Settings = request.app.state.settings
    session = get_session_factory(settings)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_db)]


def get_settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
