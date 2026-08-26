"""POST /api/jobs/listings/{id}/one-click-resume and .../open-in-chat (v7 ticket 10).

The listings these endpoints are pointed at are written straight through ``jobs_repo``, in the
shape a finished Scan leaves them (``identity_key`` from the real ``domain/listing_identity``
normalizer, not a hand-typed string). Deliberately NOT by running a Scan the way
test_jobs_listings_api.py's ``scanned`` fixture does: that starts a background task whose
Session shares the single connection ``StaticPool`` hands out for an in-memory DB, and under a
full-suite load the two intermittently interleave -- observed as a listing missing from the
list, and (in that other file) as a ``ListingMemory`` that could not be refreshed. It is a
test-harness race, not a product one (a real deployment is a file DB where every Session gets
its own connection), and it is written up in the ticket's Comments. What THIS file is about is
the two endpoints, so paying for that race here buys nothing; a Scan writing real listing rows
is already ticket 09's coverage.

What is faked, and only this: the LLM (``fake_llm``, CLAUDE.md -- no real provider, ever) and
the Chromium render (``render_resume_pdf``; the real one is covered by the ``@e2e`` tests in
test_pdf_export_templates.py and would make this file slow and Playwright-dependent for bytes
the endpoint only passes through). The HTTP contract itself -- statuses, media type,
``Content-Disposition``, the ``detail`` strings the web shows verbatim -- is real.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from sqlmodel import Session, select

from app.db.tables import ImprovementProposal, JobListing, ListingSource, ResumeVersion
from app.domain.listing_identity import identity_key
from app.repositories import jobs_repo
from app.services.jobs import one_click_service
from tests.factories import make_profile, make_resume_payload

ONE_CLICK = "/api/jobs/listings/{id}/one-click-resume"
OPEN_IN_CHAT = "/api/jobs/listings/{id}/open-in-chat"

# English, so the generated ``make_resume_payload`` matches the posting's language and no
# automatic quality pass (a third LLM call) fires. See test_one_click_service.py.
LONG_POSTING = {
    "title": "Senior Backend Engineer",
    "company": "Acme Cloud",
    "url": "https://linkedin.test/101",
    "description": (
        "We are hiring a Senior Backend Engineer to join our platform team. You will design "
        "and build scalable APIs in Python, own our PostgreSQL data layer, collaborate with "
        "the frontend team on GraphQL contracts, and help mentor junior engineers. Experience "
        "with Docker, Kubernetes, and CI/CD pipelines is a strong plus. We value clear written "
        "communication and a pragmatic approach to shipping reliable software."
    ),
    "is_remote": True,
    "location": "Remote",
}
SHORT_POSTING = {
    "title": "PHP Developer",
    "company": "Legacy Systems",
    "url": "https://indeed.test/103",
    "description": "PHP developer wanted. Apply on our website.",
    "location": "Remote",
}


def analysis_response() -> str:
    return json.dumps(
        {
            "message": "Here is what I would change to aim your resume at this posting.",
            "items": [
                {
                    "id": 1,
                    "section": "headline",
                    "current": "Senior Backend Engineer",
                    "proposed": "Senior Backend Engineer focused on Python/FastAPI APIs",
                    "rationale": "The posting asks explicitly for scalable API design.",
                }
            ],
        }
    )


def script_one_click(fake_llm) -> None:
    """The Analysis, then the generation -- the two calls one One-click Resume costs."""
    fake_llm.queue(analysis_response(), json.dumps(make_resume_payload()))


def _identity_key(session: Session, listing_id: int) -> str:
    """The Listing Memory is keyed by identity, not by listing id -- and the normalization that
    produces it is ``domain/listing_identity.py``'s, not something a test should re-guess."""
    return jobs_repo.get_listing(session, listing_id).identity_key


@pytest.fixture(autouse=True)
def _clean_locks():
    one_click_service._locks.clear()
    yield
    one_click_service._locks.clear()


