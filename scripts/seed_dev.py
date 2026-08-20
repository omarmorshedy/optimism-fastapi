"""Development seed data — mirrors the legacy seeds (rooms, laser cutters, hot
desks and their windows) so the replacement works straight out of the gate.

Usage:
    uv run python scripts/seed_dev.py
Run against the configured DATABASE_URL (defaults to the .env / local postgres).
"""

from __future__ import annotations

import datetime as dt

# Import every model so all relationships are registered (like alembic env.py).
from app.models import (  # noqa: F401
    admin_session,
    audit_event,
    availability_exception,
    availability_window,
    booking,
    email_outbox,
    resource,
    resource_type,
)
from app.core.config import get_settings
from app.db.engine import session_scope
from app.models.availability_window import AvailabilityWindow
from app.models.resource import Resource
from app.models.resource_type import ResourceType

# Legacy bitmask day=31 -> Mon..Fri (weekday 1..5). The legacy seeds contained
# overlapping windows (AM, PM and full-day) for the same resource/weekday; v1
# forbids overlaps (decision #4), so each maps to its non-overlapping
# equivalent (the full-day window).
WINDOWS_BY_RESOURCE: dict[str, list[tuple[int, str, str]]] = {
    "Sophia": [(1, "09:30", "17:30")],
    "Gerald": [(1, "09:30", "17:30")],
    "Hot Desk": [(1, "09:30", "17:30")],
    "Dinky": [
        (1, "09:30", "10:00"),
        (1, "10:00", "10:30"),
        (1, "10:30", "11:00"),
        (1, "11:00", "11:30"),
        (1, "11:30", "12:00"),
        (1, "12:00", "12:30"),
        (1, "12:30", "13:00"),
        (1, "13:00", "13:30"),
        (1, "13:30", "14:00"),
        (1, "14:00", "14:30"),
        (1, "14:30", "15:00"),
        (1, "15:00", "15:30"),
        (1, "15:30", "16:00"),
        (1, "16:00", "16:30"),
        (1, "16:30", "17:00"),
        (1, "17:00", "17:30"),
    ],
}

RESOURCES: list[tuple[str, int, str]] = [
    ("Dinky", 1, "room"),
    ("Sophia", 1, "laser-cutter"),
    ("Gerald", 1, "laser-cutter"),
    ("Events Room", 1, "room"),
    ("Hot Desk", 10, "hot-desk"),
]


def main() -> None:
    settings = get_settings()
    with session_scope(settings) as session:
        # Clear existing seedable data (keeps audit/sessions).
        session.query(AvailabilityWindow).delete()
        session.query(Resource).delete()
        session.query(ResourceType).delete()

        types = {
            name: ResourceType(name=name)
            for name in ("room", "laser-cutter", "hot-desk")
        }
        session.add_all(types.values())
        session.flush()

        resources: list[Resource] = []
        for name, capacity, type_name in RESOURCES:
            resource = Resource(
                name=name, capacity=capacity, resource_type_id=types[type_name].id
            )
            session.add(resource)
            resources.append(resource)
        session.flush()

        for resource in resources:
            for weekday, starts, ends in WINDOWS_BY_RESOURCE.get(resource.name, []):
                start_h, start_m = map(int, starts.split(":"))
                end_h, end_m = map(int, ends.split(":"))
                session.add(
                    AvailabilityWindow(
                        resource_id=resource.id,
                        weekday=weekday,
                        starts=dt.time(start_h, start_m, tzinfo=dt.timezone.utc),
                        ends=dt.time(end_h, end_m, tzinfo=dt.timezone.utc),
                        name=resource.name,
                    )
                )
        session.commit()
        print(f"Seeded {len(types)} resource types and {len(resources)} resources.")


if __name__ == "__main__":
    main()
