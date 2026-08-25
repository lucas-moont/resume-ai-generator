"""Unit tests for ``app/domain/recency.py`` (v7 ticket 07) -- the recency term of the
Visibility Score, and the UTC coercion every time comparison in the Scan engine depends on."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.recency import (
    FULL_SCORE_HOURS,
    ZERO_SCORE_HOURS,
    as_utc,
    hours_since,
    recency_score,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


class TestAsUtc:
    def test_none_stays_none(self):
        assert as_utc(None) is None

    def test_a_naive_datetime_is_read_as_utc_not_as_local_time(self):
        naive = datetime(2026, 8, 25, 12, 0)
        assert as_utc(naive) == NOW

    def test_an_aware_datetime_is_converted_not_relabelled(self):
        # 09:00 at UTC-3 is 12:00 UTC -- the instant must survive, not the wall-clock reading.
        other = datetime(2026, 8, 25, 9, 0, tzinfo=timezone(timedelta(hours=-3)))
        assert as_utc(other) == NOW

    def test_an_already_utc_datetime_is_unchanged(self):
        assert as_utc(NOW) == NOW


class TestHoursSince:
    def test_no_date_has_no_age(self):
        assert hours_since(None, NOW) is None

    def test_age_is_measured_in_hours(self):
        assert hours_since(ago(5), NOW) == pytest.approx(5.0)

    def test_a_naive_stored_timestamp_compares_against_an_aware_now(self):
        # The pairing the Scan engine actually makes: SQLite hands back naive UTC.
        naive_five_hours_ago = ago(5).replace(tzinfo=None)
        assert hours_since(naive_five_hours_ago, NOW) == pytest.approx(5.0)

    def test_a_future_date_clamps_to_zero_rather_than_going_negative(self):
        assert hours_since(NOW + timedelta(hours=3), NOW) == 0.0


class TestRecencyScore:
    def test_a_posting_from_this_hour_scores_full_marks(self):
        assert recency_score(ago(1), NOW) == 1.0

    def test_the_full_score_holds_all_the_way_to_the_24h_edge(self):
        assert recency_score(ago(FULL_SCORE_HOURS), NOW) == 1.0

    def test_a_posting_with_no_date_scores_zero_not_neutral(self):
        # Deliberate: an unknown date must not let the least informative board outrank the
        # most informative one.
        assert recency_score(None, NOW) == 0.0

    def test_it_decays_linearly_between_one_day_and_seven(self):
        # Halfway through the 24h..168h window is exactly half a point.
        midpoint = (FULL_SCORE_HOURS + ZERO_SCORE_HOURS) / 2
        assert recency_score(ago(midpoint), NOW) == pytest.approx(0.5)

    def test_it_reaches_zero_at_seven_days(self):
        assert recency_score(ago(ZERO_SCORE_HOURS), NOW) == 0.0

    def test_anything_older_than_seven_days_stays_at_zero(self):
        assert recency_score(ago(ZERO_SCORE_HOURS + 500), NOW) == 0.0

    def test_it_is_monotonic_as_a_posting_ages(self):
        ages = [0, 6, 24, 25, 48, 96, 167, 168, 400]
        scores = [recency_score(ago(a), NOW) for a in ages]
        assert scores == sorted(scores, reverse=True)

    def test_every_score_stays_inside_the_unit_interval(self):
        for age in (-10, 0, 1, 24, 100, 168, 10_000):
            assert 0.0 <= recency_score(ago(age), NOW) <= 1.0

    def test_a_repost_needs_no_flag_because_its_new_date_is_the_freshness(self):
        # CONTEXT.md says a Repost counts as new; detection is "came back with a NEWER
        # date_posted", so the fresh date it arrives with is what scores.
        stale_original = recency_score(ago(200), NOW)
        reposted = recency_score(ago(2), NOW)
        assert stale_original == 0.0
        assert reposted == 1.0
