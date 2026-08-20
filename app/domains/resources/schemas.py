"""Pydantic schemas for resources and resource-types (API_SPEC §2.1, §4.2-4.3)."""

from __future__ import annotations

from pydantic import Field, field_validator

from app.core.exceptions import validation_error
from app.domains.schemas_base import CamelModel, CamelReadModel


def _non_blank_name(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise validation_error("Name must not be blank.")
    return stripped


class ResourceBase(CamelModel):
    resource_type_id: int | None = None
    name: str = Field(max_length=255)
    capacity: int = Field(gt=0)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _non_blank_name(v)


class ResourceCreate(ResourceBase):
    pass


class ResourceUpdate(CamelModel):
    resource_type_id: int | None = None
    name: str | None = Field(default=None, max_length=255)
    capacity: int | None = Field(default=None, gt=0)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return _non_blank_name(v) if v is not None else None


class ResourceRead(ResourceBase, CamelReadModel):
    id: int


class ResourceTypeBase(CamelModel):
    name: str = Field(max_length=255)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _non_blank_name(v)


class ResourceTypeCreate(ResourceTypeBase):
    pass


class ResourceTypeUpdate(CamelModel):
    name: str | None = Field(default=None, max_length=255)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return _non_blank_name(v) if v is not None else None


class ResourceTypeRead(ResourceTypeBase, CamelReadModel):
    id: int