@pytest.fixture
def rendered(monkeypatch) -> list[str]:
    calls: list[str] = []

    async def _fake_render(resume, template=None):
        calls.append(resume.fullName)
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(one_click_service, "render_resume_pdf", _fake_render)
    return calls


@pytest.fixture
def profile(write_profile):
    return write_profile(make_profile())


def _row(posting: dict) -> tuple[JobListing, list[ListingSource]]:
    description = posting["description"]
    listing = JobListing(
        scan_id=0,  # replace_listings owns this
        identity_key=identity_key(posting["company"], posting["title"]),
        title=posting["title"],
        company=posting["company"],
        location=posting.get("location"),
        is_remote=bool(posting.get("is_remote")),
        description=description,
        description_word_count=len(description.split()),
        locale=posting.get("locale", "en"),
        visibility_score=posting.get("visibility_score", 50.0),
    )
    return listing, [ListingSource(listing_id=0, board="linkedin", url=posting["url"])]


@pytest.fixture
async def listings(client, test_db_engine) -> dict[str, int]:
    """The last Scan's two listings -- one long posting and one too short to tailor to.
    Returns ``{title: listing id}``."""
    with Session(test_db_engine) as session:
        scan = jobs_repo.start_scan(session, trigger="immediate")
        jobs_repo.replace_listings(
            session,
            scan_id=int(scan.id or 0),
            listings=[_row(LONG_POSTING), _row(SHORT_POSTING)],
        )
        for posting in (LONG_POSTING, SHORT_POSTING):
            # A Scan writes a memory for every job it SAW -- so the endpoints under test see
            # the same "already remembered, nothing generated yet" starting point they do in
            # production, not a listing whose memory row does not exist yet.
            jobs_repo.upsert_memory(
                session, identity_key(posting["company"], posting["title"]), status="new"
            )
        jobs_repo.finish_scan(
            session, scan, board_statuses={}, listings_found=2, listings_scored=0
        )
        session.commit()

    rows = (await client.get("/api/jobs/listings")).json()["listings"]
    assert len(rows) == 2, rows
    return {row["title"]: row["id"] for row in rows}


