"""Filesystem storage for uploaded Source Document bytes (v2 ticket 03).

Files land at ``<uploads_dir>/<sha256>.<ext>`` -- the sha256 IS the dedup key (see
app/repositories/source_document_repo.py::get_by_sha256), so the same bytes uploaded twice
always resolve to the same path. Callers dedup at the DB layer (check
``get_by_sha256`` first) before ever calling ``store_upload`` -- see
app/services/ingestion/pipeline.py.
"""

from __future__ import annotations

import hashlib

from app import config as config_module


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def store_upload(data: bytes, *, sha256: str, ext: str) -> str:
    """Writes ``data`` to ``<uploads_dir>/<sha256>.<ext>`` (creating the directory if it
    doesn't exist yet) and returns the path as a string -- what ``source_documents.stored_path``
    persists. ``config_module.resolve_uploads_dir()`` is read module-qualified at call time so
    tests can monkeypatch ``DATA_UPLOADS_DIR`` per-test (see tests/conftest.py)."""
    uploads_dir = config_module.resolve_uploads_dir()
    uploads_dir.mkdir(parents=True, exist_ok=True)
    path = uploads_dir / f"{sha256}.{ext}"
    path.write_bytes(data)
    return str(path)
