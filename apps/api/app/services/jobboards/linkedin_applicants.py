"""Applicant Band enrichment for LinkedIn postings (v7 ticket 04).

LinkedIn is the ONLY Job Board that says anything at all about competition, and it says it in
a form that is already a band rather than a number (CONTEXT.md: Applicant Band): an exact count
while it is small, "Over 100" once it is not, and "Be among the first 25" while it is brand
new. That is why ``ApplicantBand`` has exactly these buckets -- they are not a modelling
choice, they are the shape of what that one page can tell us.

The count is not in the search results, only on the public job page, so this is a SEPARATE
step: one extra GET per LinkedIn posting, after the search returned. Everything here is built
around that step being expendable --

* it never raises: every failure (timeout, 429, a redesigned page, a login wall) resolves to
  ``"unknown"``, which by contract never excludes a listing from the user's maximum-applicants
  filter and only scores neutrally in the Visibility Score;
* it never blocks the Scan on itself: a semaphore caps how many of these requests are in
  flight, because the fastest way to get the SEARCH blocked -- the part that actually matters
  -- is to follow it with fifty parallel page loads;
* it is honest about not knowing: ``None`` on a ``RawPosting`` means "this board has no such
  concept" and is what the other six boards leave behind; ``"unknown"`` means "we looked at
  LinkedIn and could not tell". Only this module may produce the second.
"""

from __future__ import annotations

import asyncio
import html as html_module
import logging
import re
from typing import Sequence
from urllib.parse import urlsplit

import httpx

from app.domain.schemas import ApplicantBand, RawPosting

logger = logging.getLogger(__name__)

# Short on purpose: this is a nice-to-have running after the search already succeeded. A
# LinkedIn page that takes longer than this is a page we do without.
DEFAULT_TIMEOUT_SECONDS = 6.0
# How many of these GETs may be in flight at once. The whole reason the module exists behind a
# semaphore -- see the module docstring.
DEFAULT_CONCURRENCY = 4

# Explicit and honest rather than blank or forged: an empty User-Agent is what gets a
# challenge page. ``Accept-Language`` pins the ENGLISH wording so the three forms below are the
# ones we actually parse; the Portuguese variants are still matched, because a geo-routed
# response can ignore the header.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# The three forms, in the order they MUST be tried: "Over 100 applicants" and "Be among the
# first 25 applicants" both contain "<number> applicants", so the bare form has to come last or
# it would swallow them and report "<100" for a posting with thousands of applicants.
_OVER_RE = re.compile(r"over\s+([\d.,]{1,9})\s+applicants?\b", re.IGNORECASE)
_FIRST_RE = re.compile(
    r"be\s+among\s+the\s+first\s+([\d.,]{1,9})\s+applicants?\b", re.IGNORECASE
)
_EXACT_RE = re.compile(r"([\d.,]{1,9})\s+applicants?\b", re.IGNORECASE)

# The same three, as LinkedIn writes them in pt-BR. Matched after the English ones and only as
# a fallback: the request asks for English, but a geo-routed page may answer in Portuguese and
# an "unknown" there would be a band we could have had.
_OVER_PT_RE = re.compile(r"mais\s+de\s+([\d.,]{1,9})\s+candidat", re.IGNORECASE)
_FIRST_PT_RE = re.compile(
    r"(?:entre|seja\s+um[ao]?\s+d[oa]s)\s+(?:os\s+)?([\d.,]{1,9})\s+primeir",
    re.IGNORECASE,
)
_EXACT_PT_RE = re.compile(
    r"([\d.,]{1,9})\s+candidat(?:o|a|os|as|ura|uras)\b", re.IGNORECASE
)


def _parse_count(raw: str) -> int | None:
    """"1,234" / "1.234" -> 1234. Both separators are thousands separators here (an applicant
    count is never fractional), so both are simply dropped."""
    digits = raw.replace(",", "").replace(".", "").strip()
    if not digits.isdigit():
        return None
    return int(digits)


def _band_below(count: int) -> ApplicantBand:
    """The band for "there are exactly ``count`` applicants".

    Bands are strict upper bounds, so the boundary belongs to the NEXT bucket: 24 applicants is
    ``<25``, 25 applicants is not -- it is ``<50``.
    """
    if count < 10:
        return "<10"
    if count < 25:
        return "<25"
    if count < 50:
        return "<50"
    if count < 100:
        return "<100"
    return "100+"


def _band_at_most(count: int) -> ApplicantBand:
    """The band for "there are FEWER than ``count`` applicants" -- LinkedIn's "be among the
    first 25", which is a ceiling, not a count. The ceiling lands on its own bucket: fewer than
    25 is exactly ``<25``."""
    if count <= 10:
        return "<10"
    if count <= 25:
        return "<25"
    if count <= 50:
        return "<50"
    if count <= 100:
        return "<100"
    return "100+"


