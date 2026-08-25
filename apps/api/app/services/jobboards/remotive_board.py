"""Remotive, through its public JSON API (v7 ticket 05).

The friendliest board of the seven: one documented endpoint, no key, no scraping, and a
``software-dev`` category that is already almost exactly what a Search Profile for tech asks
for. The catch is the budget -- Remotive's terms allow at most FOUR calls a day, which is why
``BOARD_SPECS`` gives it ``min_interval_hours=6`` and why this adapter makes exactly ONE HTTP
request per ``search()``, no matter how many roles the query carries. Everything the API cannot
narrow (target roles, ``hours_old``) is narrowed here, on the payload we already paid for.

Attribution note: the board's ``display_name`` beside every Listing Source link is not
decoration, it is what Remotive's API terms require of anyone republishing their listings.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime

import httpx

from app.domain.schemas import BoardQuery, BoardResult, RawPosting
from app.services.jobboards.feed_support import (
    DEFAULT_TIMEOUT_SECONDS,
    FeedFetchError,
    clean_one_line,
    fetch_text,
    html_to_text,
    is_fresh,
    newest_first,
    parse_iso_datetime,
    role_matcher,
    utc_now,
)
from app.services.jobboards.provider_registry import board_spec

REMOTIVE_API_URL = "https://remotive.com/api/remote-jobs"

# The one category that maps to this product. Remotive's other categories (design, sales,
# customer support) would only add postings the keyword Fit pass then throws away.
REMOTIVE_CATEGORY = "software-dev"

# How much wider than ``results_wanted`` to ask for when the roles are filtered locally: the
# category feed is a firehose and a 50-item page can easily contain 3 matching titles. Capped
# because the response is one JSON blob we parse in full.
_LOCAL_FILTER_OVERFETCH = 4
_MAX_LIMIT = 200


class RemotiveBoard:
    """``JobBoardProvider`` for Remotive.

    ``min_interval_hours`` comes from the catalog (6) rather than being written here twice; the
    registry refuses any adapter that tries to lower it.
    """

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        spec = board_spec("remotive")
        self.id = spec.id
        self.display_name = spec.display_name
        self.min_interval_hours = spec.min_interval_hours
        self._transport = transport
        self._timeout = timeout
        self._clock = clock

    def _params(self, query: BoardQuery) -> dict[str, str]:
        """The single request's query string.

        ``search`` is used only when the Search Profile names exactly ONE role. With several
        roles there is nothing sane to put there -- Remotive's ``search`` is one free-text
        string, and concatenating "backend engineer frontend developer" matches neither -- and
        splitting into one request per role would blow the four-calls-a-day budget in a single
        Scan. So: one role means a precise server-side query, many roles mean a wider page
        filtered here.
        """
        wanted = max(int(query.results_wanted or 0), 1)
        roles = [r.strip() for r in query.roles if isinstance(r, str) and r.strip()]
        params = {"category": REMOTIVE_CATEGORY}
        if len(roles) == 1:
            params["search"] = roles[0]
            params["limit"] = str(min(wanted, _MAX_LIMIT))
        else:
            params["limit"] = str(min(wanted * _LOCAL_FILTER_OVERFETCH, _MAX_LIMIT))
        return params

    def _to_posting(self, job: object) -> RawPosting | None:
        """One entry of ``jobs[]``, or ``None`` when it is not usable.

        A single malformed entry is skipped rather than failing the board: losing one posting
        is invisible, losing the whole board shows up as a red flag in the BoardStatusBar and
        costs the user a Scan against a 4-per-day budget.
        """
        if not isinstance(job, dict):
            return None
        title = clean_one_line(job.get("title"))
        company = clean_one_line(job.get("company_name"))
        url = job.get("url")
        if not title or not company or not isinstance(url, str) or not url.strip():
            return None
        return RawPosting(
            title=title,
            company=company,
            location=clean_one_line(job.get("candidate_required_location")) or None,
            # Every listing on Remotive is remote -- that is the entire premise of the board --
            # so this is a fact about the source, not a field we read.
            is_remote=True,
            url=url.strip(),
            description=html_to_text(job.get("description")),
            date_posted=parse_iso_datetime(job.get("publication_date")),
            # No board but LinkedIn exposes applicant counts; ``None`` says "this board has no
            # such concept", which is different from "we looked and could not tell".
            applicant_band=None,
        )

    async def search(self, query: BoardQuery) -> BoardResult:
        try:
            body = await fetch_text(
                REMOTIVE_API_URL,
                board_label=self.display_name,
                params=self._params(query),
                timeout=self._timeout,
                transport=self._transport,
            )
        except FeedFetchError as exc:
            return BoardResult(items=[], status=exc.status, message=exc.message)
        except Exception:
            # Belt and braces on top of the engine's own catch: an adapter reports, never
            # raises (base.JobBoardProvider.search).
            return BoardResult(
                items=[],
                status="error",
                message=f"Falha inesperada ao consultar {self.display_name}.",
            )

        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return BoardResult(
                items=[],
                status="error",
                message=f"{self.display_name} devolveu uma resposta que não é JSON.",
            )
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            return BoardResult(
                items=[],
                status="error",
                message=f"{self.display_name} devolveu um formato inesperado (sem lista `jobs`).",
            )

        matches_role = role_matcher(query.roles)
        now = self._clock()
        items = [
            posting
            for posting in (self._to_posting(job) for job in payload["jobs"])
            if posting is not None
            and matches_role(posting.title)
            and is_fresh(posting.date_posted, query.hours_old, now)
        ]
        return BoardResult(items=newest_first(items, query.results_wanted), status="ok")