class TestOneClickHappyPath:
    async def test_it_answers_with_a_pdf_attachment(self, client, listings, profile, fake_llm, rendered):
        script_one_click(fake_llm)

        resp = await client.post(ONE_CLICK.format(id=listings["Senior Backend Engineer"]))

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.headers["content-disposition"] == (
            'attachment; filename="curriculo-acme-cloud-senior-backend-engineer.pdf"'
        )
        assert resp.content == b"%PDF-1.4 fake"

    async def test_the_proposal_is_approved_with_no_chat_session_and_so_is_the_resume(
        self, client, listings, profile, fake_llm, rendered, test_db_engine
    ):
        """The acceptance criterion in one place: the One-click is the ONE exception to "no
        Resume without an approved Improvement Proposal", and neither row belongs to a chat."""
        script_one_click(fake_llm)

        resp = await client.post(ONE_CLICK.format(id=listings["Senior Backend Engineer"]))
        assert resp.status_code == 200

        with Session(test_db_engine) as session:
            proposals = session.exec(select(ImprovementProposal)).all()
            versions = session.exec(select(ResumeVersion)).all()
            assert [(p.status, p.session_id) for p in proposals] == [("approved", None)]
            assert [v.session_id for v in versions] == [None]
            assert proposals[0].resume_version_id == versions[0].id

    async def test_the_listing_reports_it_has_a_one_click_resume_afterwards(
        self, client, listings, profile, fake_llm, rendered
    ):
        """``hasOneClickResume`` is what turns the detail's button into "Baixar PDF"/"Regerar"
        (ticket 13) -- it must flip on the very next read."""
        listing_id = listings["Senior Backend Engineer"]
        assert (await client.get(f"/api/jobs/listings/{listing_id}")).json()["hasOneClickResume"] is False
        script_one_click(fake_llm)

        assert (await client.post(ONE_CLICK.format(id=listing_id))).status_code == 200

        detail = (await client.get(f"/api/jobs/listings/{listing_id}")).json()
        assert detail["hasOneClickResume"] is True
        card = (await client.get("/api/jobs/listings")).json()["listings"]
        assert next(c for c in card if c["id"] == listing_id)["hasOneClickResume"] is True

    async def test_the_second_click_spends_no_llm_call(
        self, client, listings, profile, fake_llm, rendered
    ):
        listing_id = listings["Senior Backend Engineer"]
        script_one_click(fake_llm)
        assert (await client.post(ONE_CLICK.format(id=listing_id))).status_code == 200

        resp = await client.post(f"{ONE_CLICK.format(id=listing_id)}?regenerate=0")

        assert resp.status_code == 200
        assert resp.content == b"%PDF-1.4 fake"
        assert fake_llm.call_count == 2  # the FakeLlm would raise on an unscripted third call
        assert len(rendered) == 2

    async def test_regenerate_1_spends_a_new_generation(
        self, client, listings, profile, fake_llm, rendered, test_db_engine
    ):
        listing_id = listings["Senior Backend Engineer"]
        script_one_click(fake_llm)
        assert (await client.post(ONE_CLICK.format(id=listing_id))).status_code == 200
        script_one_click(fake_llm)

        resp = await client.post(f"{ONE_CLICK.format(id=listing_id)}?regenerate=1")

        assert resp.status_code == 200
        assert fake_llm.call_count == 4
        with Session(test_db_engine) as session:
            versions = session.exec(select(ResumeVersion)).all()
            assert len(versions) == 2
            memory = jobs_repo.get_memory(session, _identity_key(session, listing_id))
            assert memory.resume_version_id == max(int(v.id or 0) for v in versions)


class TestOneClickRefusals:
    async def test_a_short_posting_is_422_with_the_code_the_web_expects(
        self, client, listings, profile, fake_llm, rendered
    ):
        resp = await client.post(ONE_CLICK.format(id=listings["PHP Developer"]))

        assert resp.status_code == 422
        assert resp.json()["detail"] == "description_too_short"
        assert fake_llm.call_count == 0

    async def test_an_unknown_listing_is_404(self, client, listings, profile, fake_llm):
        resp = await client.post(ONE_CLICK.format(id=999999))

        assert resp.status_code == 404

    async def test_an_llm_failure_is_502_with_an_actionable_message_and_an_intact_memory(
        self, client, listings, profile, fake_llm, rendered, test_db_engine
    ):
        listing_id = listings["Senior Backend Engineer"]
        fake_llm.queue(RuntimeError("provider exploded"))

        resp = await client.post(ONE_CLICK.format(id=listing_id))

        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert "Não consegui gerar o currículo" in detail
        # Never the raw provider error, and never the 422's code either.
        assert "provider exploded" not in detail
        assert "description_too_short" not in detail

        with Session(test_db_engine) as session:
            memory = jobs_repo.get_memory(session, _identity_key(session, listing_id))
            assert memory.resume_version_id is None
            assert session.exec(select(ImprovementProposal)).all() == []
            assert session.exec(select(ResumeVersion)).all() == []
        assert (await client.get(f"/api/jobs/listings/{listing_id}")).json()["hasOneClickResume"] is False

    async def test_a_concurrent_click_is_409_with_a_readable_message(
        self, client, listings, profile, fake_llm, monkeypatch
    ):
        listing_id = listings["Senior Backend Engineer"]
        script_one_click(fake_llm)
        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow_render(resume, template=None):
            started.set()
            await release.wait()
            return b"%PDF-1.4 fake"

        monkeypatch.setattr(one_click_service, "render_resume_pdf", _slow_render)
        first = asyncio.create_task(client.post(ONE_CLICK.format(id=listing_id)))
        await started.wait()

        second = await client.post(ONE_CLICK.format(id=listing_id))

        assert second.status_code == 409
        assert "Já estou gerando o currículo desta vaga" in second.json()["detail"]
        release.set()
        assert (await first).status_code == 200

    async def test_the_llm_error_message_is_redacted(
        self, client, listings, profile, fake_llm, rendered
    ):
        """Every error body in this app goes through ``http_error``; the 502's does too, even
        though the copy it carries is written here rather than lifted from the exception."""
        secret = "sk-ant-fake-one-click-secret-0123456789abcdef"  # pragma: allowlist secret
        fake_llm.queue(RuntimeError(f"401 unauthorized for {secret}"))

        resp = await client.post(ONE_CLICK.format(id=listings["Senior Backend Engineer"]))

        assert resp.status_code == 502
        assert secret not in resp.text


