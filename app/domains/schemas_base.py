"""Shared Pydantic base with camelCase JSON aliases (legacy-compatible API)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model: python names are snake_case, JSON uses camelCase aliases."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class CamelReadModel(CamelModel):
    """Camel model that can also be validated from ORM attributes."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid", from_attributes=True
    )
