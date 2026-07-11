"""Source Document endpoints (upload/list/apply/reject) -- extracted from routers/profile.py
(ticket 04 prefactor). Handlers here are thin HTTP mapping over
``app.services.ingestion.pipeline.ingest_upload`` (the orchestration seam) and
``app.services.chat_service.link_upload_to_session`` (the chat-domain side channel); all
paths, status codes, and response shapes are unchanged from the former monolithic router.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from pydantic import BaseModel
from sqlmodel import Session

from app.db.tables import SourceDocument
from app.domain.profile_patch import PatchOp, PatchValidationFailed, apply_patch
from app.repositories import source_document_repo
from app.routers.deps import get_session, resolve_requested_model
from app.services.chat_service import link_upload_to_session
from app.services.errors import http_error
from app.services.ingestion.merge_service import resolve_profile_for_merge
from app.services.ingestion.pipeline import (
    InvalidSourceDocumentError,
    UnsupportedMediaTypeError,
    UploadTooLargeError,
    ingest_upload,
)
from app.services.profile_patch_service import persist_patch_result
from app.services.profile_resolution import ProfileValidationError

router = APIRouter()


class ApplyDocumentRequest(BaseModel):
    ops: list[int] | None = None


def _upload_response(row: SourceDocument) -> dict:
    return {
        "documentId": row.id,
        "status": row.status,
        "proposedPatch": json.loads(row.proposed_patch) if row.proposed_patch else None,
        "diffSummary": json.loads(row.diff_summary) if row.diff_summary else None,
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


def _parse_session_id(raw: str | None) -> int | None:
    """v2 ticket 10 review fix: ``sessionId`` used to be declared ``int | None = Form(None)``,
    which makes FastAPI/Pydantic reject a malformed value (e.g. "not-a-number") with an
    automatic 422 BEFORE ``upload_document`` ever runs -- exactly the outcome this field must
    never cause (the session link is a best-effort side channel; the upload is the primary
    flow). Declaring it ``str | None`` instead and parsing it by hand here means a malformed
    value is silently treated the same as an absent one -- ``None``, never a raised error.
    """
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@router.post("/api/profile/documents", status_code=202)
async def upload_document(
    file: UploadFile = File(...),
    model: str | None = Form(None),
    sessionId: str | None = Form(None),
    session: Session = Depends(get_session),
):
    """Accepts a `.json`/`.md`/`.pdf` Source Document upload (CONTEXT.md: Source Document,
    Ingestion) and delegates the whole pipeline (size/type/dedup/store/insert/extract/propose)
    to ``ingest_upload``. Three request-shaped rejections map to their status code here: over
    ``max_upload_bytes`` (413), an unrecognized extension (415), a malformed or schema-invalid
    `.json` (422) -- none of these persist a row or a file. Everything else the pipeline itself
    handles non-fatally, landing the row at ``status='failed'`` instead (still a 202: the upload
    itself succeeded).

    ``sessionId`` (v2 ticket 10, optional multipart field) names the chat session the upload
    came from, if any -- see ``link_upload_to_session``. Declared ``str`` (not ``int``) and
    parsed by ``_parse_session_id`` on purpose: an unknown, missing, OR MALFORMED ``sessionId``
    must never affect the upload's own outcome -- an ``int`` Form field would instead make
    FastAPI itself reject a malformed value with a 422 before this handler ever runs.
    """
    content = await file.read()
    chat_session_id = _parse_session_id(sessionId)
    model_override = resolve_requested_model(model)

    try:
        row = await ingest_upload(
            session, filename=file.filename, content=content, model_override=model_override
        )
    except UploadTooLargeError as e:
        raise http_error(413, str(e)) from e
    except UnsupportedMediaTypeError as e:
        raise http_error(415, str(e)) from e
    except InvalidSourceDocumentError as e:
        raise http_error(422, str(e)) from e

    link_upload_to_session(session, chat_session_id, row)
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
    return persist_patch_result(
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
