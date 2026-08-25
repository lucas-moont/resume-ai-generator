"""v7 ticket 05: the We Work Remotely adapter (category RSS feeds, ``xml.etree``).

Two fixtures, because the interesting behaviour of this board only exists across feeds: WWR
cross-lists the same job in the umbrella programming feed and in the specialised one, so
``guid`` dedup is what keeps a Scan from importing it twice. Tests drive a two-feed instance
(``feed_urls=...``) rather than the production four, so a failure names one feed exactly.

No network: ``httpx.MockTransport`` in the constructor, fixtures read from disk, clock injected.
"""

from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.domain.schemas import BoardQuery
from app.services.jobboards.provider_registry import BoardProviderRegistry
from app.services.jobboards.weworkremotely_board import WWR_FEED_URLS, WeWorkRemotelyBoard

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "jobboards"
NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)

PROGRAMMING_FEED = "https://weworkremotely.com/categories/remote-programming-jobs.rss"
BACK_END_FEED = "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss"
TWO_FEEDS = (PROGRAMMING_FEED, BACK_END_FEED)

FEED_FIXTURE_BY_URL = {
    PROGRAMMING_FEED: "weworkremotely-programming.rss",
    BACK_END_FEED: "weworkremotely-back-end.rss",
}


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


def feeds_transport(overrides: dict[str, object] | None = None):
    """Serves each fixture at its real URL. ``overrides`` replaces one feed's answer with a
    status code or an exception, which is how the partial-failure paths are driven."""
    replacements = overrides or {}

    def responder(request: httpx.Request):
        url = str(request.url)
        if url in replacements:
            outcome = replacements[url]
            if isinstance(outcome, BaseException):
                return outcome
            if isinstance(outcome, int):
                return httpx.Response(outcome, text="nope")
            return httpx.Response(200, text=str(outcome))
        name = FEED_FIXTURE_BY_URL.get(url)
        if name is None:
            return httpx.Response(404, text="unknown feed")
        return httpx.Response(200, text=read_fixture(name))

    return recording_transport(responder)


class WwrTestCase(unittest.IsolatedAsyncioTestCase):
    def board(
        self, transport: httpx.MockTransport, feed_urls: tuple[str, ...] = TWO_FEEDS
    ) -> WeWorkRemotelyBoard:
        return WeWorkRemotelyBoard(transport=transport, clock=lambda: NOW, feed_urls=feed_urls)


