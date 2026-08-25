"""v7 ticket 05: the Remote OK adapter (``GET /api`` with an explicit User-Agent).

The three peculiarities this board forces on an adapter each get their own test: the legal
notice sitting in the first array slot, the 403 that answers a client with no User-Agent, and
the fact that Remote OK is not a tech-only board and offers no category parameter -- so the
``tags`` pass is the only thing between a Search Profile and a pile of design roles.

No network: ``httpx.MockTransport`` in the constructor, fixture read from disk, clock injected.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.domain.schemas import BoardQuery
from app.services.jobboards.provider_registry import BoardProviderRegistry
from app.services.jobboards.remoteok_board import RemoteOkBoard

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "jobboards"
NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def recording_transport(responder) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        outcome = responder(request)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return httpx.MockTransport(handler), seen


def json_transport(body: str, status: int = 200):
    return recording_transport(lambda _r: httpx.Response(status, text=body))


class RemoteOkTestCase(unittest.IsolatedAsyncioTestCase):
    def board(self, transport: httpx.MockTransport) -> RemoteOkBoard:
        return RemoteOkBoard(transport=transport, clock=lambda: NOW)


class TestParsesTheFixture(RemoteOkTestCase):
    async def test_keeps_the_dev_postings_and_nothing_else(self) -> None:
        transport, _ = json_transport(read_fixture("remoteok.json"))

        result = await self.board(transport).search(BoardQuery(hours_old=48))

        self.assertEqual(result.status, "ok")
        # Dropped, in order: the legal notice (no job), "Senior Product Designer" (no dev tag),
        # "Stale Corp" (a week old) and the entry with an empty ``position``.
        self.assertEqual(
            [(p.company, p.title) for p in result.items],
            [
                ("Meridian Data", "Senior Backend Engineer"),
                ("Untagged Works", "Backend Engineer"),
                ("Epoch Only Labs", "Frontend Developer"),
            ],
        )

    async def test_the_legal_notice_never_becomes_a_posting(self) -> None:
        transport, _ = json_transport(read_fixture("remoteok.json"))

        result = await self.board(transport).search(BoardQuery(hours_old=48))

        for posting in result.items:
            self.assertNotIn("Attribution is required", posting.description)
            self.assertTrue(posting.title)
            self.assertTrue(posting.company)

    async def test_maps_every_contract_field_of_a_posting(self) -> None:
        transport, _ = json_transport(read_fixture("remoteok.json"))

        result = await self.board(transport).search(BoardQuery(hours_old=48))
        posting = result.items[0]

        self.assertEqual(posting.title, "Senior Backend Engineer")
        self.assertEqual(posting.company, "Meridian Data")
        self.assertEqual(posting.location, "Worldwide")
        self.assertEqual(
            posting.url,
            "https://remoteok.com/remote-jobs/1088421-senior-backend-engineer-meridian-data",
        )
        self.assertTrue(posting.is_remote)
        self.assertEqual(posting.date_posted, datetime(2026, 8, 25, 11, 30, tzinfo=timezone.utc))
        self.assertIsNone(posting.applicant_band)

    async def test_falls_back_to_the_apply_url_when_there_is_no_url(self) -> None:
        transport, _ = json_transport(read_fixture("remoteok.json"))

        result = await self.board(transport).search(BoardQuery(hours_old=48))
        epoch_only = next(p for p in result.items if p.company == "Epoch Only Labs")

        self.assertEqual(epoch_only.url, "https://remoteok.com/remote-jobs/1088424-apply")

    async def test_falls_back_to_epoch_when_there_is_no_iso_date(self) -> None:
        transport, _ = json_transport(read_fixture("remoteok.json"))

        result = await self.board(transport).search(BoardQuery(hours_old=48))
        epoch_only = next(p for p in result.items if p.company == "Epoch Only Labs")

        self.assertEqual(
            epoch_only.date_posted, datetime(2026, 8, 24, 10, 20, tzinfo=timezone.utc)
        )

    async def test_description_is_clean_text_not_html(self) -> None:
        transport, _ = json_transport(read_fixture("remoteok.json"))

        result = await self.board(transport).search(BoardQuery(hours_old=48))
        description = result.items[0].description

        self.assertNotIn("<", description)
        self.assertNotIn("&amp;", description)
        self.assertIn("R&D tooling", description)
        self.assertIn("Python, FastAPI, PostgreSQL", description)

    async def test_returns_the_freshest_first_and_honours_results_wanted(self) -> None:
        transport, _ = json_transport(read_fixture("remoteok.json"))

        result = await self.board(transport).search(BoardQuery(hours_old=48, results_wanted=2))

        self.assertEqual([p.company for p in result.items], ["Meridian Data", "Untagged Works"])


class TestDevTagFilter(RemoteOkTestCase):
    async def test_a_non_technical_posting_is_dropped(self) -> None:
        transport, _ = json_transport(read_fixture("remoteok.json"))

        result = await self.board(transport).search(BoardQuery(hours_old=48))

        self.assertNotIn("Pastel Studio", [p.company for p in result.items])

    async def test_a_posting_with_no_tags_at_all_is_kept(self) -> None:
        transport, _ = json_transport(read_fixture("remoteok.json"))

        result = await self.board(transport).search(BoardQuery(hours_old=48))

        # Nothing to judge it on; the role filter downstream is the honest place to decide.
        self.assertIn("Untagged Works", [p.company for p in result.items])

    async def test_tag_matching_ignores_case_and_separators(self) -> None:
        body = (
            '[{"legal": "notice"},'
            '{"company": "Hyphen Co", "position": "Engineer", "tags": ["Front-End"],'
            ' "url": "https://remoteok.com/x", "date": "2026-08-25T11:00:00+00:00",'
            ' "description": "<p>hi</p>"}]'
        )
        transport, _ = json_transport(body)

        result = await self.board(transport).search(BoardQuery())

        self.assertEqual([p.company for p in result.items], ["Hyphen Co"])


class TestFiltering(RemoteOkTestCase):
    async def test_hours_old_drops_a_stale_posting(self) -> None:
        transport, _ = json_transport(read_fixture("remoteok.json"))

        result = await self.board(transport).search(BoardQuery(hours_old=24))

        self.assertNotIn("Stale Corp", [p.company for p in result.items])
        self.assertNotIn("Epoch Only Labs", [p.company for p in result.items])

    async def test_roles_filter_by_title(self) -> None:
        transport, _ = json_transport(read_fixture("remoteok.json"))

        result = await self.board(transport).search(
            BoardQuery(roles=["frontend developer"], hours_old=48)
        )

        self.assertEqual([p.company for p in result.items], ["Epoch Only Labs"])


class TestRequestShape(RemoteOkTestCase):
    async def test_sends_an_explicit_user_agent(self) -> None:
        transport, seen = json_transport(read_fixture("remoteok.json"))

        await self.board(transport).search(BoardQuery())

        # Remote OK answers 403 to a client with no (or a default library) User-Agent, so this
        # header is the difference between working and permanently ``blocked``.
        user_agent = seen[0].headers["user-agent"]
        self.assertIn("Agente-de-Curriculo", user_agent)
        self.assertNotIn("python-httpx", user_agent)

    async def test_asks_for_json(self) -> None:
        transport, seen = json_transport(read_fixture("remoteok.json"))

        await self.board(transport).search(BoardQuery())

        self.assertEqual(seen[0].headers["accept"], "application/json")

    async def test_makes_exactly_one_call(self) -> None:
        transport, seen = json_transport(read_fixture("remoteok.json"))

        await self.board(transport).search(BoardQuery(roles=["A", "B", "C"]))

        self.assertEqual(len(seen), 1)


class TestFailureIsReportedNeverRaised(RemoteOkTestCase):
    async def test_forbidden_is_blocked(self) -> None:
        transport, _ = json_transport("blocked by bot filter", status=403)

        result = await self.board(transport).search(BoardQuery())

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.items, [])
        self.assertIn("Remote OK", result.message or "")
        self.assertIn("403", result.message or "")

    async def test_rate_limited_is_blocked(self) -> None:
        transport, _ = json_transport("slow down", status=429)

        self.assertEqual((await self.board(transport).search(BoardQuery())).status, "blocked")

    async def test_server_error_is_error(self) -> None:
        transport, _ = json_transport("boom", status=502)

        result = await self.board(transport).search(BoardQuery())

        self.assertEqual(result.status, "error")
        self.assertIn("502", result.message or "")

    async def test_timeout_is_error_not_an_exception(self) -> None:
        transport, _ = recording_transport(
            lambda request: httpx.ReadTimeout("too slow", request=request)
        )

        result = await self.board(transport).search(BoardQuery())

        self.assertEqual(result.status, "error")
        self.assertNotIn("ReadTimeout", result.message or "")

    async def test_the_html_page_instead_of_the_api_is_error(self) -> None:
        transport, _ = json_transport("<!doctype html><html>remoteok</html>")

        result = await self.board(transport).search(BoardQuery())

        self.assertEqual(result.status, "error")
        self.assertIn("JSON", result.message or "")

    async def test_a_json_object_instead_of_a_list_is_error(self) -> None:
        transport, _ = json_transport('{"error": "nope"}')

        result = await self.board(transport).search(BoardQuery())

        self.assertEqual(result.status, "error")
        self.assertIn("lista", result.message or "")


class TestBoardIdentity(RemoteOkTestCase):
    async def test_identity_comes_from_the_catalog(self) -> None:
        board = RemoteOkBoard()

        self.assertEqual(board.id, "remoteok")
        self.assertEqual(board.display_name, "Remote OK")
        self.assertEqual(board.min_interval_hours, 1)

    async def test_the_registry_accepts_it(self) -> None:
        registry = BoardProviderRegistry([RemoteOkBoard()])

        self.assertIs(registry.get("remoteok").__class__, RemoteOkBoard)


if __name__ == "__main__":
    unittest.main()