def applicant_band_from_html(page_html: str | None) -> ApplicantBand | None:
    """The Applicant Band a LinkedIn job page states, or ``None`` when it states nothing.

    Tags are stripped and entities unescaped first, because the caption arrives as markup
    (``<span class="num-applicants__caption">Over 200 applicants</span>``) and LinkedIn is free
    to wrap the number in its own element tomorrow -- matching the rendered TEXT survives that,
    matching the markup does not.

    ``None`` (rather than ``"unknown"``) is deliberate: this function reports what the page
    said, and only the caller knows that having looked and found nothing is what ``"unknown"``
    means.
    """
    if not page_html:
        return None
    text = _WS_RE.sub(" ", html_module.unescape(_TAG_RE.sub(" ", page_html)))

    for pattern in (_OVER_RE, _OVER_PT_RE):
        match = pattern.search(text)
        if match:
            count = _parse_count(match.group(1))
            # "over N" means at least N+1 -- for LinkedIn's only real case, N=100, that is
            # "100+"; the generic arithmetic keeps a hypothetical "over 25" honest too.
            return _band_below(count + 1) if count is not None else None

    for pattern in (_FIRST_RE, _FIRST_PT_RE):
        match = pattern.search(text)
        if match:
            count = _parse_count(match.group(1))
            return _band_at_most(count) if count is not None else None

    for pattern in (_EXACT_RE, _EXACT_PT_RE):
        match = pattern.search(text)
        if match:
            count = _parse_count(match.group(1))
            return _band_below(count) if count is not None else None

    return None


def is_linkedin_url(url: str | None) -> bool:
    """Whether ``url`` points at linkedin.com. Guards the enrichment against being pointed at
    another board's posting by a future caller -- the parsing above is LinkedIn's wording and
    would be nonsense anywhere else."""
    if not url:
        return False
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "linkedin.com" or host.endswith(".linkedin.com")


async def fetch_applicant_band(
    url: str,
    *,
    client: httpx.AsyncClient,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ApplicantBand:
    """One posting's band. Always answers; ``"unknown"`` covers every way this can go wrong."""
    try:
        response = await client.get(
            url, headers=DEFAULT_HEADERS, timeout=timeout, follow_redirects=True
        )
    except Exception:  # noqa: BLE001 -- an expendable step may not fail the Scan
        logger.debug("linkedin applicant band: request failed", exc_info=True)
        return "unknown"
    if response.status_code != 200:
        # 429/999 (LinkedIn's own "go away") and a login wall all land here. Nothing to say:
        # the SEARCH is what reports Board Status, not this.
        logger.debug(
            "linkedin applicant band: status %s for a posting page", response.status_code
        )
        return "unknown"
    try:
        return applicant_band_from_html(response.text) or "unknown"
    except Exception:  # noqa: BLE001
        logger.debug("linkedin applicant band: parse failed", exc_info=True)
        return "unknown"


async def enrich_applicant_bands(
    postings: Sequence[RawPosting],
    *,
    client: httpx.AsyncClient | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[RawPosting]:
    """Return ``postings`` with every LinkedIn one carrying an Applicant Band.

    Postings that are not LinkedIn's pass through untouched (``applicant_band`` stays ``None``
    -- "this board has no such concept"). LinkedIn's always come back with a band, ``"unknown"``
    included.

    ``client`` is injectable so the Scan can reuse one connection pool -- and so tests can hand
    in an ``httpx.MockTransport`` instead of reaching the network. Without one, a client is
    opened and closed here.
    """
    if not postings:
        return list(postings)

    targets = [i for i, posting in enumerate(postings) if is_linkedin_url(posting.url)]
    if not targets:
        return list(postings)

    enriched = list(postings)
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _one(index: int, http: httpx.AsyncClient) -> None:
        async with semaphore:
            band = await fetch_applicant_band(enriched[index].url, client=http, timeout=timeout)
        enriched[index] = enriched[index].model_copy(update={"applicant_band": band})

    async def _run(http: httpx.AsyncClient) -> None:
        await asyncio.gather(
            *(_one(index, http) for index in targets), return_exceptions=True
        )

    try:
        if client is not None:
            await _run(client)
        else:
            async with httpx.AsyncClient(timeout=timeout) as owned:
                await _run(owned)
    except Exception:  # noqa: BLE001 -- the whole step is expendable, the postings are not
        logger.warning("linkedin applicant band enrichment failed wholesale", exc_info=True)
        return [
            posting.model_copy(update={"applicant_band": posting.applicant_band or "unknown"})
            if is_linkedin_url(posting.url)
            else posting
            for posting in postings
        ]

    # A gathered task that raised (it should not -- ``fetch_applicant_band`` swallows) would
    # leave its posting at ``None``; LinkedIn postings must never end at "no such concept".
    return [
        posting.model_copy(update={"applicant_band": "unknown"})
        if posting.applicant_band is None and is_linkedin_url(posting.url)
        else posting
        for posting in enriched
    ]


__all__ = [
    "DEFAULT_CONCURRENCY",
    "DEFAULT_HEADERS",
    "DEFAULT_TIMEOUT_SECONDS",
    "applicant_band_from_html",
    "enrich_applicant_bands",
    "fetch_applicant_band",
    "is_linkedin_url",
]