class TestParsesTheFixtures(WwrTestCase):
    async def test_reads_both_feeds_and_keeps_each_job_once(self) -> None:
        transport, seen = feeds_transport()

        result = await self.board(transport).search(BoardQuery(hours_old=48))

        self.assertEqual(len(seen), 2)
        self.assertEqual(result.status, "ok")
        self.assertIsNone(result.message)
        # "Hyperloop Labs" appears in BOTH feeds under the same guid and is imported once; the
        # item with no company separator is dropped; "Old Guard Software" is a week old.
        self.assertEqual(
            [(p.company, p.title) for p in result.items],
            [
                ("Hyperloop Labs", "Senior Backend Engineer (Go)"),
                ("Quiet Ledger", "Backend Engineer, Payments"),
                ("Bright Pixel", "Front-End Developer"),
            ],
        )

    async def test_splits_company_from_title_at_the_first_colon(self) -> None:
        transport, _ = feeds_transport()

        result = await self.board(transport).search(BoardQuery(hours_old=48))
        posting = result.items[0]

        self.assertEqual(posting.company, "Hyperloop Labs")
        self.assertEqual(posting.title, "Senior Backend Engineer (Go)")

    async def test_an_explicit_company_element_wins_over_the_title_split(self) -> None:
        transport, _ = feeds_transport()

        result = await self.board(transport).search(BoardQuery(hours_old=48))
        quiet_ledger = next(p for p in result.items if p.company == "Quiet Ledger")

        # The <company> element is authoritative, and the title still loses the company prefix
        # WWR writes into it -- but only because the prefix IS the company name.
        self.assertEqual(quiet_ledger.title, "Backend Engineer, Payments")

    async def test_an_unrelated_colon_in_the_title_does_not_become_the_company(self) -> None:
        item = ET.fromstring(
            "<item><title>Engineer, Platform: Payments</title>"
            "<company>Quiet Ledger</company>"
            "<link>https://weworkremotely.com/remote-jobs/x</link></item>"
        )

        company, title = WeWorkRemotelyBoard()._split_company_and_title(item)

        self.assertEqual(company, "Quiet Ledger")
        self.assertEqual(title, "Engineer, Platform: Payments")

    async def test_drops_an_item_whose_company_cannot_be_recovered(self) -> None:
        transport, _ = feeds_transport()

        result = await self.board(transport).search(BoardQuery(hours_old=48))

        # "A title with no company separator" is fresh and would otherwise pass every filter --
        # it is dropped because identity_key(company, title) needs a company side.
        self.assertNotIn(
            "A title with no company separator", [p.title for p in result.items]
        )
        self.assertNotIn("", [p.company for p in result.items])

    async def test_maps_every_contract_field_of_a_posting(self) -> None:
        transport, _ = feeds_transport()

        result = await self.board(transport).search(BoardQuery(hours_old=48))
        posting = result.items[0]

        self.assertEqual(
            posting.url,
            "https://weworkremotely.com/remote-jobs/hyperloop-labs-senior-backend-engineer-go",
        )
        # <region> is where remote is allowed FROM; it never makes the job on-site.
        self.assertEqual(posting.location, "Anywhere in the World")
        self.assertTrue(posting.is_remote)
        # RFC 822 pubDate -> aware UTC.
        self.assertEqual(
            posting.date_posted, datetime(2026, 8, 25, 10, 41, 7, tzinfo=timezone.utc)
        )
        self.assertIsNone(posting.applicant_band)

    async def test_description_is_clean_text_not_html(self) -> None:
        transport, _ = feeds_transport()

        result = await self.board(transport).search(BoardQuery(hours_old=48))
        description = result.items[0].description

        self.assertNotIn("<", description)
        self.assertNotIn("&amp;", description)
        self.assertIn("Headquarters: Lisbon, Portugal", description)
        self.assertIn("Design & ship services end to end", description)
        # &nbsp; and &euro; decoded.
        self.assertIn("Salary range: €70k-€95k.", description)

    async def test_returns_the_freshest_first_and_honours_results_wanted(self) -> None:
        transport, _ = feeds_transport()

        result = await self.board(transport).search(BoardQuery(hours_old=48, results_wanted=1))

        self.assertEqual([p.title for p in result.items], ["Senior Backend Engineer (Go)"])


class TestFiltering(WwrTestCase):
    async def test_hours_old_drops_a_stale_posting(self) -> None:
        transport, _ = feeds_transport()

        result = await self.board(transport).search(BoardQuery(hours_old=24))

        self.assertNotIn("Backend Engineer", [p.title for p in result.items])
        self.assertNotIn("Old Guard Software", [p.company for p in result.items])

    async def test_an_item_with_no_pubdate_survives_and_sorts_last(self) -> None:
        feed = (
            '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
            "<item><title>No Date Co: Backend Engineer</title>"
            "<link>https://weworkremotely.com/remote-jobs/no-date</link>"
            "<guid>https://weworkremotely.com/remote-jobs/no-date</guid>"
            "<description>no pubDate on this one</description></item>"
            "<item><title>Dated Co: Backend Engineer</title>"
            "<link>https://weworkremotely.com/remote-jobs/dated</link>"
            "<guid>https://weworkremotely.com/remote-jobs/dated</guid>"
            "<pubDate>Tue, 25 Aug 2026 11:00:00 +0000</pubDate>"
            "<description>dated</description></item>"
            "</channel></rss>"
        )
        transport, _ = feeds_transport({PROGRAMMING_FEED: feed, BACK_END_FEED: 404})

        result = await self.board(transport).search(BoardQuery(hours_old=1))

        # A dateless posting cannot be judged against the window, so it is kept -- and it sorts
        # behind every dated one, the same way it scores as the oldest bucket downstream.
        self.assertEqual([p.company for p in result.items], ["Dated Co", "No Date Co"])
        self.assertIsNone(result.items[-1].date_posted)

    async def test_roles_filter_by_title_case_insensitively(self) -> None:
        transport, _ = feeds_transport()

        result = await self.board(transport).search(
            BoardQuery(roles=["front end developer"], hours_old=48)
        )

        self.assertEqual([p.company for p in result.items], ["Bright Pixel"])


