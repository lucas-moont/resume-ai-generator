"""The Visibility Score (v7 ticket 08): the Job Monitor's one ranking key.

CONTEXT.md (Visibility Score) in a sentence: "a weighted blend of Fit Score, recency (Repost
counts as new) and Applicant Band -- higher means the resume is more likely to be READ". That
last word is the whole point of the module, and the reason it is not just the Fit Score sorted
descending: a perfect fit with three hundred applicants ranks below a good fit posted an hour
ago, because the question this score answers is not "how well do I match?" but "if I apply,
does anyone see it?".

Three normalized terms, blended by the weights in ``app.config``:

* **fit** -- ``fit_score / 100`` (``services/jobs/fit_service.py``);
* **recency** -- ``domain.recency.recency_score``, 1.0 up to 24h decaying to 0 at 7 days. A
  Repost needs no special case: it arrives holding a fresh ``date_posted``, which is precisely
  how it was detected;
* **competition** -- the Applicant Band, through ``config.APPLICANT_BAND_SCORE``.

Pure: no clock, no I/O, no DB. Both inputs that could come from a clock (recency) or a
database (the band) are passed in already resolved, so a Scan scores every listing it found
against one instant and a test never depends on the wall clock.

The one import that needs justifying: this is the first ``domain/`` module to read
``app.config``. The spec pins the weights and the band table to that file deliberately -- they
are the product's calibration knobs, not this function's private constants, and v7 explicitly
leaves them un-editable in the UI so there is exactly one place to change them. They are read
module-qualified at CALL time, so monkeypatching either table in a test takes effect without a
reload, and nothing about the function becomes impure: reading a constant is not I/O.
"""

from __future__ import annotations

import math

from app import config as config_module

# The band that means "no board told us" rather than a position on the crowding scale. Spelled
# here rather than imported from the Scan engine: this module is downstream of nothing.
UNKNOWN_BAND = "unknown"

# What an unrecognized (or absent) band scores. The same value ``unknown`` carries, and for the
# same reason: an unreadable band is not evidence of a crowd, so it must neither reward nor
# punish the listing.
NEUTRAL_COMPETITION = 0.5


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round_half_up(value: float) -> int:
    """Half-up, not Python's banker's rounding.

    ``round(0.5)`` is 0 and ``round(1.5)`` is 2 -- defensible for statistics, surprising for a
    score a user reads next to another score. A blend landing exactly on ``.5`` should always
    round the same direction, and up is the one a reader predicts.
    """
    return int(math.floor(value + 0.5))


def competition_score(band: str | None) -> float:
    """The competition term for one Applicant Band, in ``0.0..1.0``.

    ``None`` (a board with no such concept), ``unknown``, and any band the contract does not
    know all score ``NEUTRAL_COMPETITION``. That is the same rule the Applicant Band filter
    follows from the other side (``scan_service.passes_band_cap``): an absent number never
    counts against a listing, because "LinkedIn didn't say" is not "three hundred people
    applied".
    """
    table = config_module.APPLICANT_BAND_SCORE
    if band is None:
        return float(table.get(UNKNOWN_BAND, NEUTRAL_COMPETITION))
    return float(table.get(band, table.get(UNKNOWN_BAND, NEUTRAL_COMPETITION)))


def visibility_score(fit_0_100: float, recency_0_1: float, band: str | None) -> int:
    """The ranking key, ``0..100`` -- the SAME scale as the Fit Score.

    Sharing the scale is a contract decision (ticket 01, decision 2), not a coincidence: the two
    badges sit side by side on the listing card, so a reader must be able to see "fit 90,
    visibility 62" and understand that the gap is the queue.

    Both numeric inputs are clamped rather than validated. A Fit of 120 or a recency of -0.2
    means an upstream bug, and the honest failure for a RANKING function is to keep ranking
    (that listing simply sits at the top or the bottom of the range) rather than to raise
    mid-Scan and cost the user every other listing the Scan found.
    """
    weights = config_module.VISIBILITY_WEIGHTS
    fit = _clamp(float(fit_0_100), 0.0, 100.0) / 100.0
    recency = _clamp(float(recency_0_1), 0.0, 1.0)
    competition = _clamp(competition_score(band), 0.0, 1.0)
    blend = (
        float(weights.get("fit", 0.0)) * fit
        + float(weights.get("recency", 0.0)) * recency
        + float(weights.get("competition", 0.0)) * competition
    )
    return int(_clamp(_round_half_up(100.0 * blend), 0, 100))
