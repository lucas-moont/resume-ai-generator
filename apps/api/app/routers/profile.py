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
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from pydantic import BaseModel
from sqlmodel import Session

from app.config import max_upload_bytes
from app.db.tables import ProfileVersion, SourceDocument
from app.domain.profile_patch import PatchOp, PatchResult, PatchValidationFailed, apply_patch
from app.domain.schemas import RevertProfileRequest
from app.repositories import profile_repo, source_document_repo
from app.routers.deps import get_session, resolve_requested_model
from app.services.errors import http_error
from app.services.github_client import fetch_user_repos
from app.services.ingestion.ingest_json import JsonIngestionError, ingest_json
from app.services.ingestion.ingest_markdown import ingest_markdown
from app.services.ingestion.ingest_pdf import ingest_pdf
from app.services.ingestion.merge_service import propose_merge, resolve_profile_for_merge
from app.services.ingestion.storage import compute_sha256, store_upload
from app.services.profile_resolution import (
    ProfileValidationError,
    ResolvedProfile,
    resolve_active_profile,
)
from app.services.secret_redaction import redact_secrets

router = APIRouter()


class ApplyDocumentRequest(BaseModel):
    ops: list[int] | None = None


class PatchProfileRequest(BaseModel):
    ops: list[PatchOp]


def _resolve_active_profile_or_error(session: Session) -> ResolvedProfile:
    """Shared by this router's two READ-ONLY consumers of "the active profile" --
    ``GET /api/profile`` and ``GET /api/github/repos`` -- extracted from two near-identical
    ``try/except FileNotFoundError/ProfileValidationError`` blocks (ticket 01 review) that had
    drifted into different styles (one used ``http_error``, the other a bare
    ``HTTPException`` with a custom message).

    NOT used by the write paths this ticket (04) adds (``PATCH /api/profile``,
    ``POST .../{id}/apply``): those call ``resolve_profile_for_merge`` instead
    (``services/ingestion/merge_service.py``), which additionally falls back to a blank
    ``ProfileMaster`` when neither a DB version nor a disk profile exists yet (bootstrapping a
    user's very first manual edit or upload) -- a fallback ``GET /api/profile`` deliberately
    does NOT get, since serving a fabricated blank profile as if it were real data would be
    wrong for a read.
    """
    try:
        return resolve_active_profile(session)
    except FileNotFoundError as e:
        raise http_error(404, str(e)) from e
    except ProfileValidationError as e:
        raise http_error(400, str(e)) from e


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
        "proposedPatch": json.loads(row.proposed_patch) if row.proposed_patch else None,
        "diffSummary": json.loads(row.diff_summary) if row.diff_summary else None,
        "extractedPreview": json.loads(row.extracted_json) if row.extracted_json else None,
        "error": row.error,
    }


async def _propose_merge_or_fail(
    session: Session, row: SourceDocument, resume, model_override: str | None
) -> SourceDocument:
    """Runs the Incremental Merge pipeline (``services/ingestion/merge_service.py``) for a
    just-extracted Source Document, for ALL THREE formats -- unlike ingestion (json is
    LLM-free, md/pdf are not), Adjudication is a separate call gated purely by whether the
    Deterministic Diff found anything new or divergent. Any failure here (a broken active
    profile, an unreachable LLM) marks the document 'failed' with an actionable, redacted
    message rather than ever surfacing as a 500 -- the same non-fatal treatment ticket 03
    established for extraction failures; the file and its ``extractedPreview`` are already
    safely persisted by the time this runs.
    """
    try:
        profile = resolve_profile_for_merge(session)
        proposal = await propose_merge(profile, resume, model=model_override)
    except Exception as e:
        row = source_document_repo.mark_failed(
            session, row, error=redact_secrets(f"Could not build a merge proposal: {e}")
        )
        session.commit()
        return row

    row = source_document_repo.mark_proposed(
        session,
        row,
        proposed_patch=json.dumps([op.model_dump() for op in proposal.ops]),
        diff_summary=json.dumps(proposal.diff_summary),
    )
    session.commit()
    return row


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


