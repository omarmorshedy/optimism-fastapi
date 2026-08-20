"""Pydantic schemas for admin auth (API_SPEC §4.1)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str


class LoginResponse(BaseModel):
    message: str = "Logged in."
