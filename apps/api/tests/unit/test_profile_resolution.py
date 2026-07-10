"""Interface tests for app/services/profile_resolution.py (v2 ticket 01 — "Perfil vivo como
fonte de leitura"). Replaces the old profile_service.py policy (DB-empty disk fallback +
placeholder/PDF extraction policy) with a single ``resolve_active_profile(session)`` seam
used by routers/profile.py, generation_service.py, and chat_service.py.

SQLite in-memory (StaticPool) + tmp-path disk, per the ticket's testing convention -- no HTTP
client here (see tests/integration/test_profile_endpoints.py and
test_generate_endpoints_compat.py for the endpoint-level coverage of the same interface).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import Session
from sqlmodel.pool import StaticPool

from app.db.engine import create_db_engine, init_db
from app.domain.schemas import ProfileMaster, ResumeDocument
from app.repositories import profile_repo
from app.services import profile_resolution as profile_resolution_module
from app.services.profile_resolution import (
    ProfileValidationError,
    finish_profile_from_extraction,
    load_real_profile_from_disk_or_none,
    resolve_active_profile,
)
from tests.factories import make_profile


@pytest.fixture
def engine():
    eng = create_db_engine("sqlite://", poolclass=StaticPool)
    init_db(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture(autouse=True)
def _no_pdf_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test gets "no Profile.pdf on disk" unless it opts into a specific PDF scenario
    via ``mock_pdf_excerpt`` below -- resolve_active_profile always attempts a PDF read."""
    monkeypatch.setattr(profile_resolution_module, "load_profile_pdf_excerpt", lambda: ("", None, None))


@pytest.fixture
def mock_pdf_excerpt(monkeypatch: pytest.MonkeyPatch):
    def _set(text: str = "", path: Path | None = None, err: str | None = None) -> None:
        monkeypatch.setattr(
            profile_resolution_module, "load_profile_pdf_excerpt", lambda: (text, path, err)
        )

    return _set


class TestResolveActiveProfileFromDb:
    def test_db_active_version_wins_over_disk(self, session, write_profile):
        write_profile(make_profile(fullName="Disk Person"))
        db_profile = make_profile(fullName="DB Person")
        row = profile_repo.insert_version(
            session, data=json.dumps(db_profile), source_kind="seed_disk"
        )
        session.commit()

        resolved = resolve_active_profile(session)

        assert resolved.profile.fullName == "DB Person"
        assert resolved.profile_version_id == row.id
        assert resolved.source == "db"
        assert resolved.needs_extraction is False

    def test_db_active_version_is_the_highest_version_not_insertion_order(
        self, session, write_profile
    ):
        write_profile(make_profile(fullName="Disk Person"))
        profile_repo.insert_version(session, data=json.dumps(make_profile(fullName="V1")), source_kind="seed_disk")
        v2_row = profile_repo.insert_version(session, data=json.dumps(make_profile(fullName="V2")), source_kind="manual")
        session.commit()

        resolved = resolve_active_profile(session)

        assert resolved.profile.fullName == "V2"
        assert resolved.profile_version_id == v2_row.id


class TestResolveActiveProfileFallsBackToDisk:
    def test_empty_db_falls_back_to_disk(self, session, write_profile):
        write_profile(make_profile(fullName="Disk Person"))

        resolved = resolve_active_profile(session)

        assert resolved.profile.fullName == "Disk Person"
        assert resolved.profile_version_id is None
        assert resolved.source == "disk"
        assert resolved.needs_extraction is False

    def test_empty_db_and_missing_disk_profile_raises_file_not_found(self, session):
        with pytest.raises(FileNotFoundError):
            resolve_active_profile(session)

    def test_empty_db_and_invalid_disk_json_raises_profile_validation_error(
        self, session, isolated_data_env
    ):
        (isolated_data_env / "resume.json").write_text("not valid json", encoding="utf-8")

        with pytest.raises(ProfileValidationError):
            resolve_active_profile(session)

    def test_placeholder_disk_profile_with_no_pdf_needs_extraction(self, session, write_profile):
        write_profile(
            make_profile(fullName="Alex Sample", summary="Replace this text with your real summary.")
        )

        resolved = resolve_active_profile(session)

        assert resolved.needs_extraction is True
        assert resolved.pdf_text == ""

    def test_placeholder_disk_profile_with_pdf_needs_extraction_and_carries_pdf_text(
        self, session, write_profile, mock_pdf_excerpt
    ):
        write_profile(
            make_profile(fullName="Alex Sample", summary="Replace this text with your real summary.")
        )
        mock_pdf_excerpt(text="Real PDF text.", path=Path("/fake/Profile.pdf"))

        resolved = resolve_active_profile(session)

        assert resolved.needs_extraction is True
        assert resolved.pdf_text == "Real PDF text."
        assert resolved.pdf_path == Path("/fake/Profile.pdf")


class TestResolveActiveProfilePdfErrors:
    def test_broken_pdf_raises_regardless_of_db_state(
        self, session, write_profile, mock_pdf_excerpt
    ):
        write_profile(make_profile())
        mock_pdf_excerpt(path=Path("/fake/Profile.pdf"), err="could not decode PDF")

        with pytest.raises(ProfileValidationError, match="could not decode PDF"):
            resolve_active_profile(session)

    def test_broken_pdf_raises_even_when_db_has_an_active_version(
        self, session, write_profile, mock_pdf_excerpt
    ):
        profile_repo.insert_version(session, data=json.dumps(make_profile()), source_kind="seed_disk")
        session.commit()
        mock_pdf_excerpt(path=Path("/fake/Profile.pdf"), err="could not decode PDF")

        with pytest.raises(ProfileValidationError):
            resolve_active_profile(session)


class TestFinishProfileFromExtraction:
    def test_valid_extraction_becomes_a_profile_master(self):
        extracted = ResumeDocument(fullName="Ana Costa", headline="Engineer", summary="A real summary.")

        profile = finish_profile_from_extraction(extracted)

        assert isinstance(profile, ProfileMaster)
        assert profile.fullName == "Ana Costa"

    def test_extraction_with_blank_fullname_raises(self):
        extracted = ResumeDocument(fullName="  ", headline="Engineer", summary="A real summary.")

        with pytest.raises(ProfileValidationError):
            finish_profile_from_extraction(extracted)


class TestLoadRealProfileFromDiskOrNone:
    def test_missing_file_returns_none(self, isolated_data_env):
        assert load_real_profile_from_disk_or_none() is None

    def test_invalid_json_returns_none(self, isolated_data_env):
        (isolated_data_env / "resume.json").write_text("not valid json", encoding="utf-8")
        assert load_real_profile_from_disk_or_none() is None

    def test_placeholder_profile_returns_none(self, write_profile):
        write_profile(make_profile(fullName="Alex Sample", summary="Replace this text with your real summary."))
        assert load_real_profile_from_disk_or_none() is None

    def test_real_profile_returns_profile_master(self, write_profile):
        write_profile(make_profile(fullName="Ana Costa"))
        profile = load_real_profile_from_disk_or_none()
        assert profile is not None
        assert profile.fullName == "Ana Costa"
