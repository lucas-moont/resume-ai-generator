"""How FRESH a posting is, as a 0..1 number (v7 ticket 07).

One of the three terms of the Visibility Score (CONTEXT.md: Visibility Score) and the only one
ticket 07 computes -- Fit and the Applicant Band term arrive with ticket 08. Pure functions, no
I/O, no DB, no clock of their own: ``now`` is always passed in, so a Scan scores every listing
it found against ONE instant and a test never depends on the wall clock.

The curve is the spec's, verbatim (docs/v7-job-monitor.md, "Visibility Score"): **1.0 up to
24h, decaying linearly to 0 at 7 days**, and 0 from there on. Two consequences worth naming,
because both are deliberate:

* A posting with **no date** scores 0, the same as a week-old one. Boards that publish no date
  are common enough (see the feed adapters of ticket 05, which keep such postings rather than
  discarding them), and scoring an unknown date as fresh would let the least informative board
  outrank the most informative one. Costing it rank is the conservative failure.
* A **Repost** needs no special case here, even though CONTEXT.md says it "counts as new".
  Repost detection in the Scan engine is precisely "the same identity came back with a
  ``date_posted`` newer than the last time we saw it", so a Repost arrives holding a fresh date
  and this function scores that date. A flag that forced the score to 1.0 would be a second,
  weaker answer -- and it would score a Repost whose new date is already five days old as if it
  had been published this morning.
"""

from __future__ import annotations

from datetime import datetime, timezone

# Full marks below this age: a posting from the last day is as fresh as freshness gets, and
# splitting hairs between "two hours ago" and "twenty hours ago" would let the clock, not the
# job, decide the ranking.
FULL_SCORE_HOURS = 24.0
# Zero at seven days. Past it the recency term stops discriminating rather than going negative.
ZERO_SCORE_HOURS = 7 * 24.0


def as_utc(value: datetime | None) -> datetime | None:
    """A datetime as timezone-aware UTC, or ``None``.

    Needed because the two sides of every comparison in the Scan engine come from different
    places: a ``RawPosting.date_posted`` is aware UTC by contract, while the SAME instant read
    back out of SQLite is naive (SQLite has no native timezone-aware storage -- see
    ``app.db.tables._utcnow`` and the reaper's module docstring, which states the same rule).
    A naive value is therefore READ as UTC rather than as local time: that is what was written.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def hours_since(date_posted: datetime | None, now: datetime) -> float | None:
    """Age in hours, or ``None`` when the board reported no date. Negative ages (a board
    stamping a posting slightly in the future, or a clock skew) clamp to 0 -- "newer than now"
    is still just "brand new"."""
    posted = as_utc(date_posted)
    if posted is None:
        return None
    delta = (as_utc(now) - posted).total_seconds() / 3600.0
    return max(0.0, delta)


def recency_score(date_posted: datetime | None, now: datetime) -> float:
    """The recency term of the Visibility Score, in ``0.0..1.0``.

    ``1.0`` for anything posted within ``FULL_SCORE_HOURS``, then linear to ``0.0`` at
    ``ZERO_SCORE_HOURS``, then ``0.0``. ``None`` (no date) scores ``0.0`` -- see the module
    docstring for why that is the conservative answer rather than a neutral one.
    """
    age = hours_since(date_posted, now)
    if age is None:
        return 0.0
    if age <= FULL_SCORE_HOURS:
        return 1.0
    if age >= ZERO_SCORE_HOURS:
        return 0.0
    span = ZERO_SCORE_HOURS - FULL_SCORE_HOURS
    return (ZERO_SCORE_HOURS - age) / span
