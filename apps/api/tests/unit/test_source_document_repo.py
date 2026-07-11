"""Repository tests for source_documents (v2 ticket 03 -- "Ingestao e Source Documents").

Mirrors the fixture setup in tests/unit/test_repositories.py (in-memory SQLite engine via
app.db.engine.create_db_engine(), same production code path) but kept in its own module so
this ticket's tests don't collide with concurrent edits to that shared file.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session
from sqlmodel.pool import StaticPool

from app.db.engine import create_db_engine, init_db
from app.repositories import profile_repo, source_document_repo


@pytest.fixture
def engine():
    eng = create_db_engine("sqlite://", poolclass=StaticPool)
    init_db(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


class TestSourceDocumentRepo:
    def test_insert_and_get(self, session):
        row = source_document_repo.insert(
            session,
            filename="resume.json",
            media_type="json",
            sha256="a" * 64,
            size_bytes=123,
            stored_path="data/uploads/aaaa.json",
        )

        found = source_document_repo.get(session, row.id)

        assert found is not None
        assert found.filename == "resume.json"
        assert found.media_type == "json"
        assert found.status == "stored"  # default lifecycle start (CONTEXT.md: Source Document)
        assert found.extracted_json is None
        assert found.proposed_patch is None
        assert found.error is None

    def test_get_returns_none_for_missing_id(self, session):
        assert source_document_repo.get(session, 999) is None

    def test_get_by_sha256_finds_the_matching_row(self, session):
        source_document_repo.insert(
            session,
            filename="a.md",
            media_type="md",
            sha256="b" * 64,
            size_bytes=10,
            stored_path="data/uploads/bbbb.md",
        )

        found = source_document_repo.get_by_sha256(session, "b" * 64)

        assert found is not None
        assert found.filename == "a.md"

    def test_get_by_sha256_returns_none_when_absent(self, session):
        assert source_document_repo.get_by_sha256(session, "c" * 64) is None

    def test_sha256_is_unique_at_the_db_level(self, session):
        source_document_repo.insert(
            session,
            filename="one.json",
            media_type="json",
            sha256="d" * 64,
            size_bytes=1,
            stored_path="data/uploads/dddd.json",
        )
        session.commit()

        with pytest.raises(IntegrityError):
            source_document_repo.insert(
                session,
                filename="two.json",
                media_type="json",
                sha256="d" * 64,
                size_bytes=2,
                stored_path="data/uploads/dddd-2.json",
            )

    def test_list_all_returns_newest_first(self, session):
        source_document_repo.insert(
            session,
            filename="first.json",
            media_type="json",
            sha256="e" * 64,
            size_bytes=1,
            stored_path="p1",
        )
        source_document_repo.insert(
            session,
            filename="second.json",
            media_type="json",
            sha256="f" * 64,
            size_bytes=1,
            stored_path="p2",
        )

        rows = source_document_repo.list_all(session)

        assert [r.filename for r in rows] == ["second.json", "first.json"]

    def test_mark_extracted_sets_status_and_preview(self, session):
        row = source_document_repo.insert(
            session,
            filename="a.json",
            media_type="json",
            sha256="1" * 64,
            size_bytes=1,
            stored_path="p",
        )

        updated = source_document_repo.mark_extracted(
            session, row, extracted_json=json.dumps({"fullName": "Ana"})
        )

        assert updated.status == "extracted"
        assert json.loads(updated.extracted_json)["fullName"] == "Ana"
        assert updated.error is None

    def test_mark_failed_sets_status_and_error(self, session):
        row = source_document_repo.insert(
            session,
            filename="scanned.pdf",
            media_type="pdf",
            sha256="2" * 64,
            size_bytes=1,
            stored_path="p",
        )

        updated = source_document_repo.mark_failed(session, row, error="PDF has no extractable text")

        assert updated.status == "failed"
        assert updated.error == "PDF has no extractable text"
        assert updated.extracted_json is None

    def test_delete_removes_the_row(self, session):
        row = source_document_repo.insert(
            session,
            filename="gone.json",
            media_type="json",
            sha256="3" * 64,
            size_bytes=1,
            stored_path="p",
        )
        session.commit()

        source_document_repo.delete(session, row)
        session.commit()

        assert source_document_repo.get(session, row.id) is None


class TestSourceDocumentSoftRefOrphan:
    """profile_versions.source_document_id is a soft ref, deliberately without a real FK (see
    app/db/tables.py's module docstring). This is the acceptance-criteria orphan case: deleting
    a source_documents row that a profile_versions row still points at must not raise an
    integrity error, and the profile_versions row (append-only history) must survive untouched.
    """

    def test_deleting_a_referenced_source_document_does_not_break_the_profile_version(self, session):
        doc = source_document_repo.insert(
            session,
            filename="orphan.json",
            media_type="json",
            sha256="4" * 64,
            size_bytes=1,
            stored_path="p",
        )
        session.commit()

        version = profile_repo.insert_version(
            session, data="{}", source_kind="upload", source_document_id=doc.id
        )
        session.commit()

        source_document_repo.delete(session, doc)
        session.commit()  # must not raise -- no real FK constraint enforces this reference

        assert source_document_repo.get(session, doc.id) is None
        reloaded = profile_repo.get_by_version(session, version.version)
        assert reloaded is not None
        assert reloaded.source_document_id == doc.id  # dangling reference, preserved as-is
