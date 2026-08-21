"""Custom APIRoute that commits the request session BEFORE the response is sent.

FastAPI finalises ``yield`` dependencies *after* the response has been
delivered, which means ``get_db``'s teardown commit happened after the client
could observe the response. That caused a real race: a booking was created, the
confirmation/cancellation link was returned, but a token lookup immediately
after could 404 because the insert was not yet committed.

This route handler commits (or rolls back) the request session between the
endpoint running and the response being returned, so every write is visible to
the client the moment the response arrives.
"""

from __future__ import annotations

from fastapi import Request, Response
from fastapi.routing import APIRoute


class CommitOnSuccessRoute(APIRoute):
    """APIRoute whose handler commits the request session on success."""

    def get_route_handler(self):  # type: ignore[no-untyped-def]
        original_handler = super().get_route_handler()

        async def commit_handler(request: Request) -> Response:
            session = getattr(request.state, "db_session", None)
            try:
                response = await original_handler(request)
            except Exception:
                if session is not None:
                    session.rollback()
                raise
            if session is not None:
                session.commit()
            return response

        return commit_handler