def _persist_patch_result(
    session: Session,
    result: PatchResult,
    *,
    source_kind: str,
    change_summary: str,
    source_document_id: int | None = None,
    skipped: int | None = None,
) -> dict:
    """Shared by ``PATCH /api/profile`` and ``POST .../{id}/apply``: appends the new Profile
    Version a Patch Validator result produces and returns the ``{profileVersion, applied,
    skipped}`` shape both endpoints respond with. ``skipped`` overrides the plain
    ``len(result.skipped)`` count -- ``apply_source_document`` uses this to fold in ops a
    ``{ops: [indices]}`` subset excluded before the Patch Validator ever saw them (see its own
    docstring), so ``applied + skipped`` always equals the number of ops in the proposal it
    started from, not just the ones actually submitted.
    """
    new_version = profile_repo.insert_version(
        session,
        data=result.profile.model_dump_json(),
        source_kind=source_kind,
        patch=json.dumps([op.model_dump() for op in result.applied]),
        source_document_id=source_document_id,
        change_summary=change_summary,
    )
    session.commit()
    session.refresh(new_version)
    return {
        "profileVersion": new_version.version,
        "applied": len(result.applied),
        "skipped": len(result.skipped) if skipped is None else skipped,
    }


@router.get("/api/profile")
async def get_profile(session: Session = Depends(get_session)):
    resolved = _resolve_active_profile_or_error(session)
    return resolved.profile.model_dump()


