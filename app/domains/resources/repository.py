"""Repository layer for resources and resource-types (isolated DB access)."""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.resource import Resource
from app.models.resource_type import ResourceType


class ResourceTypeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_all(self) -> list[ResourceType]:
        stmt = select(ResourceType).order_by(ResourceType.id)
        return list(self.session.scalars(stmt))

    def get(self, type_id: int) -> ResourceType | None:
        return self.session.get(ResourceType, type_id)

    def get_by_name(self, name: str) -> ResourceType | None:
        stmt = select(ResourceType).where(ResourceType.name == name)
        return self.session.scalar(stmt)

    def create(self, name: str) -> ResourceType:
        obj = ResourceType(name=name)
        self.session.add(obj)
        return obj

    def update(self, obj: ResourceType, **fields: object) -> ResourceType:
        for key, value in fields.items():
            setattr(obj, key, value)
        return obj

    def delete(self, obj: ResourceType) -> None:
        self.session.delete(obj)

    def nullify_resources(self, type_id: int) -> None:
        """Legacy resource-type deletion semantics: null resourceTypeId first (§11.5)."""
        self.session.execute(
            update(Resource)
            .where(Resource.resource_type_id == type_id)
            .values(resource_type_id=None)
        )


class ResourceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_all(self) -> list[Resource]:
        stmt = select(Resource).order_by(Resource.id)
        return list(self.session.scalars(stmt))

    def get(self, resource_id: int) -> Resource | None:
        return self.session.get(Resource, resource_id)

    def get_by_name(self, name: str) -> Resource | None:
        stmt = select(Resource).where(Resource.name == name)
        return self.session.scalar(stmt)

    def create(self, *, resource_type_id: int | None, name: str, capacity: int) -> Resource:
        obj = Resource(resource_type_id=resource_type_id, name=name, capacity=capacity)
        self.session.add(obj)
        return obj

    def update(self, obj: Resource, **fields: object) -> Resource:
        for key, value in fields.items():
            setattr(obj, key, value)
        return obj

    def delete(self, obj: Resource) -> None:
        self.session.delete(obj)

    def count_active_bookings(self, resource_id: int) -> int:
        stmt = (
            select(func.count(Booking.id))
            .where(Booking.resource_id == resource_id)
            .where(Booking.cancelled.is_(False))
            .where(Booking.deleted_at.is_(None))
        )
        return int(self.session.scalar(stmt) or 0)
