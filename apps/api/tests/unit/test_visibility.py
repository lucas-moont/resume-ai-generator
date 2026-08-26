"""Unit tests for the Visibility Score (v7 ticket 08) -- ``app/domain/visibility.py``.

A pure function, so these are a table: the three terms at their extremes, the decay the recency
term hands in (24h -> 7d, and a Repost arriving as a fresh date), every Applicant Band including
``unknown``, and the ordering property the whole Job Monitor rests on -- that the ranking answers
"will this be read?", not "how well do I match?".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import config as config_module
from app.domain.recency import recency_score
from app.domain.visibility import NEUTRAL_COMPETITION, competition_score, visibility_score

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


class TestCompetitionScore:
    @pytest.mark.parametrize(
        "band,expected",
        [
            ("<10", 1.0),
            ("<25", 0.9),
            ("<50", 0.75),
            ("<100", 0.5),
            ("100+", 0.1),
            ("unknown", 0.5),
        ],
    )
    def test_the_band_table_from_the_spec(self, band, expected):
        assert competition_score(band) == expected

    def test_an_absent_band_scores_neutral_not_zero(self):
        # CONTEXT.md (Applicant Band): an absent number is not evidence of a crowd. A board with
        # no such concept reports None; it must neither reward nor punish the listing.
        assert competition_score(None) == NEUTRAL_COMPETITION

    def test_a_band_the_contract_does_not_know_scores_neutral(self):
        assert competition_score("<7") == NEUTRAL_COMPETITION

    def test_the_scale_is_monotonic_from_least_to_most_crowded(self):
        bands = ["<10", "<25", "<50", "<100", "100+"]
        scores = [competition_score(b) for b in bands]
        assert scores == sorted(scores, reverse=True)


class TestVisibilityScore:
    def test_the_best_possible_listing_scores_100(self):
        assert visibility_score(100, 1.0, "<10") == 100

    def test_the_worst_possible_listing_still_scores_the_crowding_it_has(self):
        # Fit 0 and no date (recency 0). A literal zero would need a band worth 0, and ``100+``
        # is 0.1 rather than 0 on purpose: "over 100" covers 101 and 3000 alike, so it is still
        # a better queue than one nobody measured. 100*(0.20*0.1) = 2.
        assert visibility_score(0, 0.0, "100+") == 2

    @pytest.mark.parametrize(
        "fit,recency,band,expected",
        [
            # 100*(0.55*1.0 + 0.20*0.1) = 57 -- a perfect fit on a stale, crowded posting.
            (100, 0.0, "100+", 57),
            # 100*(0.25*1.0 + 0.20*1.0) = 45 -- a brand-new, empty queue with no fit at all.
            (0, 1.0, "<10", 45),
            # 100*(0.55*0.8 + 0.25*0.5 + 0.20*0.5) = 66.5, half-up.
            (80, 0.5, "unknown", 67),
            # 100*(0.55*0.6 + 0.25*1.0 + 0.20*0.9) = 76.
            (60, 1.0, "<25", 76),
        ],
    )
    def test_the_blend_is_the_specs_weighted_sum(self, fit, recency, band, expected):
        assert visibility_score(fit, recency, band) == expected

    def test_a_perfect_fit_in_a_crowd_ranks_below_a_good_fit_posted_an_hour_ago(self):
        # The sentence from CONTEXT.md (Visibility Score), as an assertion. This is the whole
        # reason the Monitor does not just sort by Fit.
        crowded = visibility_score(100, recency_score(ago(120), NOW), "100+")
        fresh = visibility_score(75, recency_score(ago(1), NOW), "<25")
        assert fresh > crowded

    def test_the_fit_term_outweighs_either_of_the_others_alone(self):
        # 0.55 > 0.25 and 0.55 > 0.20: Fit is the only term about the JOB.
        fit_only = visibility_score(100, 0.0, "unknown")
        queue_only = visibility_score(0, 1.0, "<10")
        assert fit_only > queue_only

    def test_the_result_is_an_int_on_the_same_scale_as_the_fit_score(self):
        value = visibility_score(73, 0.42, "<50")
        assert isinstance(value, int) and 0 <= value <= 100


class TestRecencyDecayThroughTheBlend:
    """The 24h -> 7d decay, seen through the score the user actually reads."""

    def test_anything_inside_24h_scores_the_same(self):
        one_hour = visibility_score(50, recency_score(ago(1), NOW), "<50")
        twenty_hours = visibility_score(50, recency_score(ago(20), NOW), "<50")
        assert one_hour == twenty_hours

    def test_the_score_decays_between_24h_and_7_days(self):
        scores = [
            visibility_score(50, recency_score(ago(h), NOW), "<50") for h in (24, 48, 96, 168)
        ]
        assert scores == sorted(scores, reverse=True)
        assert scores[0] > scores[-1]

    def test_past_7_days_it_stops_discriminating(self):
        assert visibility_score(50, recency_score(ago(168), NOW), "<50") == visibility_score(
            50, recency_score(ago(1000), NOW), "<50"
        )

    def test_a_posting_with_no_date_scores_as_the_oldest(self):
        assert visibility_score(50, recency_score(None, NOW), "<50") == visibility_score(
            50, recency_score(ago(400), NOW), "<50"
        )

    def test_a_repost_ranks_as_new_because_it_arrives_with_a_fresh_date(self):
        # There is no Repost flag in this function on purpose (domain/recency.py's docstring
        # says why): a Repost is DETECTED as a newer date_posted, so it simply scores as fresh.
        stale = visibility_score(50, recency_score(ago(200), NOW), "<50")
        reposted = visibility_score(50, recency_score(ago(2), NOW), "<50")
        assert reposted > stale


class TestOutOfRangeInputs:
    def test_a_fit_above_100_is_clamped_not_raised(self):
        # A ranking function that raises mid-Scan costs the user every OTHER listing too.
        assert visibility_score(400, 1.0, "<10") == visibility_score(100, 1.0, "<10")

    def test_a_negative_fit_is_clamped(self):
        assert visibility_score(-20, 0.0, "100+") == visibility_score(0, 0.0, "100+")

    def test_a_recency_outside_0_1_is_clamped(self):
        assert visibility_score(0, 5.0, "100+") == visibility_score(0, 1.0, "100+")
        assert visibility_score(0, -5.0, "100+") == visibility_score(0, 0.0, "100+")


class TestWeightsComeFromConfig:
    def test_a_reweighted_blend_takes_effect_without_a_reload(self, monkeypatch):
        # The weights are read module-qualified at call time precisely so the calibration the
        # spec defers ("calibrar após uso real") is a one-line change in config.py.
        monkeypatch.setattr(
            config_module,
            "VISIBILITY_WEIGHTS",
            {"fit": 1.0, "recency": 0.0, "competition": 0.0},
        )
        assert visibility_score(42, 1.0, "<10") == 42

    def test_a_missing_weight_reads_as_zero_rather_than_raising(self, monkeypatch):
        monkeypatch.setattr(config_module, "VISIBILITY_WEIGHTS", {"fit": 1.0})
        assert visibility_score(80, 1.0, "<10") == 80

    def test_the_band_table_is_config_too(self, monkeypatch):
        monkeypatch.setattr(config_module, "APPLICANT_BAND_SCORE", {"<10": 0.0, "unknown": 0.0})
        assert visibility_score(0, 0.0, "<10") == 0
