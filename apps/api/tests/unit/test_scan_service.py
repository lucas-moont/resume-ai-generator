"""Unit tests for the pure decisions inside the Scan engine (v7 ticket 07).

Everything here is a function that neither touches the database nor calls a board: dedup and
Listing Source folding, the Applicant Band rules, Repost detection, the maximum-applicants
filter, the board query window, and the Board Status message hygiene. The end-to-end Scan --
lock, transaction, memory, scheduler -- is ``tests/integration/test_scan_engine.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.tables import ListingMemory
from app.domain.listing_identity import identity_key
from app.domain.schemas import BoardResult, RawPosting
from app.services.jobs import scan_service
from app.services.jobs.fit_service import FitOutcome
from app.services.jobs.scan_service import (
    BoardOutcome,
    ScanAlreadyRunning,
    _build_listing,
    _outcome_for,
    _ordered_statuses,
    _produced_evidence,
    _safe_message,
    _skipped_message,
    _smaller_band,
    description_hash,
    group_postings,
    hours_old_for,
    is_repost,
    passes_band_cap,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def posting(**kwargs) -> RawPosting:
    base = {
        "title": "Backend Engineer",
        "company": "Acme Tech",
        "url": "https://example.test/1",
        "description": "Python and FastAPI",
    }
    base.update(kwargs)
    return RawPosting(**base)


class _Board:
    """The two attributes ``_outcome_for`` reads off a provider."""

    def __init__(self, board_id: str = "linkedin") -> None:
        self.id = board_id


# --- The board query window --------------------------------------------------------------------


class TestHoursOldFor:
    def test_the_window_overlaps_the_interval_so_nothing_falls_between_two_scans(self):
        assert hours_old_for(24) == 48
        for interval in (1, 3, 6, 12, 24):
            assert hours_old_for(interval) >= interval * 2

    def test_a_short_interval_still_asks_for_a_full_day(self):
        # A 1h interval must not mean "only postings from the last two hours" after the app
        # has been closed overnight -- the floor wins under 12h.
        assert hours_old_for(1) == 24
        assert hours_old_for(3) == 24
        assert hours_old_for(6) == 24
        assert hours_old_for(12) == 24

    def test_scheduling_switched_off_still_gives_an_immediate_scan_a_window(self):
        assert hours_old_for(None) == 48


# --- Applicant Band ------------------------------------------------------------------------------


class TestSmallerBand:
    def test_the_smallest_known_band_across_sources_wins(self):
        assert _smaller_band("<100", "<25") == "<25"
        assert _smaller_band("<25", "<100") == "<25"

    def test_a_known_band_beats_unknown_in_either_order(self):
        assert _smaller_band("unknown", "<50") == "<50"
        assert _smaller_band("<50", "unknown") == "<50"

    def test_none_means_this_board_has_no_such_concept_and_never_wins(self):
        assert _smaller_band("<10", None) == "<10"

    def test_unknown_survives_only_when_nothing_knew_anything(self):
        assert _smaller_band("unknown", None) == "unknown"
        assert _smaller_band("unknown", "unknown") == "unknown"

    def test_the_most_crowded_band_is_still_a_band(self):
        assert _smaller_band("unknown", "100+") == "100+"
        assert _smaller_band("100+", "<10") == "<10"


class TestPassesBandCap:
    def test_no_cap_passes_everything(self):
        for band in ("<10", "<100", "100+", "unknown"):
            assert passes_band_cap(band, None) is True

    def test_a_cap_keeps_its_own_band_and_everything_below(self):
        assert passes_band_cap("<10", "<50") is True
        assert passes_band_cap("<50", "<50") is True

    def test_a_cap_excludes_the_crowded_ones(self):
        assert passes_band_cap("<100", "<50") is False
        assert passes_band_cap("100+", "<50") is False

    def test_unknown_never_excludes_a_listing(self):
        # CONTEXT.md (Applicant Band): an absent number is not evidence of a crowd.
        assert passes_band_cap("unknown", "<10") is True


# --- Dedup ---------------------------------------------------------------------------------------


class TestGroupPostings:
    def test_the_same_job_on_two_boards_is_one_listing_with_two_sources(self):
        groups = group_postings(
            [
                ("linkedin", posting(url="https://linkedin.test/1")),
                ("indeed", posting(company="AcmeTech Ltda.", url="https://indeed.test/1")),
            ]
        )
        assert len(groups) == 1
        assert [s.board for s in groups[0].sources] == ["linkedin", "indeed"]
        assert groups[0].key == identity_key("Acme Tech", "Backend Engineer")

    def test_two_different_jobs_stay_two_listings(self):
        groups = group_postings(
            [
                ("linkedin", posting(title="Backend Engineer")),
                ("linkedin", posting(title="Frontend Engineer", url="https://x.test/2")),
            ]
        )
        assert len(groups) == 2

    def test_the_longest_description_wins_because_it_feeds_fit_and_the_one_click_resume(self):
        groups = group_postings(
            [
                ("linkedin", posting(description="short")),
                ("indeed", posting(url="https://indeed.test/1", description="a much longer text")),
            ]
        )
        assert groups[0].description == "a much longer text"

    def test_a_board_that_returns_no_description_never_wins_the_field(self):
        groups = group_postings(
            [
                ("linkedin", posting(description="the real posting text")),
                ("indeed", posting(url="https://indeed.test/1", description="")),
            ]
        )
        assert groups[0].description == "the real posting text"

    def test_the_newest_date_across_sources_wins(self):
        groups = group_postings(
            [
                ("linkedin", posting(date_posted=ago(50))),
                ("indeed", posting(url="https://indeed.test/1", date_posted=ago(2))),
            ]
        )
        assert groups[0].date_posted == ago(2)

    def test_remote_is_true_when_any_board_says_so(self):
        groups = group_postings(
            [
                ("linkedin", posting(is_remote=False)),
                ("indeed", posting(url="https://indeed.test/1", is_remote=True)),
            ]
        )
        assert groups[0].is_remote is True

    def test_the_first_non_empty_location_is_kept(self):
        groups = group_postings(
            [
                ("linkedin", posting(location=None)),
                ("indeed", posting(url="https://indeed.test/1", location="São Paulo, SP")),
            ]
        )
        assert groups[0].location == "São Paulo, SP"

    def test_the_smallest_known_band_across_sources_becomes_the_listings_band(self):
        groups = group_postings(
            [
                ("linkedin", posting(applicant_band="100+")),
                ("indeed", posting(url="https://indeed.test/1", applicant_band=None)),
                ("google", posting(url="https://google.test/1", applicant_band="<25")),
            ]
        )
        assert groups[0].band == "<25"

    def test_each_source_keeps_what_its_own_board_reported(self):
        groups = group_postings(
            [
                ("linkedin", posting(applicant_band="100+", date_posted=ago(30))),
                ("indeed", posting(url="https://indeed.test/1", applicant_band=None)),
            ]
        )
        by_board = {s.board: s for s in groups[0].sources}
        assert by_board["linkedin"].applicant_band == "100+"
        assert by_board["indeed"].applicant_band == "unknown"
        assert by_board["linkedin"].date_posted == ago(30)

    def test_the_same_url_from_the_same_board_collapses_to_one_source(self):
        groups = group_postings([("linkedin", posting()), ("linkedin", posting())])
        assert len(groups[0].sources) == 1

    def test_the_same_url_from_two_boards_is_still_two_sources(self):
        # Two boards genuinely linking the same page is two places the user can apply from.
        groups = group_postings([("linkedin", posting()), ("indeed", posting())])
        assert len(groups[0].sources) == 2

    def test_a_posting_with_no_title_is_not_a_job(self):
        assert group_postings([("linkedin", posting(title="   "))]) == []

    def test_a_posting_with_no_url_is_not_a_job(self):
        assert group_postings([("linkedin", posting(url=""))]) == []

    def test_a_posting_with_no_company_still_becomes_a_listing(self):
        groups = group_postings([("linkedin", posting(company=""))])
        assert len(groups) == 1
        assert groups[0].company == ""

    def test_group_order_follows_the_order_the_postings_arrived(self):
        groups = group_postings(
            [
                ("linkedin", posting(title="B Role", url="https://x.test/b")),
                ("linkedin", posting(title="A Role", url="https://x.test/a")),
            ]
        )
        assert [g.title for g in groups] == ["B Role", "A Role"]


# --- Repost ---------------------------------------------------------------------------------------


def memory(**kwargs) -> ListingMemory:
    base = {
        "identity_key": "acmetech|backendengineer",
        "status": "new",
        "first_seen_at": ago(72),
        "last_seen_at": ago(48),
        "status_changed_at": ago(72),
    }
    base.update(kwargs)
    return ListingMemory(**base)


class TestIsRepost:
    def test_a_job_never_seen_before_is_new_not_a_repost(self):
        assert is_repost(None, ago(1)) is False

    def test_a_known_job_republished_since_we_last_looked_is_a_repost(self):
        assert is_repost(memory(last_seen_at=ago(48)), ago(2)) is True

    def test_the_same_old_posting_coming_back_is_not_a_repost(self):
        assert is_repost(memory(last_seen_at=ago(48)), ago(72)) is False

    def test_a_posting_with_no_date_cannot_be_shown_to_be_newer(self):
        assert is_repost(memory(), None) is False

    def test_a_naive_stored_last_seen_at_still_compares(self):
        # SQLite hands back naive UTC; the posting's date is aware. Without the coercion this
        # comparison would raise rather than answer.
        assert is_repost(memory(last_seen_at=ago(48).replace(tzinfo=None)), ago(2)) is True

    def test_exactly_last_seen_at_is_not_newer(self):
        assert is_repost(memory(last_seen_at=ago(10)), ago(10)) is False


# --- Building the listing row ------------------------------------------------------------------


class TestBuildListing:
    def _group(self, **kwargs):
        return group_postings([("linkedin", posting(**kwargs))])[0]

    def test_visibility_blends_recency_with_the_neutral_terms(self):
        # Ticket 08 replaced ticket 07's provisional "recency alone". A fresh posting with no
        # Fit and an unknown band scores 100*(0.25*1.0 + 0.20*0.5) = 35.
        listing, _ = _build_listing(self._group(date_posted=ago(1)), None, now=NOW)
        assert listing.visibility_score == 35.0

    def test_an_old_posting_ranks_at_the_bottom(self):
        # Only the neutral competition term is left: 100*(0.20*0.5) = 10.
        listing, _ = _build_listing(self._group(date_posted=ago(300)), None, now=NOW)
        assert listing.visibility_score == 10.0

    def test_a_scored_listing_outranks_an_equally_fresh_unscored_one(self):
        fit = FitOutcome(score=90, estimated=False, source="llm", description_hash="h")
        scored, _ = _build_listing(self._group(date_posted=ago(1)), None, fit=fit, now=NOW)
        unscored, _ = _build_listing(self._group(date_posted=ago(1)), None, now=NOW)
        assert scored.visibility_score > unscored.visibility_score

    def test_no_fit_is_claimed_when_the_memory_has_none(self):
        listing, _ = _build_listing(self._group(), None, now=NOW)
        assert listing.fit_score == 0
        # True since ticket 08: ``fit_estimated`` carries one meaning -- "this is not a real Fit
        # Score" -- so that ``listings_scored`` can simply count the false ones. A 0 nobody
        # computed is exactly what the flag is for; ticket 07 read it as "nothing estimated it".
        assert listing.fit_estimated is True

    def test_the_fit_from_this_scan_lands_on_the_row(self):
        fit = FitOutcome(score=64, estimated=True, source="keyword", description_hash="h")
        listing, _ = _build_listing(self._group(), None, fit=fit, now=NOW)
        assert (listing.fit_score, listing.fit_estimated) == (64, True)

    def test_a_fit_already_paid_for_is_reattached_from_the_memory(self):
        listing, _ = _build_listing(self._group(), memory(fit_score=78), now=NOW)
        assert listing.fit_score == 78
        assert listing.fit_estimated is False

    def test_the_description_word_count_is_precomputed_for_the_card(self):
        listing, _ = _build_listing(self._group(description="one two three"), None, now=NOW)
        assert listing.description_word_count == 3

    def test_the_postings_own_language_is_detected_not_the_uis(self):
        pt = self._group(
            description="Buscamos uma pessoa desenvolvedora com experiência em Python "
            "para atuar na nossa equipe; requisitos e responsabilidades no anúncio."
        )
        listing, _ = _build_listing(pt, None, now=NOW)
        assert listing.locale == "pt-BR"

    def test_an_english_posting_resolves_to_en(self):
        en = self._group(
            description="We are looking for a backend engineer with strong experience in "
            "Python; the role requires knowledge of our team's best practices."
        )
        listing, _ = _build_listing(en, None, now=NOW)
        assert listing.locale == "en"

    def test_the_repost_flag_lands_on_the_row(self):
        listing, repost = _build_listing(
            self._group(date_posted=ago(1)), memory(last_seen_at=ago(48)), now=NOW
        )
        assert repost is True and listing.is_repost is True


# --- Board outcomes ------------------------------------------------------------------------------


class TestOutcomeFor:
    def test_a_normal_result_becomes_ok_with_a_count(self):
        _, outcome, items = _outcome_for(_Board(), BoardResult(items=[posting()], status="ok"))
        assert (outcome.status, outcome.count, len(items)) == ("ok", 1, 1)

    def test_items_are_kept_even_from_a_board_that_reported_blocked(self):
        # Ticket 04 decision 3: a board refused partway through still returns what it found.
        _, outcome, items = _outcome_for(
            _Board(), BoardResult(items=[posting()], status="blocked", message="429")
        )
        assert outcome.status == "blocked"
        assert len(items) == 1

    def test_an_adapter_that_raises_only_fails_its_own_board(self):
        _, outcome, items = _outcome_for(_Board("indeed"), RuntimeError("boom"))
        assert (outcome.board, outcome.status, items) == ("indeed", "error", [])
        assert "RuntimeError" in outcome.message

    def test_an_adapter_returning_nonsense_is_an_error_not_a_crash(self):
        _, outcome, items = _outcome_for(_Board(), {"items": []})
        assert outcome.status == "error" and items == []


class TestSafeMessage:
    def test_a_url_never_reaches_the_user(self):
        assert "[url]" in _safe_message("failed on https://x.test/a?token=1", fallback="f")
        assert "x.test" not in _safe_message("failed on https://x.test/a", fallback="f")

    def test_whitespace_collapses(self):
        assert _safe_message("a\n\n  b", fallback="f") == "a b"

    def test_an_empty_message_becomes_the_fallback(self):
        assert _safe_message("   ", fallback="algo deu errado") == "algo deu errado"

    def test_a_long_message_is_capped(self):
        assert len(_safe_message("x" * 5000, fallback="f")) <= 200


class TestSkippedMessage:
    def test_it_names_the_minimum_and_how_long_ago_the_board_answered(self):
        message = _skipped_message(6, timedelta(hours=2))
        assert "6h" in message and "2h" in message

    def test_it_is_in_portuguese_like_every_other_board_status_message(self):
        assert "Intervalo mínimo" in _skipped_message(6, timedelta(hours=1))


class TestProducedEvidence:
    def test_one_board_answering_is_enough(self):
        assert _produced_evidence([BoardOutcome("linkedin", "ok", None, 3)]) is True

    def test_an_ok_board_with_zero_results_still_counts_as_evidence(self):
        # "We looked and there is nothing new" is a real answer about the job market.
        assert _produced_evidence([BoardOutcome("linkedin", "ok", None, 0)]) is True

    def test_every_board_blocked_is_evidence_about_the_boards_not_the_market(self):
        assert (
            _produced_evidence(
                [BoardOutcome("linkedin", "blocked", "429", 0), BoardOutcome("indeed", "error")]
            )
            is False
        )

    def test_a_blocked_board_that_still_returned_items_counts(self):
        assert _produced_evidence([BoardOutcome("linkedin", "blocked", "429", 5)]) is True

    def test_a_skipped_board_is_not_evidence_of_anything(self):
        assert _produced_evidence([BoardOutcome("remotive", "skipped", "cedo demais", 0)]) is False


class TestOrderedStatuses:
    def test_the_map_is_written_in_catalog_order(self):
        ordered = _ordered_statuses(
            {
                "remoteok": BoardOutcome("remoteok", "ok", None, 1),
                "linkedin": BoardOutcome("linkedin", "blocked", "429", 0),
            }
        )
        assert list(ordered) == ["linkedin", "remoteok"]

    def test_every_entry_carries_status_message_and_count(self):
        ordered = _ordered_statuses({"indeed": BoardOutcome("indeed", "error", "quebrou", 0)})
        assert ordered["indeed"] == {"status": "error", "message": "quebrou", "count": 0}


class TestDescriptionHash:
    def test_the_same_text_hashes_the_same(self):
        assert description_hash("abc") == description_hash("abc")

    def test_different_text_hashes_differently(self):
        assert description_hash("abc") != description_hash("abd")

    def test_an_empty_description_still_has_a_hash(self):
        assert len(description_hash("")) == 64


class TestScanAlreadyRunning:
    def test_it_carries_the_scan_when_there_is_one(self):
        class _Scan:
            id = 7

        e = ScanAlreadyRunning(_Scan())
        assert e.scan_id == 7 and "7" in str(e)

    def test_it_survives_having_no_scan_to_carry(self):
        e = ScanAlreadyRunning(None)
        assert e.scan_id is None and "already running" in str(e)


def test_the_module_never_reaches_a_board_or_an_llm_by_itself():
    # Guard the seam: the engine gets its adapters handed to it, it never builds them.
    source = (scan_service.__file__ or "").replace("\\", "/")
    text = open(source, encoding="utf-8").read()
    assert "httpx" not in text
    assert "llm_client" not in text
    assert "default_registry" not in text
