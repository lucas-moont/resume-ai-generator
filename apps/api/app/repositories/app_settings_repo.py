"""Repository for app_settings (v3 ticket 01) -- non-sensitive runtime preferences (provider
choice, default model). Values are stored JSON-encoded so any JSON-serializable preference
(string, number, bool, list, dict) round-trips without a schema migration.

Callers own the transaction (commit/rollback) -- same convention as profile_repo/chat_repo.

IMPORTANT for callers outside tests (e.g. v3 ticket 03's settings endpoints): do NOT call
``set``/``delete`` here directly from a router. Go through ``app.config.set_app_setting`` /
``delete_app_setting`` instead -- cache invalidation for ``get_runtime_config()`` lives there,
and writing straight to this repo would leave the process serving a stale cached value.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from app.db.tables import AppSettings


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get(session: Session, key: str) -> Any | None:
    row = session.get(AppSettings, key)
    if row is None:
        return None
    return json.loads(row.value)


def get_all(session: Session) -> dict[str, Any]:
    rows = session.exec(select(AppSettings)).all()
    return {row.key: json.loads(row.value) for row in rows}


def set(session: Session, key: str, value: Any) -> AppSettings:
    encoded = json.dumps(value)
    row = session.get(AppSettings, key)
    if row is None:
        row = AppSettings(key=key, value=encoded)
    else:
        row.value = encoded
        row.updated_at = _utcnow()
    session.add(row)
    session.flush()
    return row


def delete(session: Session, key: str) -> None:
    row = session.get(AppSettings, key)
    if row is not None:
        session.delete(row)
        session.flush()