@router.patch("/api/profile")
async def patch_profile(body: PatchProfileRequest, session: Session = Depends(get_session)):
    """Manual/direct profile edit (docs/v2-living-profile.md item 5): the same Patch Validator
    every other write path goes through, with ``source_kind="manual"`` (so, unlike an upload,
    a ``remove`` op is allowed -- CONTEXT.md: Upload-never-removes only restricts uploads).
    """
    try:
        profile = resolve_profile_for_merge(session)
    except ProfileValidationError as e:
        raise http_error(400, str(e)) from e
    try:
        result = apply_patch(profile, body.ops, source_kind="manual")
    except PatchValidationFailed as e:
        raise http_error(422, f"Patch produced an invalid profile: {e}") from e

    return _persist_patch_result(
        session,
        result,
        source_kind="manual",
        change_summary=f"Manual edit: {len(result.applied)} change(s)",
    )


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
    file: UploadFile = File(...),
    model: str | None = Form(None),
    session: Session = Depends(get_session),
):
    """Accepts a `.json`/`.md`/`.pdf` Source Document upload (CONTEXT.md: Source Document,
    Ingestion). `.json` is validated deterministically (no LLM) -- a malformed or
    schema-invalid file is a request error (422) and no row is persisted for it, same
    treatment as the >max-size case (413): both are rejected before they ever become a Source
    Document. `.md`/`.pdf` go through LLM extraction instead (``model`` optionally overrides
    the configured model, same convention as /api/generate and /api/chat): the file is
    persisted and the row inserted as `status='stored'` FIRST, since LLM extraction can fail
    for reasons that have nothing to do with the upload being bad (a scanned PDF with no text
    layer, a flaky provider); any failure there marks the row `status='failed'` with an
    actionable, secret-redacted message instead of ever surfacing as a 500 -- the upload
    itself already succeeded, so the response is still 202.
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

    model_override = resolve_requested_model(model)

    if media_type == "json":
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
        row = await _propose_merge_or_fail(session, row, resume, model_override)
        return _upload_response(row)

    # .md / .pdf: persist first (status='stored'), then attempt LLM-based extraction --
    # any failure there becomes status='failed', never a 500 (see docstring above).
    stored_path = store_upload(content, sha256=sha256, ext=media_type)
    row = source_document_repo.insert(
        session,
        filename=file.filename or f"upload.{media_type}",
        media_type=media_type,
        sha256=sha256,
        size_bytes=len(content),
        stored_path=stored_path,
        status="stored",
    )
    session.commit()

    try:
        if media_type == "md":
            resume = await ingest_markdown(content, model=model_override)
        else:
            resume = await ingest_pdf(Path(stored_path), model=model_override)
    except Exception as e:
        row = source_document_repo.mark_failed(session, row, error=redact_secrets(str(e)))
        session.commit()
        return _upload_response(row)

    row = source_document_repo.mark_extracted(session, row, extracted_json=resume.model_dump_json())
    session.commit()
    row = await _propose_merge_or_fail(session, row, resume, model_override)
    return _upload_response(row)


@router.get("/api/profile/documents")
async def list_documents(session: Session = Depends(get_session)):
    rows = source_document_repo.list_all(session)
    return {"documents": [_document_list_dict(r) for r in rows]}


@router.post("/api/profile/documents/{document_id}/apply")
async def apply_source_document(
    document_id: int, body: ApplyDocumentRequest, session: Session = Depends(get_session)
):
    """Approves a proposed merge -- in full, or a ``{ops: [indices]}`` subset into the STORED
    ``proposedPatch`` (the already Patch-Validator-vetted ops from proposal time, never the raw
    LLM output -- see merge_service.py). Re-runs the Patch Validator against the CURRENT active
    profile (robust to anything that changed since the proposal was made) and appends a new
    Profile Version with ``source_kind="upload"``.

    ``skipped`` in the response is honest about BOTH ways an op can fail to land: ops the Patch
    Validator itself rejected (out-of-bounds target, etc. -- ``result.skipped``) AND ops that
    were simply never selected by a ``{ops: [indices]}`` subset (excluded before the validator
    ever saw them). Either way, ``applied + skipped`` always equals the number of ops in
    ``proposedPatch``, never silently dropping the un-selected ones.
    """
    row = source_document_repo.get(session, document_id)
    if row is None:
        raise http_error(404, f"Source Document {document_id} not found")
    if row.status != "proposed":
        raise http_error(
            409, f"Source Document {document_id} is '{row.status}', not 'proposed' -- nothing to apply"
        )

    all_ops = [PatchOp.model_validate(op) for op in json.loads(row.proposed_patch or "[]")]
    if body.ops is not None:
        wanted = set(body.ops)
        ops_to_apply = [op for i, op in enumerate(all_ops) if i in wanted]
        excluded_count = len(all_ops) - len(ops_to_apply)
    else:
        ops_to_apply = all_ops
        excluded_count = 0

    try:
        profile = resolve_profile_for_merge(session)
    except ProfileValidationError as e:
        raise http_error(400, str(e)) from e
    try:
        result = apply_patch(profile, ops_to_apply, source_kind="upload")
    except PatchValidationFailed as e:
        raise http_error(422, f"Patch produced an invalid profile: {e}") from e

    row = source_document_repo.mark_applied(session, row)
    return _persist_patch_result(
        session,
        result,
        source_kind="upload",
        source_document_id=row.id,
        change_summary=f"Applied upload: {row.filename}",
        skipped=len(result.skipped) + excluded_count,
    )


@router.post("/api/profile/documents/{document_id}/reject", status_code=204)
async def reject_source_document(document_id: int, session: Session = Depends(get_session)):
    row = source_document_repo.get(session, document_id)
    if row is None:
        raise http_error(404, f"Source Document {document_id} not found")
    if row.status != "proposed":
        raise http_error(
            409, f"Source Document {document_id} is '{row.status}', not 'proposed' -- nothing to reject"
        )
    source_document_repo.mark_rejected(session, row)
    session.commit()
    return Response(status_code=204)


@router.get("/api/github/repos")
async def github_repos(username: str | None = None, session: Session = Depends(get_session)):
    resolved = _resolve_active_profile_or_error(session)
    user = username or resolved.profile.githubUsername
    if not user:
        return {"repos": [], "warning": "No githubUsername in profile and no username query"}
    repos, warn = await fetch_user_repos(user)
    return {
        "repos": [r.model_dump() for r in repos],
        "warning": warn,
    }
