"""v7 ticket 05: ``feed_providers()`` and the machinery the three feed adapters share.

The factory is small but load-bearing: it is what a Scan hands to ``BoardProviderRegistry``, so
"the three feed boards are all wired and all satisfy the Protocol" is asserted here once
instead of being discovered when a Scan quietly runs four boards instead of seven.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import httpx

from app.services.jobboards.feed_providers import feed_providers
from app.services.jobboards.feed_support import (
    html_to_text,
    is_fresh,
    role_matcher,
)
from app.services.jobboards.provider_registry import BoardProviderRegistry, board_spec

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


class TestFeedProviders(unittest.TestCase):
    def test_returns_the_three_feed_boards_in_catalog_order(self) -> None:
        self.assertEqual(
            [p.id for p in feed_providers()], ["remotive", "weworkremotely", "remoteok"]
        )

    def test_each_board_matches_its_catalog_spec(self) -> None:
        for provider in feed_providers():
            spec = board_spec(provider.id)
            self.assertEqual(provider.display_name, spec.display_name)
            self.assertEqual(provider.min_interval_hours, spec.min_interval_hours)

    def test_the_registry_accepts_all_three(self) -> None:
        registry = BoardProviderRegistry(feed_providers())

        self.assertEqual(len(registry), 3)
        self.assertEqual(registry.ids(), ("remotive", "weworkremotely", "remoteok"))

    def test_a_shared_transport_reaches_every_board(self) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(200, text="[]"))

        for provider in feed_providers(transport=transport):
            self.assertIs(provider._transport, transport)  # type: ignore[attr-defined]

    def test_production_construction_takes_no_arguments(self) -> None:
        # No key, no optional dependency, no config: the feed half of v7 can always be built,
        # which is exactly why it is a separate factory from ticket 04's JobSpy providers.
        self.assertEqual(len(feed_providers()), 3)


class TestSharedFiltering(unittest.TestCase):
    """The two decisions every adapter delegates to ``feed_support``, asserted directly
    because their edge cases (a dateless posting, an empty role list) are the ones a recorded
    fixture cannot express."""

    def test_a_posting_with_no_date_survives_the_freshness_window(self) -> None:
        # Dropping it would let a board that stopped publishing dates go silently empty;
        # keeping it only costs rank, since a dateless posting already scores as the oldest
        # bucket in the Visibility Score.
        self.assertTrue(is_fresh(None, hours_old=1, now=NOW))

    def test_freshness_is_inclusive_at_the_edge_of_the_window(self) -> None:
        self.assertTrue(is_fresh(NOW - timedelta(hours=24), hours_old=24, now=NOW))
        self.assertFalse(is_fresh(NOW - timedelta(hours=24, seconds=1), hours_old=24, now=NOW))

    def test_a_future_date_is_fresh(self) -> None:
        self.assertTrue(is_fresh(NOW + timedelta(hours=2), hours_old=1, now=NOW))

    def test_no_roles_matches_every_title(self) -> None:
        matches = role_matcher([])

        self.assertTrue(matches("Senior Backend Engineer"))
        self.assertTrue(matches("Head of Sales"))

    def test_a_role_matches_a_title_with_extra_words_in_any_order(self) -> None:
        matches = role_matcher(["Backend Engineer"])

        self.assertTrue(matches("Senior Backend Engineer, Payments"))
        self.assertTrue(matches("Engineer, Backend"))
        self.assertFalse(matches("Frontend Developer"))

    def test_separators_and_accents_do_not_break_a_match(self) -> None:
        matches = role_matcher(["Front-End Developer"])

        self.assertTrue(matches("Front End Developer"))
        self.assertTrue(matches("FrontEnd Developer"))
        self.assertTrue(matches("frontend developer"))

    def test_a_blank_role_is_ignored_rather_than_matching_everything(self) -> None:
        matches = role_matcher(["   ", "Backend Engineer"])

        self.assertFalse(matches("Product Designer"))


class TestHtmlToText(unittest.TestCase):
    def test_empty_and_missing_html_become_an_empty_string(self) -> None:
        self.assertEqual(html_to_text(None), "")
        self.assertEqual(html_to_text(""), "")
        self.assertEqual(html_to_text("   "), "")

    def test_tags_never_survive(self) -> None:
        text = html_to_text("<p>Hello <strong>world</strong></p><a href='#'>link</a>")

        self.assertNotIn("<", text)
        self.assertIn("Hello world", text)
        self.assertIn("link", text)

    def test_a_script_body_does_not_come_back_as_markup(self) -> None:
        # Whatever bleach does with the tag, the result must be TEXT: nothing downstream may
        # hand this field to innerHTML, and nothing here may produce a live tag.
        text = html_to_text("<p>before</p><script>alert('x')</script><p>after</p>")

        self.assertNotIn("<script", text)
        self.assertIn("before", text)
        self.assertIn("after", text)

    def test_entities_are_decoded(self) -> None:
        self.assertEqual(html_to_text("<p>R&amp;D &gt; sales &nbsp;always</p>"), "R&D > sales always")

    def test_runs_of_blank_lines_collapse_to_one(self) -> None:
        text = html_to_text("<p>a</p><p></p><p></p><p></p><p>b</p>")

        self.assertNotIn("\n\n\n", text)
        self.assertTrue(text.startswith("a"))
        self.assertTrue(text.endswith("b"))


if __name__ == "__main__":
    unittest.main()
