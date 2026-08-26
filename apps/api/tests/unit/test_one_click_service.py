"""The One-click Resume service (v7 ticket 10): app/services/jobs/one_click_service.py.

These sit one level below tests/integration/test_jobs_one_click_api.py -- same pipeline, no
HTTP client -- so the four rules the module owns can be asserted as facts about rows rather
than about status codes: the second click costs no LLM call, a failed generation leaves the
Listing Memory exactly as it was, the proposal lands `approved` with `session_id IS NULL`, and
the ResumeVersion is attached to no chat session.

No LLM and no browser is real: ``fake_llm`` scripts every call (CLAUDE.md), and
``render_resume_pdf`` is replaced -- the actual Chromium render is covered by the ``@e2e``
tests in test_pdf_export_templates.py and would make every test here slow and Playwright-
dependent for bytes this module only passes through.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from sqlmodel import Session, select

from app import config as config_module
from app.db.tables import ChatMessage, ChatSession, ImprovementProposal, JobListing, ResumeVersion
from app.repositories import chat_repo, jobs_repo, proposal_repo
from app.services import settings_service
from app.services.jobs import one_click_service
from tests.factories import make_profile, make_resume_payload

# English on purpose: the posting's language is what the Resume is written in (Locale
# Authority), and ``make_resume_payload`` is English -- so the generated document matches the
# expected locale and no automatic quality pass (a second LLM call) is triggered. The
# Portuguese case is covered by ``TestResolveListingLocale`` without spending a call.
JOB_DESCRIPTION = (
    "We are hiring a Senior Backend Engineer to join our platform team. You will design "
    "and build scalable APIs in Python, own our PostgreSQL data layer, collaborate with "
    "the frontend team on GraphQL contracts, and help mentor junior engineers. Experience "
    "with Docker, Kubernetes, and CI/CD pipelines is a strong plus. We value clear written "
    "communication and a pragmatic approach to shipping reliable software."
)

SHORT_DESCRIPTION = "Backend dev. Apply on our site."

IDENTITY_KEY = "acme cloud|senior backend engineer"


def analysis_response(**overrides) -> str:
    payload = {
        "message": "Here is what I would change to aim your resume at this posting.",
        "items": [
            {
                "id": 1,
                "section": "headline",
                "current": "Senior Backend Engineer",
                "proposed": "Senior Backend Engineer focused on Python/FastAPI APIs",
                "rationale": "The posting asks explicitly for scalable API design in Python.",
            }
        ],
    }
    payload.update(overrides)
    return json.dumps(payload)


def generation_response() -> str:
    return json.dumps(make_resume_payload())


def script_one_click(fake_llm) -> None:
    """The two calls one generation costs: the Analysis, then the generation itself."""
    fake_llm.queue(analysis_response(), generation_response())


@pytest.fixture(autouse=True)
def _clean_locks():
    """``_locks`` is module state (the single-flight rule is per process, like the Scan
    runner's lock), so a test that leaves an entry behind must not be able to affect the next
    one."""
    one_click_service._locks.clear()
    yield
    one_click_service._locks.clear()


@pytest.fixture
def session(test_db_engine):
    with Session(test_db_engine) as s:
        yield s


@pytest.fixture
def profile(write_profile):
    return write_profile(make_profile())


@pytest.fixture
def rendered(monkeypatch) -> list[tuple[str, str]]:
    """Replaces the Chromium render, and records (fullName, template) per call so a test can
    assert WHICH document was rendered without reading PDF bytes."""
    calls: list[tuple[str, str]] = []

    async def _fake_render(resume, template=None):
        calls.append((resume.fullName, template))
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(one_click_service, "render_resume_pdf", _fake_render)
    return calls


def seed_listing(session: Session, **overrides) -> JobListing:
    """One Job Listing from a finished Scan -- written through the repository, so the row is
    shaped exactly as a real Scan would leave it."""
    scan = jobs_repo.start_scan(session, trigger="immediate")
    defaults = dict(
        scan_id=0,
        identity_key=IDENTITY_KEY,
        title="Senior Backend Engineer",
        company="Acme Cloud",
        description=JOB_DESCRIPTION,
        description_word_count=len(JOB_DESCRIPTION.split()),
        locale="en",
    )
    defaults.update(overrides)
    listing = JobListing(**defaults)
    jobs_repo.replace_listings(session, scan_id=int(scan.id or 0), listings=[(listing, [])])
    jobs_repo.upsert_memory(session, str(defaults["identity_key"]), status="new")
    session.commit()
    return listing


class TestFirstClick:
    async def test_generates_a_resume_through_the_analysis_and_approves_the_proposal(
        self, session, profile, fake_llm, rendered
    ):
        listing = seed_listing(session)
        script_one_click(fake_llm)

        result = await one_click_service.one_click_resume(session, int(listing.id or 0))

        assert result.content == b"%PDF-1.4 fake"
        assert result.regenerated is True
        assert fake_llm.call_count == 2

        # The Analysis really ran (it is not skipped for the One-click -- only the human
        # approval turn is), and the generation carried its items as the approved plan.
        assert "Job description:" in fake_llm.calls[0]["user"]
        assert "APPROVED IMPROVEMENT PLAN" in fake_llm.calls[1]["user"]
        assert "Senior Backend Engineer focused on Python/FastAPI APIs" in fake_llm.calls[1]["user"]

    async def test_the_proposal_is_approved_and_belongs_to_no_chat_session(
        self, session, profile, fake_llm, rendered
    ):
        """CONTEXT.md (One-click Resume): the proposal is auto-approved AS PRODUCED -- a real,
        itemized, auditable row, just with no conversation behind it."""
        listing = seed_listing(session)
        script_one_click(fake_llm)

        result = await one_click_service.one_click_resume(session, int(listing.id or 0))

        rows = session.exec(select(ImprovementProposal)).all()
        assert len(rows) == 1
        assert rows[0].status == "approved"
        assert rows[0].session_id is None
        assert rows[0].resume_version_id == result.resume_version_id
        assert rows[0].job_description == JOB_DESCRIPTION
        assert len(proposal_repo.get_items(rows[0])) == 1

    async def test_the_resume_version_is_attached_to_no_chat_session(
        self, session, profile, fake_llm, rendered
    ):
        listing = seed_listing(session)
        script_one_click(fake_llm)

        result = await one_click_service.one_click_resume(session, int(listing.id or 0))

        version = session.get(ResumeVersion, result.resume_version_id)
        assert version.session_id is None
        # And it does not put a conversation in the sidebar either.
        assert session.exec(select(ChatSession)).all() == []
        assert session.exec(select(ChatMessage)).all() == []

    async def test_the_listing_memory_points_at_the_generated_resume(
        self, session, profile, fake_llm, rendered
    ):
        listing = seed_listing(session)
        script_one_click(fake_llm)

        result = await one_click_service.one_click_resume(session, int(listing.id or 0))

        memory = jobs_repo.get_memory(session, IDENTITY_KEY)
        assert memory.resume_version_id == result.resume_version_id

    async def test_a_click_does_not_move_the_repost_baseline(
        self, session, profile, fake_llm, rendered
    ):
        """``last_seen_at`` is what the next Scan compares a posting's date against
        (``scan_service.is_repost``) -- the same rule ``listing_query._write_memory`` protects
        for a status click. A generation is not a sighting."""
        listing = seed_listing(session)
        before = jobs_repo.get_memory(session, IDENTITY_KEY).last_seen_at
        script_one_click(fake_llm)

        await one_click_service.one_click_resume(session, int(listing.id or 0))

        assert jobs_repo.get_memory(session, IDENTITY_KEY).last_seen_at == before

    async def test_the_status_the_user_chose_is_untouched(
        self, session, profile, fake_llm, rendered
    ):
        listing = seed_listing(session)
        jobs_repo.upsert_memory(session, IDENTITY_KEY, status="applied")
        session.commit()
        script_one_click(fake_llm)

        await one_click_service.one_click_resume(session, int(listing.id or 0))

        assert jobs_repo.get_memory(session, IDENTITY_KEY).status == "applied"

    async def test_the_pdf_is_named_after_the_company_and_the_role(
        self, session, profile, fake_llm, rendered
    ):
        listing = seed_listing(session)
        script_one_click(fake_llm)

        result = await one_click_service.one_click_resume(session, int(listing.id or 0))

        assert result.filename == "curriculo-acme-cloud-senior-backend-engineer.pdf"


class TestSecondClick:
    async def test_the_second_click_re_renders_and_spends_no_llm_call(
        self, session, profile, fake_llm, rendered
    ):
        """The whole point of the Listing Memory holding ``resume_version_id``."""
        listing = seed_listing(session)
        script_one_click(fake_llm)
        first = await one_click_service.one_click_resume(session, int(listing.id or 0))

        second = await one_click_service.one_click_resume(session, int(listing.id or 0))

        assert fake_llm.call_count == 2  # unchanged: the FakeLlm would raise on a third call
        assert second.resume_version_id == first.resume_version_id
        assert second.regenerated is False
        assert len(rendered) == 2  # rendered again, generated once

    async def test_regenerate_spends_a_new_generation_and_replaces_the_memory(
        self, session, profile, fake_llm, rendered
    ):
        listing = seed_listing(session)
        script_one_click(fake_llm)
        first = await one_click_service.one_click_resume(session, int(listing.id or 0))
        script_one_click(fake_llm)

        second = await one_click_service.one_click_resume(
            session, int(listing.id or 0), regenerate=True
        )

        assert fake_llm.call_count == 4
        assert second.resume_version_id != first.resume_version_id
        assert second.regenerated is True
        assert jobs_repo.get_memory(session, IDENTITY_KEY).resume_version_id == second.resume_version_id
        # The first proposal is not rewritten -- both are approved, each pointing at its own
        # document, so the history of what was generated when stays readable.
        rows = session.exec(select(ImprovementProposal)).all()
        assert [r.status for r in rows] == ["approved", "approved"]
        assert {r.resume_version_id for r in rows} == {first.resume_version_id, second.resume_version_id}

    async def test_a_dangling_memory_reference_regenerates_instead_of_failing(
        self, session, profile, fake_llm, rendered
    ):
        """``resume_version_id`` is a soft ref: the row it names can be gone. Refusing to serve
        the button over bookkeeping the user never saw would be the worse answer."""
        listing = seed_listing(session)
        jobs_repo.upsert_memory(session, IDENTITY_KEY, resume_version_id=9999)
        session.commit()
        script_one_click(fake_llm)

        result = await one_click_service.one_click_resume(session, int(listing.id or 0))

        assert result.regenerated is True
        assert jobs_repo.get_memory(session, IDENTITY_KEY).resume_version_id == result.resume_version_id


class TestRefusals:
    async def test_an_unknown_listing_is_a_listing_not_found(self, session, profile, fake_llm):
        with pytest.raises(one_click_service.ListingNotFound):
            await one_click_service.one_click_resume(session, 4242)

    async def test_a_posting_too_short_to_tailor_to_is_refused_before_any_llm_call(
        self, session, profile, fake_llm, rendered
    ):
        listing = seed_listing(
            session, description=SHORT_DESCRIPTION, description_word_count=6
        )

        with pytest.raises(one_click_service.DescriptionTooShort) as excinfo:
            await one_click_service.one_click_resume(session, int(listing.id or 0))

        # The message is the CODE, not copy -- the web owns the sentence it shows (ticket 13).
        assert str(excinfo.value) == "description_too_short"
        assert fake_llm.call_count == 0
        assert rendered == []

    async def test_an_llm_failure_leaves_the_memory_and_the_proposals_intact(
        self, session, profile, fake_llm, rendered
    ):
        listing = seed_listing(session)
        before = jobs_repo.get_memory(session, IDENTITY_KEY)
        assert before.resume_version_id is None
        fake_llm.queue(RuntimeError("provider exploded"))

        with pytest.raises(one_click_service.OneClickGenerationFailed):
            await one_click_service.one_click_resume(session, int(listing.id or 0))

        assert jobs_repo.get_memory(session, IDENTITY_KEY).resume_version_id is None
        assert session.exec(select(ImprovementProposal)).all() == []
        assert session.exec(select(ResumeVersion)).all() == []

    async def test_a_generation_failure_after_a_good_analysis_leaves_no_proposal_behind(
        self, session, profile, fake_llm, rendered
    ):
        """Deliberately different from the chat, where a failed generation leaves the proposal
        `proposed` and reapprovable -- there is a conversation there to reapprove it in."""
        listing = seed_listing(session)
        fake_llm.queue(analysis_response(), RuntimeError("provider exploded"))

        with pytest.raises(one_click_service.OneClickGenerationFailed):
            await one_click_service.one_click_resume(session, int(listing.id or 0))

        assert session.exec(select(ImprovementProposal)).all() == []
        assert jobs_repo.get_memory(session, IDENTITY_KEY).resume_version_id is None

    async def test_unusable_analysis_output_is_a_generation_failure_not_a_crash(
        self, session, profile, fake_llm, rendered
    ):
        listing = seed_listing(session)
        fake_llm.queue("not json at all")

        with pytest.raises(one_click_service.OneClickGenerationFailed):
            await one_click_service.one_click_resume(session, int(listing.id or 0))

        assert session.exec(select(ImprovementProposal)).all() == []

    async def test_a_failed_pdf_render_still_keeps_the_generated_resume(
        self, session, profile, fake_llm, monkeypatch
    ):
        """The retry is free: the document is already in the Listing Memory."""
        listing = seed_listing(session)
        script_one_click(fake_llm)

        async def _boom(resume, template=None):
            raise RuntimeError("chromium is not installed")

        monkeypatch.setattr(one_click_service, "render_resume_pdf", _boom)

        with pytest.raises(one_click_service.PdfRenderFailed):
            await one_click_service.one_click_resume(session, int(listing.id or 0))

        assert jobs_repo.get_memory(session, IDENTITY_KEY).resume_version_id is not None

    async def test_no_profile_is_not_dressed_up_as_a_generation_failure(
        self, session, fake_llm, rendered
    ):
        """There is no Profile to tailor -- telling the user to retry the provider would send
        them after the wrong problem, so this stays the app's own FileNotFoundError."""
        listing = seed_listing(session)

        with pytest.raises(FileNotFoundError):
            await one_click_service.one_click_resume(session, int(listing.id or 0))

        assert fake_llm.call_count == 0


class TestSingleFlight:
    async def test_a_concurrent_click_on_the_same_listing_is_refused(
        self, session, profile, fake_llm, rendered, monkeypatch
    ):
        """One One-click per listing at a time: a double click would burn two LLM calls and
        race to write one Listing Memory."""
        listing = seed_listing(session)
        script_one_click(fake_llm)
        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow_render(resume, template=None):
            started.set()
            await release.wait()
            return b"%PDF-1.4 fake"

        monkeypatch.setattr(one_click_service, "render_resume_pdf", _slow_render)

        first = asyncio.create_task(
            one_click_service.one_click_resume(session, int(listing.id or 0))
        )
        await started.wait()

        with pytest.raises(one_click_service.OneClickAlreadyRunning):
            await one_click_service.one_click_resume(session, int(listing.id or 0))

        release.set()
        assert (await first).regenerated is True

    async def test_the_lock_is_per_listing_not_global(
        self, session, profile, fake_llm, rendered, monkeypatch
    ):
        """Two DIFFERENT listings being one-clicked at once is a perfectly reasonable thing to
        do; only the same listing twice is refused. Asserted on the lock itself rather than by
        racing two generations, because the DB Session is per-REQUEST in production and sharing
        one across two coroutines would be testing SQLAlchemy, not this rule."""
        listing = seed_listing(session)
        script_one_click(fake_llm)
        held = asyncio.Event()
        release = asyncio.Event()
        other_lock_taken = False

        async def _slow_render(resume, template=None):
            nonlocal other_lock_taken
            # A different listing's lock is free while this one is held...
            one_click_service._lock_for(int(listing.id or 0) + 1)
            other_lock_taken = True
            held.set()
            await release.wait()
            return b"%PDF-1.4 fake"

        monkeypatch.setattr(one_click_service, "render_resume_pdf", _slow_render)
        task = asyncio.create_task(
            one_click_service.one_click_resume(session, int(listing.id or 0))
        )
        await held.wait()
        release.set()
        await task

        assert other_lock_taken is True

    async def test_a_finished_click_leaves_no_lock_behind(
        self, session, profile, fake_llm, rendered
    ):
        listing = seed_listing(session)
        script_one_click(fake_llm)

        await one_click_service.one_click_resume(session, int(listing.id or 0))

        assert int(listing.id or 0) not in one_click_service._locks

    async def test_the_lock_is_released_after_a_failure(
        self, session, profile, fake_llm, rendered
    ):
        """A refused click must not leave the listing permanently 409ing."""
        listing = seed_listing(session)
        fake_llm.queue(RuntimeError("provider exploded"))
        with pytest.raises(one_click_service.OneClickGenerationFailed):
            await one_click_service.one_click_resume(session, int(listing.id or 0))

        script_one_click(fake_llm)
        result = await one_click_service.one_click_resume(session, int(listing.id or 0))

        assert result.regenerated is True


class TestTemplate:
    async def test_the_pdf_uses_the_globally_preferred_template(
        self, session, profile, fake_llm, rendered, monkeypatch
    ):
        """No browser is in the loop, so the Template comes from the server-side preference
        (CONTEXT.md: a global sticky preference, like theme) rather than a request field."""
        listing = seed_listing(session)
        script_one_click(fake_llm)
        monkeypatch.setattr(settings_service, "get_resume_template", lambda: "latex-ats")

        await one_click_service.one_click_resume(session, int(listing.id or 0))

        assert rendered[-1][1] == "latex-ats"

    async def test_it_falls_back_to_the_default_template_when_nothing_was_saved(self):
        """Today's real state: the web still keeps the pick in ``localStorage``, so nothing
        writes this app_setting yet and every One-click PDF renders with the default."""
        assert settings_service.get_resume_template() == "modern"

    async def test_a_saved_preference_is_read_from_app_settings(self, session, profile, fake_llm, rendered):
        listing = seed_listing(session)
        script_one_click(fake_llm)
        config_module.set_app_setting(settings_service.RESUME_TEMPLATE_SETTING_KEY, "latex-ats")

        await one_click_service.one_click_resume(session, int(listing.id or 0))

        assert rendered[-1][1] == "latex-ats"


class TestResolveListingLocale:
    """Locale Authority: the POSTING's language, resolved once by the Scan and read here --
    never re-sniffed, so the badge the user saw and the resume they get agree."""

    def test_it_uses_the_listings_own_locale(self):
        assert one_click_service.resolve_listing_locale(_bare_listing(locale="en")) == "en"
        assert one_click_service.resolve_listing_locale(_bare_listing(locale="pt-BR")) == "pt-BR"

    def test_a_region_subtag_folds_onto_a_supported_language(self):
        assert one_click_service.resolve_listing_locale(_bare_listing(locale="en-US")) == "en"

    def test_an_unsupported_locale_falls_back_to_the_default(self):
        assert one_click_service.resolve_listing_locale(_bare_listing(locale="fr")) == "pt-BR"

    async def test_the_analysis_prompt_carries_the_listings_locale(
        self, session, profile, fake_llm, rendered
    ):
        listing = seed_listing(session)
        script_one_click(fake_llm)

        await one_click_service.one_click_resume(session, int(listing.id or 0))

        assert "Target locale" in fake_llm.calls[0]["user"]
        assert fake_llm.calls[0]["user"].rstrip().endswith(
            "following the schema in the system prompt."
        )
        assert "Target locale for \"message\" and every item's \"proposed\"/\"rationale\": en" in (
            fake_llm.calls[0]["user"]
        )


class TestFileName:
    def test_accents_and_punctuation_are_stripped(self):
        listing = _bare_listing(company="Ação & Cia. Ltda", title="Engenheiro(a) Backend")
        assert one_click_service.one_click_file_name(listing) == (
            "curriculo-acao-cia-ltda-engenheiro-a-backend.pdf"
        )

    def test_a_listing_with_nothing_sluggable_still_gets_a_name(self):
        assert one_click_service.one_click_file_name(_bare_listing(company="—", title="?")) == (
            "curriculo.pdf"
        )


class TestOpenInChat:
    def test_it_creates_a_resume_session_titled_company_and_role(self, session):
        listing = seed_listing(session)

        chat_session = one_click_service.open_in_chat(session, int(listing.id or 0))
        session.commit()

        assert chat_session.kind == "resume"
        assert chat_session.title == "Acme Cloud · Senior Backend Engineer"
        assert chat_session.job_description == JOB_DESCRIPTION
        assert chat_session.locale == "en"

    def test_the_posting_is_stored_as_the_users_first_message(self, session):
        listing = seed_listing(session)

        chat_session = one_click_service.open_in_chat(session, int(listing.id or 0))
        session.commit()

        _row, messages = chat_repo.get_session_with_messages(session, int(chat_session.id or 0))
        assert [(m.role, m.content) for m in messages] == [("user", JOB_DESCRIPTION)]
        # No intent is stamped: intent is what the server decides when a turn RUNS, and this
        # turn has not run -- exactly like every user message the chat itself writes.
        assert messages[0].intent is None

    def test_it_spends_no_llm_call_and_generates_nothing(self, session, fake_llm):
        listing = seed_listing(session)

        one_click_service.open_in_chat(session, int(listing.id or 0))
        session.commit()

        assert fake_llm.call_count == 0
        assert session.exec(select(ResumeVersion)).all() == []
        assert session.exec(select(ImprovementProposal)).all() == []

    def test_a_short_posting_may_still_be_opened_in_the_chat(self, session):
        """Only the One-click is refused on a thin posting: the chat can ask about it, and the
        user can paste the rest of the description themselves."""
        listing = seed_listing(
            session, description=SHORT_DESCRIPTION, description_word_count=6
        )

        chat_session = one_click_service.open_in_chat(session, int(listing.id or 0))
        session.commit()

        assert chat_session.job_description == SHORT_DESCRIPTION

    def test_an_unknown_listing_is_a_listing_not_found(self, session):
        with pytest.raises(one_click_service.ListingNotFound):
            one_click_service.open_in_chat(session, 4242)

    def test_a_listing_missing_a_company_still_gets_a_readable_title(self, session):
        listing = seed_listing(session, company="")

        chat_session = one_click_service.open_in_chat(session, int(listing.id or 0))
        session.commit()

        assert chat_session.title == "Senior Backend Engineer"


def _bare_listing(**overrides) -> JobListing:
    defaults = dict(
        scan_id=0,
        identity_key=IDENTITY_KEY,
        title="Senior Backend Engineer",
        company="Acme Cloud",
        description=JOB_DESCRIPTION,
        description_word_count=len(JOB_DESCRIPTION.split()),
        locale="en",
    )
    defaults.update(overrides)
    return JobListing(**defaults)
