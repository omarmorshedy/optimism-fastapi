"""API router for resources and resource-types (API_SPEC §3.1-3.2, §4.2-4.3)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Response, status

from app.core.route import CommitOnSuccessRoute
from app.db.session import SessionDep
from app.domains.admin.audit import record_audit
from app.domains.admin.auth import require_admin, require_csrf
from app.domains.resources.schemas import (
    ResourceCreate,
    ResourceRead,
    ResourceTypeCreate,
    ResourceTypeRead,
    ResourceTypeUpdate,
    ResourceUpdate,
)
from app.domains.resources.service import ResourceService, ResourceTypeService
from app.domains.windows.schemas import AvailabilityWindowRead, WindowReplacementItem
from app.domains.windows.service import AvailabilityWindowService

resources_router = APIRouter(
    prefix="/resources", tags=["resources"], route_class=CommitOnSuccessRoute
)
resource_types_router = APIRouter(
    prefix="/resource-types", tags=["resource-types"], route_class=CommitOnSuccessRoute
)

ResourceId = Annotated[int, Path(ge=0)]
TypeId = Annotated[int, Path(ge=0)]


# --- resources ---------------------------------------------------------------


@resources_router.get("", response_model=list[ResourceRead])
def list_resources(session: SessionDep) -> list[ResourceRead]:
    return ResourceService(session).list()


@resources_router.post(
    "",
    response_model=ResourceRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_admin, require_csrf],
)
def create_resource(payload: ResourceCreate, session: SessionDep) -> ResourceRead:
    obj = ResourceService(session).create(payload)
    record_audit(session, "resource.create", resource_id=obj.id)
    return obj


@resources_router.get("/{resource_id}", response_model=ResourceRead)
def get_resource(resource_id: ResourceId, session: SessionDep) -> ResourceRead:
    return ResourceService(session).get(resource_id)


@resources_router.put(
    "/{resource_id}",
    response_model=ResourceRead,
    dependencies=[require_admin, require_csrf],
)
def update_resource(
    payload: ResourceUpdate,
    session: SessionDep,
    resource_id: ResourceId,
) -> ResourceRead:
    obj = ResourceService(session).update(resource_id, payload)
    record_audit(session, "resource.update", resource_id=obj.id)
    return obj


@resources_router.delete(
    "/{resource_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_admin, require_csrf],
)
def delete_resource(session: SessionDep, resource_id: ResourceId) -> Response:
    ResourceService(session).delete(resource_id)
    record_audit(session, "resource.delete", resource_id=resource_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- resource windows --------------------------------------------------------


@resources_router.get(
    "/{resource_id}/windows",
    response_model=list[AvailabilityWindowRead],
    dependencies=[require_admin],
)
def list_resource_windows(
    session: SessionDep, resource_id: ResourceId
) -> list[AvailabilityWindowRead]:
    return AvailabilityWindowService(session).list_for_resource(resource_id)


@resources_router.put(
    "/{resource_id}/windows",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_admin, require_csrf],
)
def replace_resource_windows(
    payload: list[WindowReplacementItem],
    session: SessionDep,
    resource_id: ResourceId,
) -> Response:
    AvailabilityWindowService(session).replace_for_resource(resource_id, payload)
    record_audit(session, "resource.windows.replace", resource_id=resource_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- resource types ----------------------------------------------------------


@resource_types_router.get("", response_model=list[ResourceTypeRead])
def list_resource_types(session: SessionDep) -> list[ResourceTypeRead]:
    return ResourceTypeService(session).list()


@resource_types_router.post(
    "",
    response_model=ResourceTypeRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_admin, require_csrf],
)
def create_resource_type(payload: ResourceTypeCreate, session: SessionDep) -> ResourceTypeRead:
    obj = ResourceTypeService(session).create(payload)
    record_audit(session, "resource_type.create", resource_id=obj.id)
    return obj


@resource_types_router.get("/{type_id}", response_model=ResourceTypeRead)
def get_resource_type(type_id: TypeId, session: SessionDep) -> ResourceTypeRead:
    return ResourceTypeService(session).get(type_id)


@resource_types_router.put(
    "/{type_id}",
    response_model=ResourceTypeRead,
    dependencies=[require_admin, require_csrf],
)
def update_resource_type(
    payload: ResourceTypeUpdate,
    session: SessionDep,
    type_id: TypeId,
) -> ResourceTypeRead:
    obj = ResourceTypeService(session).update(type_id, payload)
    record_audit(session, "resource_type.update", resource_id=obj.id)
    return obj


@resource_types_router.delete(
    "/{type_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_admin, require_csrf],
)
def delete_resource_type(session: SessionDep, type_id: TypeId) -> Response:
    ResourceTypeService(session).delete(type_id)
    record_audit(session, "resource_type.delete", resource_id=type_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
