"""v7 ticket 05: the Remotive adapter (public JSON API, ``category=software-dev``).

No test here reaches the network: every one wires an ``httpx.MockTransport`` into the adapter's
constructor (the board's own seam -- see ``feed_support``) and answers from a fixture recorded
by hand in ``tests/fixtures/jobboards/``. The clock is injected too, so a fixture whose dates
are frozen in August 2026 keeps exercising ``hours_old`` forever instead of going stale.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.domain.schemas import BoardQuery
from app.services.jobboards.provider_registry import BoardProviderRegistry
from app.services.jobboards.remotive_board import RemotiveBoard

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "jobboards"

# Noon on the day the fixture was recorded: the two fresh postings are hours old, the "Legacy
# Systems" one is a week old.
NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def recording_transport(
    responder,
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    """A MockTransport plus the list of requests it saw, so a test can assert on the query
    string the adapter built (which is where Remotive's four-calls-a-day budget is spent)."""
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


class RemotiveTestCase(unittest.IsolatedAsyncioTestCase):
    def board(self, transport: httpx.MockTransport) -> RemotiveBoard:
        return RemotiveBoard(transport=transport, clock=lambda: NOW)


class TestParsesTheFixture(RemotiveTestCase):
    async def test_keeps_only_fresh_postings_matching_a_target_role(self) -> None:
        transport, _ = json_transport(read_fixture("remotive-software-dev.json"))

        result = await self.board(transport).search(
            BoardQuery(roles=["Backend Engineer", "Frontend Developer"], hours_old=48)
        )

        self.assertEqual(result.status, "ok")
        self.assertIsNone(result.message)
        # "DevOps Engineer" matches no target role; "Legacy Systems Ltda" is a week old; the
        # last entry has no company_name and cannot be identified.
        self.assertEqual(
            [(p.company, p.title) for p in result.items],
            [("Acme Cloud", "Senior Backend Engineer"), ("Nimbus Labs", "Frontend Developer (React)")],
        )

    async def test_maps_every_contract_field_of_a_posting(self) -> None:
        transport, _ = json_transport(read_fixture("remotive-software-dev.json"))

        result = await self.board(transport).search(BoardQuery(roles=["Backend Engineer"]))
        posting = result.items[0]

        self.assertEqual(posting.title, "Senior Backend Engineer")
        self.assertEqual(posting.company, "Acme Cloud")
        self.assertEqual(posting.location, "Worldwide")
        self.assertEqual(
            posting.url,
            "https://remotive.com/remote-jobs/software-dev/senior-backend-engineer-1912345",
        )
        # Remotive is a remote-only board: this is a fact about the source, not a parsed field.
        self.assertTrue(posting.is_remote)
        # Naive in the payload, aware UTC in the contract (ticket 01 decision 9).
        self.assertEqual(posting.date_posted, datetime(2026, 8, 25, 9, 12, 14, tzinfo=timezone.utc))
        # Only LinkedIn has applicant counts; ``None`` means "this board has no such concept".
        self.assertIsNone(posting.applicant_band)

    async def test_description_is_clean_text_not_html(self) -> None:
        transport, _ = json_transport(read_fixture("remotive-software-dev.json"))

        result = await self.board(transport).search(BoardQuery(roles=["Backend Engineer"]))
        description = result.items[0].description

        self.assertNotIn("<", description)
        self.assertNotIn("&amp;", description)
        self.assertNotIn("&nbsp;", description)
        # Entities decoded into the characters a Fit keyword pass and a PDF actually want.
        self.assertIn("R&D", description)
        self.assertIn("PostgreSQL schema design & migrations", description)
        # Structure survives: list items are separate lines, and the paragraph that follows a
        # </ul> does not weld onto the last bullet.
        self.assertIn("Comfortable with AWS\nApply by September 30.", description)
        # <br /> is a line break, not nothing.
        self.assertIn("September 30.\nNo agencies, please.", description)

    async def test_skips_a_malformed_entry_without_failing_the_board(self) -> None:
        transport, _ = json_transport(read_fixture("remotive-software-dev.json"))

        result = await self.board(transport).search(BoardQuery(hours_old=48))

        self.assertEqual(result.status, "ok")
        self.assertNotIn("", [p.company for p in result.items])
        # Everything fresh and identifiable, with no roles to filter by: 3 of the 5 entries.
        self.assertEqual(len(result.items), 3)

    async def test_returns_the_freshest_first_and_honours_results_wanted(self) -> None:
        transport, _ = json_transport(read_fixture("remotive-software-dev.json"))

        result = await self.board(transport).search(BoardQuery(hours_old=48, results_wanted=2))

        self.assertEqual(len(result.items), 2)
        self.assertEqual(
            [p.title for p in result.items], ["Senior Backend Engineer", "DevOps Engineer"]
        )


class TestFiltering(RemotiveTestCase):
    async def test_hours_old_drops_a_stale_posting(self) -> None:
        transport, _ = json_transport(read_fixture("remotive-software-dev.json"))

        # Only the 09:12 posting falls inside a 3h window ending at the frozen 12:00.
        result = await self.board(transport).search(BoardQuery(hours_old=3))

        self.assertEqual([p.title for p in result.items], ["Senior Backend Engineer"])

    async def test_no_roles_means_the_whole_category(self) -> None:
        transport, _ = json_transport(read_fixture("remotive-software-dev.json"))

        result = await self.board(transport).search(BoardQuery(roles=[], hours_old=48))

        self.assertIn("DevOps Engineer", [p.title for p in result.items])

    async def test_role_matching_ignores_case_separators_and_extra_words(self) -> None:
        transport, _ = json_transport(read_fixture("remotive-software-dev.json"))

        # "front-end developer" must find "Frontend Developer (React)"; "backend engineer" must
        # find "Senior Backend Engineer".
        result = await self.board(transport).search(
            BoardQuery(roles=["front-end DEVELOPER", "backend engineer"], hours_old=48)
        )

        self.assertEqual(
            sorted(p.title for p in result.items),
            ["Frontend Developer (React)", "Senior Backend Engineer"],
        )


class TestRequestShape(RemotiveTestCase):
    async def test_always_makes_exactly_one_call_whatever_the_roles(self) -> None:
        transport, seen = json_transport(read_fixture("remotive-software-dev.json"))

        await self.board(transport).search(
            BoardQuery(roles=["Backend Engineer", "Frontend Developer", "SRE"])
        )

        # Remotive's terms allow four calls a DAY; one call per role would blow that budget in
        # a single Scan (and is why min_interval_hours is 6).
        self.assertEqual(len(seen), 1)

    async def test_one_role_is_pushed_to_the_api_as_search(self) -> None:
        transport, seen = json_transport(read_fixture("remotive-software-dev.json"))

        await self.board(transport).search(BoardQuery(roles=["Backend Engineer"], results_wanted=25))

        params = seen[0].url.params
        self.assertEqual(params.get("category"), "software-dev")
        self.assertEqual(params.get("search"), "Backend Engineer")
        self.assertEqual(params.get("limit"), "25")

    async def test_several_roles_fetch_a_wider_page_and_filter_locally(self) -> None:
        transport, seen = json_transport(read_fixture("remotive-software-dev.json"))

        await self.board(transport).search(
            BoardQuery(roles=["Backend Engineer", "Frontend Developer"], results_wanted=25)
        )

        params = seen[0].url.params
        self.assertIsNone(params.get("search"))
        self.assertEqual(params.get("limit"), "100")

    async def test_sends_an_explicit_user_agent(self) -> None:
        transport, seen = json_transport(read_fixture("remotive-software-dev.json"))

        await self.board(transport).search(BoardQuery())

        self.assertIn("Agente-de-Curriculo", seen[0].headers["user-agent"])


class TestFailureIsReportedNeverRaised(RemotiveTestCase):
    async def test_rate_limited_is_blocked(self) -> None:
        transport, _ = json_transport("nope", status=429)

        result = await self.board(transport).search(BoardQuery())

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.items, [])
        self.assertIn("Remotive", result.message or "")
        self.assertIn("429", result.message or "")

    async def test_forbidden_is_blocked(self) -> None:
        transport, _ = json_transport("nope", status=403)

        self.assertEqual((await self.board(transport).search(BoardQuery())).status, "blocked")

    async def test_server_error_is_error(self) -> None:
        transport, _ = json_transport("boom", status=503)

        result = await self.board(transport).search(BoardQuery())

        self.assertEqual(result.status, "error")
        self.assertIn("503", result.message or "")

    async def test_timeout_is_error_not_an_exception(self) -> None:
        transport, _ = recording_transport(
            lambda request: httpx.ReadTimeout("too slow", request=request)
        )

        result = await self.board(transport).search(BoardQuery())

        self.assertEqual(result.status, "error")
        self.assertIn("Remotive", result.message or "")

    async def test_connection_failure_is_error(self) -> None:
        transport, _ = recording_transport(
            lambda request: httpx.ConnectError("no route", request=request)
        )

        self.assertEqual((await self.board(transport).search(BoardQuery())).status, "error")

    async def test_a_body_that_is_not_json_is_error(self) -> None:
        transport, _ = json_transport("<html>maintenance</html>")

        result = await self.board(transport).search(BoardQuery())

        self.assertEqual(result.status, "error")
        self.assertIn("JSON", result.message or "")

    async def test_json_without_a_jobs_list_is_error(self) -> None:
        transport, _ = json_transport('{"job-count": 0}')

        result = await self.board(transport).search(BoardQuery())

        self.assertEqual(result.status, "error")
        self.assertIn("jobs", result.message or "")

    async def test_no_message_ever_leaks_an_exception_repr(self) -> None:
        transport, _ = recording_transport(
            lambda request: httpx.ConnectError("no route to host", request=request)
        )

        message = (await self.board(transport).search(BoardQuery())).message or ""

        self.assertNotIn("ConnectError", message)
        self.assertNotIn("Traceback", message)


class TestBoardIdentity(RemotiveTestCase):
    async def test_declares_the_catalog_minimum_of_six_hours(self) -> None:
        board = RemotiveBoard()

        self.assertEqual(board.id, "remotive")
        self.assertEqual(board.display_name, "Remotive")
        # The terms-of-service floor (at most four calls a day), read from the catalog rather
        # than written here a second time.
        self.assertEqual(board.min_interval_hours, 6)

    async def test_the_registry_accepts_it(self) -> None:
        registry = BoardProviderRegistry([RemotiveBoard()])

        self.assertIs(registry.get("remotive").__class__, RemotiveBoard)


if __name__ == "__main__":
    unittest.main()