class TestPartialAndTotalFailure(WwrTestCase):
    async def test_one_broken_feed_still_returns_the_other_ones_jobs(self) -> None:
        transport, _ = feeds_transport({BACK_END_FEED: 500})

        result = await self.board(transport).search(BoardQuery(hours_old=48))

        # A Scan is partial, not failed -- and so is this board's own answer.
        self.assertEqual(result.status, "ok")
        self.assertIn("1 de 2", result.message or "")
        self.assertIn("Hyperloop Labs", [p.company for p in result.items])
        self.assertNotIn("Quiet Ledger", [p.company for p in result.items])

    async def test_every_feed_rate_limited_is_blocked(self) -> None:
        transport, _ = feeds_transport({PROGRAMMING_FEED: 429, BACK_END_FEED: 429})

        result = await self.board(transport).search(BoardQuery())

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.items, [])
        self.assertIn("We Work Remotely", result.message or "")

    async def test_a_site_wide_block_wins_over_a_plain_error(self) -> None:
        transport, _ = feeds_transport({PROGRAMMING_FEED: 500, BACK_END_FEED: 429})

        result = await self.board(transport).search(BoardQuery())

        # Reporting ``error`` here would tell the user to expect a bug fix; ``blocked`` tells
        # them the truth, which is "we try again next Scan".
        self.assertEqual(result.status, "blocked")

    async def test_every_feed_failing_with_a_server_error_is_error(self) -> None:
        transport, _ = feeds_transport({PROGRAMMING_FEED: 503, BACK_END_FEED: 503})

        result = await self.board(transport).search(BoardQuery())

        self.assertEqual(result.status, "error")

    async def test_timeout_on_every_feed_is_error_not_an_exception(self) -> None:
        timeout = httpx.ReadTimeout("too slow")
        transport, _ = feeds_transport({PROGRAMMING_FEED: timeout, BACK_END_FEED: timeout})

        result = await self.board(transport).search(BoardQuery())

        self.assertEqual(result.status, "error")
        self.assertNotIn("ReadTimeout", result.message or "")

    async def test_unparseable_xml_is_error_not_an_exception(self) -> None:
        broken = "<rss><channel><item><title>unclosed"
        transport, _ = feeds_transport({PROGRAMMING_FEED: broken, BACK_END_FEED: broken})

        result = await self.board(transport).search(BoardQuery())

        self.assertEqual(result.status, "error")
        self.assertIn("RSS", result.message or "")

    async def test_unparseable_xml_on_one_feed_only_degrades_that_feed(self) -> None:
        transport, _ = feeds_transport({BACK_END_FEED: "<rss><channel><item>"})

        result = await self.board(transport).search(BoardQuery(hours_old=48))

        self.assertEqual(result.status, "ok")
        self.assertIn("Hyperloop Labs", [p.company for p in result.items])


class TestBoardIdentity(WwrTestCase):
    async def test_identity_comes_from_the_catalog(self) -> None:
        board = WeWorkRemotelyBoard()

        self.assertEqual(board.id, "weworkremotely")
        self.assertEqual(board.display_name, "We Work Remotely")
        self.assertEqual(board.min_interval_hours, 1)

    async def test_production_reads_the_four_programming_categories(self) -> None:
        # WWR files a job under exactly one category, so the umbrella feed alone is not enough.
        self.assertEqual(len(WWR_FEED_URLS), 4)
        self.assertEqual(WeWorkRemotelyBoard()._feed_urls, WWR_FEED_URLS)
        for url in WWR_FEED_URLS:
            self.assertTrue(url.startswith("https://weworkremotely.com/categories/"))
            self.assertTrue(url.endswith(".rss"))

    async def test_the_registry_accepts_it(self) -> None:
        registry = BoardProviderRegistry([WeWorkRemotelyBoard()])

        self.assertIs(registry.get("weworkremotely").__class__, WeWorkRemotelyBoard)


if __name__ == "__main__":
    unittest.main()
