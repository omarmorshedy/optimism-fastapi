"""Business rules for resources and resource-types (API_SPEC §4.2-4.3)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import (
    DETAIL_RESOURCE_NOT_FOUND,
    conflict,
    not_found,
)
from app.domains.resources.repository import ResourceRepository, ResourceTypeRepository
from app.domains.resources.schemas import (
    ResourceCreate,
    ResourceRead,
    ResourceTypeCreate,
    ResourceTypeRead,
    ResourceTypeUpdate,
    ResourceUpdate,
)

DETAIL_DUPLICATE_NAME = "An item with that name already exists."
DETAIL_DELETE_BLOCKED = "Cannot delete a resource that has active bookings."
DETAIL_NO_SUCH_TYPE = "Resource type not found."


class ResourceTypeService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = ResourceTypeRepository(session)

    def list(self) -> list[ResourceTypeRead]:
        return [ResourceTypeRead.model_validate(t) for t in self.repo.list_all()]

    def get(self, type_id: int) -> ResourceTypeRead:
        obj = self.repo.get(type_id)
        if obj is None:
            raise not_found("No such resourceType")
        return ResourceTypeRead.model_validate(obj)

    def create(self, data: ResourceTypeCreate) -> ResourceTypeRead:
        name = data.name.strip()
        if self.repo.get_by_name(name) is not None:
            raise conflict(DETAIL_DUPLICATE_NAME)
        obj = self.repo.create(name=name)
        self.session.flush()
        return ResourceTypeRead.model_validate(obj)

    def update(self, type_id: int, data: ResourceTypeUpdate) -> ResourceTypeRead:
        obj = self.repo.get(type_id)
        if obj is None:
            raise not_found("No such resourceType")
        fields = data.model_dump(exclude_unset=True)
        if "name" in fields:
            name = str(fields["name"]).strip()
            existing = self.repo.get_by_name(name)
            if existing is not None and existing.id != type_id:
                raise conflict(DETAIL_DUPLICATE_NAME)
            fields["name"] = name
        self.repo.update(obj, **fields)
        self.session.flush()
        return ResourceTypeRead.model_validate(obj)

    def delete(self, type_id: int) -> None:
        obj = self.repo.get(type_id)
        if obj is None:
            raise not_found("No such resourceType")
        self.repo.nullify_resources(type_id)
        self.repo.delete(obj)
        self.session.flush()


class ResourceService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = ResourceRepository(session)
        self.type_repo = ResourceTypeRepository(session)

    def _validate_type(self, type_id: int | None) -> None:
        if type_id is not None and self.type_repo.get(type_id) is None:
            raise not_found(DETAIL_NO_SUCH_TYPE)

    def _unique_name(self, name: str, exclude_id: int | None = None) -> None:
        existing = self.repo.get_by_name(name)
        if existing is not None and existing.id != exclude_id:
            raise conflict(DETAIL_DUPLICATE_NAME)

    def list(self) -> list[ResourceRead]:
        return [ResourceRead.model_validate(r) for r in self.repo.list_all()]

    def get(self, resource_id: int) -> ResourceRead:
        obj = self.repo.get(resource_id)
        if obj is None:
            raise not_found(DETAIL_RESOURCE_NOT_FOUND)
        return ResourceRead.model_validate(obj)

    def create(self, data: ResourceCreate) -> ResourceRead:
        self._validate_type(data.resource_type_id)
        name = data.name.strip()
        self._unique_name(name)
        obj = self.repo.create(
            resource_type_id=data.resource_type_id,
            name=name,
            capacity=data.capacity,
        )
        self.session.flush()
        return ResourceRead.model_validate(obj)

    def update(self, resource_id: int, data: ResourceUpdate) -> ResourceRead:
        obj = self.repo.get(resource_id)
        if obj is None:
            raise not_found(DETAIL_RESOURCE_NOT_FOUND)
        fields = data.model_dump(exclude_unset=True)
        if "name" in fields:
            name = str(fields["name"]).strip()
            self._unique_name(name, exclude_id=resource_id)
            fields["name"] = name
        if "resourceTypeId" in fields:
            self._validate_type(fields["resource_type_id"])
        if fields:
            self.repo.update(obj, **fields)
            self.session.flush()
        return ResourceRead.model_validate(obj)

    def delete(self, resource_id: int) -> None:
        obj = self.repo.get(resource_id)
        if obj is None:
            raise not_found(DETAIL_RESOURCE_NOT_FOUND)
        if self.repo.count_active_bookings(resource_id) > 0:
            raise conflict(DETAIL_DELETE_BLOCKED)
        self.repo.delete(obj)
        self.session.flush()
