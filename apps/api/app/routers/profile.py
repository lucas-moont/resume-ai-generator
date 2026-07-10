"""GET /api/profile[, /versions[, /versions/{n}]] and POST /api/profile/revert (v2 ticket
01 -- "Perfil vivo como fonte de leitura").

Every route here goes through ``profile_resolution.resolve_active_profile`` for reads (DB
active version first, disk fallback when profile_versions is empty -- see that module's
docstring) instead of the v1 raw disk read this router used to do. ``/versions`` and
``/versions/{n}`` expose the append-only version history directly via ``profile_repo``;
``/revert`` never rewrites history -- it inserts a new version (source_kind="revert") whose
data copies the target version's.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session

from app.config import max_upload_bytes
from app.db.tables import ProfileVersion, SourceDocument
from app.domain.schemas import RevertProfileRequest
from app.repositories import profile_repo, source_document_repo
from app.routers.deps import get_session
from app.services.errors import http_error
from app.services.github_client import fetch_user_repos
from app.services.ingestion.ingest_json import JsonIngestionError, ingest_json
from app.services.ingestion.storage import compute_sha256, store_upload
from app.services.profile_resolution import ProfileValidationError, resolve_active_profile

router = APIRouter()

_MEDIA_TYPE_BY_EXT = {"json": "json", "md": "md", "markdown": "md", "pdf": "pdf"}


def _media_type_from_filename(filename: str | None) -> str | None:
    if not filename or "." not in filename:
        return None
    ext = filename.rsplit(".", 1)[-1].lower()
    return _MEDIA_TYPE_BY_EXT.get(ext)


def _upload_response(row: SourceDocument) -> dict:
    return {
        "documentId": row.id,
        "status": row.status,
        "extractedPreview": json.loads(row.extracted_json) if row.extracted_json else None,
        "error": row.error,
    }


def _document_list_dict(row: SourceDocument) -> dict:
    return {
        "documentId": row.id,
        "filename": row.filename,
        "mediaType": row.media_type,
        "status": row.status,
        "sizeBytes": row.size_bytes,
        "createdAt": row.created_at.isoformat(),
        "error": row.error,
    }


def _version_dict(row: ProfileVersion) -> dict:
    return {
        "version": row.version,
        "sourceKind": row.source_kind,
        "changeSummary": row.change_summary,
        "createdAt": row.created_at.isoformat(),
    }


@router.get("/api/profile")
async def get_profile(session: Session = Depends(get_session)):
    try:
        resolved = resolve_active_profile(session)
    except FileNotFoundError as e:
        raise http_error(404, str(e)) from e
    except ProfileValidationError as e:
        raise http_error(400, str(e)) from e
    return resolved.profile.model_dump()


@router.get("/api/profile/versions")
async def list_profile_versions(session: Session = Depends(get_session)):
    rows = profile_repo.list_versions(session)
    return {"versions": [_version_dict(r) for r in rows]}


@router.get("/api/profile/versions/{n}")
async def get_profile_version(n: int, session: Session = Depends(get_session)):
    row = profile_repo.get_by_version(session, n)
    if row is None:
        raise http_error(404, f"Profile version {n} not found")
    return {**_version_dict(row), "data": json.loads(row.data)}


@router.post("/api/profile/revert")
async def revert_profile(body: RevertProfileRequest, session: Session = Depends(get_session)):
    target = profile_repo.get_by_version(session, body.toVersion)
    if target is None:
        raise http_error(404, f"Profile version {body.toVersion} not found")

    new_row = profile_repo.insert_version(
        session,
        data=target.data,
        source_kind="revert",
        change_summary=f"Reverted to version {body.toVersion}",
    )
    session.commit()
    session.refresh(new_row)
    return _version_dict(new_row)


@router.post("/api/profile/documents", status_code=202)
async def upload_document(
    file: UploadFile = File(...), session: Session = Depends(get_session)
):
    """Accepts a `.json`/`.md`/`.pdf` Source Document upload (CONTEXT.md: Source Document,
    Ingestion). `.json` is validated deterministically (no LLM) -- a malformed or
    schema-invalid file is a request error (422) and no row is persisted for it, same
    treatment as the >max-size case (413): both are rejected before they ever become a Source
    Document. `.md`/`.pdf` ingestion (LLM-based) is added in a later slice of this ticket;
    for now those extensions are recognized but not yet processed.
    """
    content = await file.read()
    limit = max_upload_bytes()
    if len(content) > limit:
        raise http_error(413, f"File exceeds the {limit} byte upload limit")

    media_type = _media_type_from_filename(file.filename)
    if media_type is None:
        raise http_error(415, "Unsupported file type -- upload a .json, .md, or .pdf file")

    sha256 = compute_sha256(content)
    existing = source_document_repo.get_by_sha256(session, sha256)
    if existing is not None:
        return _upload_response(existing)

    if media_type != "json":
        raise http_error(415, f"{media_type} uploads are not supported yet")

    try:
        resume = ingest_json(content)
    except JsonIngestionError as e:
        raise http_error(422, str(e)) from e

    stored_path = store_upload(content, sha256=sha256, ext="json")
    row = source_document_repo.insert(
        session,
        filename=file.filename or "upload.json",
        media_type="json",
        sha256=sha256,
        size_bytes=len(content),
        stored_path=stored_path,
        status="extracted",
        extracted_json=resume.model_dump_json(),
    )
    session.commit()
    return _upload_response(row)


@router.get("/api/profile/documents")
async def list_documents(session: Session = Depends(get_session)):
    rows = source_document_repo.list_all(session)
    return {"documents": [_document_list_dict(r) for r in rows]}


@router.get("/api/github/repos")
async def github_repos(username: str | None = None, session: Session = Depends(get_session)):
    try:
        resolved = resolve_active_profile(session)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Profile JSON not found — see README (data/profile/resume.json).",
        ) from None
    except ProfileValidationError as e:
        raise http_error(400, str(e)) from e
    user = username or resolved.profile.githubUsername
    if not user:
        return {"repos": [], "warning": "No githubUsername in profile and no username query"}
    repos, warn = await fetch_user_repos(user)
    return {
        "repos": [r.model_dump() for r in repos],
        "warning": warn,
    }
