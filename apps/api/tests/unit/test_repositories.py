"""Repository-layer tests for the B5 SQLite persistence layer.

Uses an in-memory SQLite engine (StaticPool, so all sessions in a test share the same
in-memory DB) with foreign_keys=ON, exercising the same app.db.engine.create_db_engine()
code path production uses -- not a hand-rolled test-only engine.
"""

from __future__ import annotations

import json

import pytest
from sqlmodel import Session, text
from sqlmodel.pool import StaticPool

from app.db.engine import create_db_engine, init_db
from app.domain.schemas import ProfileMaster, ResumeDocument
from app.repositories import app_settings_repo, chat_repo, profile_repo, resume_repo


@pytest.fixture
def engine():
    eng = create_db_engine("sqlite://", poolclass=StaticPool)
    init_db(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


class TestProfileRepo:
    def test_get_active_returns_none_when_empty(self, session):
        assert profile_repo.get_active(session) is None

    def test_insert_version_is_sequential_and_unique_within_one_session(self, session):
        first = profile_repo.insert_version(session, data="{}", source_kind="seed_disk")
        second = profile_repo.insert_version(session, data="{}", source_kind="manual")

        assert first.version == 1
        assert second.version == 2

    def test_get_active_is_the_highest_version(self, session):
        profile_repo.insert_version(session, data='{"n": 1}', source_kind="seed_disk")
        profile_repo.insert_version(session, data='{"n": 2}', source_kind="manual")

        active = profile_repo.get_active(session)

        assert active is not None
        assert active.version == 2
        assert active.data == '{"n": 2}'

    def test_get_by_version_returns_the_matching_row(self, session):
        profile_repo.insert_version(session, data='{"n": 1}', source_kind="seed_disk")
        second = profile_repo.insert_version(session, data='{"n": 2}', source_kind="manual")

        found = profile_repo.get_by_version(session, 2)

        assert found is not None
        assert found.id == second.id

    def test_profile_master_roundtrips_through_the_data_column(self, session):
        profile = ProfileMaster(
            fullName="Ana Costa",
            headline="Senior Backend Engineer",
            summary="A summary.",
            skills=["Python", "SQL"],
            githubUsername="anacosta",
        )

        row = profile_repo.insert_version(
            session, data=profile.model_dump_json(), source_kind="seed_disk"
        )
        reloaded = ProfileMaster.model_validate_json(row.data)

        assert reloaded == profile


class TestChatRepo:
    def test_create_session_and_list_sessions(self, session):
        chat_repo.create_session(session, title="First")
        chat_repo.create_session(session, title="Second")

        sessions = chat_repo.list_sessions(session)

        assert [s.title for s in sessions] == ["Second", "First"]  # updated_at desc

    def test_get_session_with_messages(self, session):
        chat_session = chat_repo.create_session(session, title="A session")
        chat_repo.append_message(session, session_id=chat_session.id, role="user", content="hi")
        chat_repo.append_message(session, session_id=chat_session.id, role="assistant", content="hello")

        found, messages = chat_repo.get_session_with_messages(session, chat_session.id)

        assert found is not None
        assert found.id == chat_session.id
        assert [m.content for m in messages] == ["hi", "hello"]

    def test_get_session_with_messages_returns_none_for_missing_session(self, session):
        found, messages = chat_repo.get_session_with_messages(session, 999)

        assert found is None
        assert messages == []

    def test_delete_session_cascades_messages_but_not_resume_versions(self, session):
        chat_session = chat_repo.create_session(session, title="Deletable")
        chat_repo.append_message(session, session_id=chat_session.id, role="user", content="hi")
        resume = resume_repo.insert_version(
            session, data="{}", session_id=chat_session.id
        )
        session.commit()

        deleted = chat_repo.delete_session(session, chat_session.id)
        session.commit()

        assert deleted is True
        found, messages = chat_repo.get_session_with_messages(session, chat_session.id)
        assert found is None
        assert messages == []
        # The resume version survives the session's deletion (session_id is nulled out, not
        # the row itself -- see app/db/tables.py's module docstring on ON DELETE SET NULL).
        survivor = resume_repo.get(session, resume.id)
        assert survivor is not None
        assert survivor.session_id is None

    def test_delete_session_returns_false_for_missing_session(self, session):
        assert chat_repo.delete_session(session, 999) is False

    def test_append_message_and_touch_session_updates_updated_at(self, session):
        chat_session = chat_repo.create_session(session, title="Touchable")
        original_updated_at = chat_session.updated_at

        chat_repo.touch_session(session, chat_session.id)
        session.refresh(chat_session)

        assert chat_session.updated_at >= original_updated_at


class TestResumeRepo:
    def test_insert_and_get(self, session):
        row = resume_repo.insert_version(session, data="{}")

        found = resume_repo.get(session, row.id)

        assert found is not None
        assert found.data == "{}"

    def test_parent_version_chaining(self, session):
        parent = resume_repo.insert_version(session, data='{"v": 1}')
        child = resume_repo.insert_version(session, data='{"v": 2}', parent_version_id=parent.id)

        assert child.parent_version_id == parent.id

    def test_resume_document_roundtrips_through_the_data_column(self, session):
        resume = ResumeDocument(fullName="Ana Costa", headline="Engineer", summary="Summary text.")

        row = resume_repo.insert_version(session, data=resume.model_dump_json())
        reloaded = ResumeDocument.model_validate_json(row.data)

        assert reloaded == resume

    def test_links_to_a_profile_version(self, session):
        profile_version = profile_repo.insert_version(session, data="{}", source_kind="seed_disk")

        resume = resume_repo.insert_version(
            session, data="{}", profile_version_id=profile_version.id
        )

        assert resume.profile_version_id == profile_version.id


class TestAppSettingsRepo:
    """v3 ticket 01: non-sensitive runtime preferences (provider/model choice) -- API keys
    NEVER land here, only in the OS keychain (see app/services/secret_store.py)."""

    def test_get_returns_none_when_key_is_missing(self, session):
        assert app_settings_repo.get(session, "ai_provider") is None

    def test_set_then_get_roundtrips_the_value(self, session):
        app_settings_repo.set(session, "ai_provider", "claude")
        session.commit()

        assert app_settings_repo.get(session, "ai_provider") == "claude"

    def test_set_overwrites_an_existing_key(self, session):
        app_settings_repo.set(session, "ai_provider", "claude")
        app_settings_repo.set(session, "ai_provider", "gemini")
        session.commit()

        assert app_settings_repo.get(session, "ai_provider") == "gemini"

    def test_delete_removes_the_key(self, session):
        app_settings_repo.set(session, "ai_provider", "claude")
        session.commit()

        app_settings_repo.delete(session, "ai_provider")
        session.commit()

        assert app_settings_repo.get(session, "ai_provider") is None

    def test_delete_missing_key_is_not_an_error(self, session):
        app_settings_repo.delete(session, "does-not-exist")  # no raise

    def test_get_all_returns_every_stored_key(self, session):
        app_settings_repo.set(session, "ai_provider", "claude")
        app_settings_repo.set(session, "ai_default_model", "claude-sonnet-5")
        session.commit()

        assert app_settings_repo.get_all(session) == {
            "ai_provider": "claude",
            "ai_default_model": "claude-sonnet-5",
        }

    def test_value_is_json_encoded_on_disk(self, session):
        """Guards against accidentally storing a bare Python repr instead of JSON -- the acceptance
        criterion is ``app_settings(key PK, value JSON, updated_at)``."""
        app_settings_repo.set(session, "ai_provider", "claude")
        session.commit()

        row = session.get(app_settings_repo.AppSettings, "ai_provider")
        assert row is not None
        assert json.loads(row.value) == "claude"


def test_foreign_keys_pragma_is_enforced(engine):
    """Sanity check that create_db_engine() actually turns on FK enforcement -- without it
    the cascade-delete test above would pass for the wrong reason (SQLite silently ignoring
    the FK constraints entirely)."""
    with Session(engine) as session:
        result = session.exec(text("PRAGMA foreign_keys")).first()
        assert result[0] == 1