class TestOpenInChat:
    async def test_it_creates_a_session_the_chat_can_rehydrate(self, client, listings):
        listing_id = listings["Senior Backend Engineer"]

        resp = await client.post(OPEN_IN_CHAT.format(id=listing_id))

        assert resp.status_code == 200
        session_id = resp.json()["sessionId"]

        body = (await client.get(f"/api/chat/sessions/{session_id}")).json()
        assert body["session"]["title"] == "Acme Cloud · Senior Backend Engineer"
        assert body["session"]["kind"] == "resume"
        assert body["session"]["jobDescription"] == LONG_POSTING["description"]
        assert body["session"]["locale"] == "en"
        # The rehydration shows the posting as the user's own message (spec Backend-5).
        assert [(m["role"], m["content"]) for m in body["messages"]] == [
            ("user", LONG_POSTING["description"])
        ]
        assert body["activeResume"] is None
        assert body["pendingProposal"] is None

    async def test_the_new_session_shows_up_in_the_resume_sidebar(self, client, listings):
        resp = await client.post(OPEN_IN_CHAT.format(id=listings["Senior Backend Engineer"]))
        session_id = resp.json()["sessionId"]

        sessions = (await client.get("/api/chat/sessions")).json()["sessions"]

        assert [s["id"] for s in sessions] == [session_id]
        assert sessions[0]["title"] == "Acme Cloud · Senior Backend Engineer"

    async def test_the_next_turn_treats_the_posting_as_a_job_and_proposes(
        self, client, listings, profile, fake_llm, parse_sse
    ):
        """The button's promise: the FULL flow, proposal reviewed. Sending the seeded posting
        routes to "generate" -> the Analysis -> a Pending Proposal, with no new path through
        the chat and nothing generated yet."""
        resp = await client.post(OPEN_IN_CHAT.format(id=listings["Senior Backend Engineer"]))
        session_id = resp.json()["sessionId"]
        fake_llm.queue(analysis_response())

        stream = await client.post(
            f"/api/chat/sessions/{session_id}/messages/stream",
            json={"message": LONG_POSTING["description"]},
        )

        assert stream.status_code == 200
        kinds = [e for e, _ in parse_sse(stream.text)]
        assert "proposal" in kinds
        assert "resume" not in kinds
        assert fake_llm.call_count == 1

        body = (await client.get(f"/api/chat/sessions/{session_id}")).json()
        assert body["pendingProposal"]["status"] == "proposed"

    async def test_it_spends_no_llm_call(self, client, listings, fake_llm):
        await client.post(OPEN_IN_CHAT.format(id=listings["Senior Backend Engineer"]))

        assert fake_llm.call_count == 0

    async def test_a_short_posting_may_still_be_opened(self, client, listings):
        """Only the One-click is refused on a thin posting -- the chat is exactly where the
        user goes to work around one."""
        resp = await client.post(OPEN_IN_CHAT.format(id=listings["PHP Developer"]))

        assert resp.status_code == 200

    async def test_an_unknown_listing_is_404(self, client, listings):
        assert (await client.post(OPEN_IN_CHAT.format(id=999999))).status_code == 404
