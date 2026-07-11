"""GET/PUT /api/settings/providers, GET/PUT/DELETE /api/settings/keys (v3 ticket 03).

Thin HTTP-shape adapter -- all the actual logic (provider entry assembly, which app_settings
key a write targets, key-source resolution) lives in app/services/settings_service.py.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel

from app.services import settings_service
from app.services.errors import http_error

router = APIRouter()

ProviderModeIn = Literal["auto", "claude", "gemini", "ollama"]
# Derived from settings_service.MANAGED_SECRET_NAMES (the single source of truth) rather than
# hand-duplicated here -- a hand-synced second Literal could let a future key addition 200 on
# PUT/DELETE while still missing from GET /api/settings/keys. `Literal[a_tuple]` flattens the
# tuple into individual literal members (see PEP 586), same as `Literal["A", "B", "C"]`.
SecretNameIn = Literal[settings_service.MANAGED_SECRET_NAMES]


class ProvidersUpdateRequest(BaseModel):
    provider: ProviderModeIn
    defaultModel: str | None = None


class KeyUpsertRequest(BaseModel):
    name: SecretNameIn
    value: str


@router.get("/api/settings/providers")
async def get_providers() -> dict:
    return await settings_service.get_providers_settings()


@router.put("/api/settings/providers")
async def put_providers(body: ProvidersUpdateRequest) -> dict:
    settings_service.update_providers_settings(body.provider, body.defaultModel)
    return await settings_service.get_providers_settings()


@router.get("/api/settings/keys")
async def get_keys() -> dict:
    return settings_service.get_keys_settings()


@router.put("/api/settings/keys")
async def put_key(body: KeyUpsertRequest) -> dict:
    try:
        return settings_service.upsert_key(body.name, body.value)
    except ValueError as e:
        raise http_error(422, str(e)) from e


@router.delete("/api/settings/keys/{name}", status_code=204)
async def delete_key(name: SecretNameIn) -> Response:
    settings_service.delete_key(name)
    return Response(status_code=204)
