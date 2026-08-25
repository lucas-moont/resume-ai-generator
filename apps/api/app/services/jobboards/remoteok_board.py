"""Remote OK, through its public ``/api`` JSON endpoint (v7 ticket 05).

Three things are peculiar to this board and all three are load-bearing:

* **It refuses an anonymous client.** Remote OK answers 403 to a request with no (or a default
  library) ``User-Agent``. ``feed_support.fetch_text`` always sends ours, so a 403 here means a
  real block and correctly reports ``blocked`` rather than looking like a bug.
* **The first element of the array is not a job.** It is the legal notice ("commercial use
  requires..."), and it is the reason attribution beside every Listing Source link is a term of
  use, not a nicety. We drop any element carrying a ``legal`` key.
* **It is not a tech-only board.** Remote OK lists design, sales and support roles in the same
  array, and unlike Remotive there is no category parameter to narrow it. The narrowing is
  ``tags``, which every listing carries -- see ``_is_dev_posting``.
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
    parse_epoch,
    parse_iso_datetime,
    role_matcher,
    utc_now,
)
from app.services.jobboards.provider_registry import board_spec

REMOTEOK_API_URL = "https://remoteok.com/api"

# Tags that mean "this is a software engineering job". Compared after the same normalization
# the tags themselves get (lowercased, non-alphanumerics removed), so "front-end", "Front End"
# and "frontend" are one entry.
#
# The list is deliberately broad and deliberately a CLOSED vocabulary, never a heuristic: the
# asymmetry is that an over-inclusive tag costs one card the keyword Fit pass will score near
# zero, while a missing tag makes a real job invisible to the whole product.
_DEV_TAGS_RAW = (
    "dev", "developer", "engineer", "engineering", "software", "programming", "coding",
    "backend", "back end", "frontend", "front end", "fullstack", "full stack", "web dev",
    "mobile", "android", "ios", "react native", "flutter",
    "api", "microservices", "graphql", "sql", "nosql", "postgres", "postgresql", "mysql",
    "mongodb", "redis", "database",
    "devops", "sre", "infrastructure", "infra", "cloud", "aws", "gcp", "azure", "kubernetes",
    "docker", "terraform", "linux", "sysadmin", "platform",
    "python", "django", "flask", "fastapi", "javascript", "typescript", "node", "nodejs",
    "react", "vue", "angular", "svelte", "next", "nextjs", "java", "kotlin", "scala",
    "golang", "go", "rust", "ruby", "rails", "php", "laravel", "elixir", "erlang", "c",
    "c++", "c#", ".net", "dotnet", "swift", "objective c", "perl", "haskell", "clojure",
    "data engineer", "data science", "machine learning", "ml", "ai", "deep learning", "nlp",
    "qa", "testing", "automation", "security", "infosec", "cybersecurity", "blockchain",
    "web3", "solidity", "smart contracts", "embedded", "firmware", "game dev", "unity",
    "architect", "cto", "tech lead", "wordpress", "shopify", "salesforce", "sap",
)


def _normalize_tag(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(ch for ch in value.lower() if ch.isalnum())


_DEV_TAGS = frozenset(filter(None, (_normalize_tag(t) for t in _DEV_TAGS_RAW)))


class RemoteOkBoard:
    """``JobBoardProvider`` for Remote OK."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        spec = board_spec("remoteok")
        self.id = spec.id
        self.display_name = spec.display_name
        self.min_interval_hours = spec.min_interval_hours
        self._transport = transport
        self._timeout = timeout
        self._clock = clock

    @staticmethod
    def _is_legal_notice(entry: dict) -> bool:
        """The array's first element, which describes the licence rather than a job. Detected
        by its ``legal`` key instead of by position, so an extra banner element (or a day when
        the notice moves) does not import a fake job called "None"."""
        return "legal" in entry

    @staticmethod
    def _is_dev_posting(entry: dict) -> bool:
        """Whether the tags say this is a software job.

        A posting with NO tags at all passes: there is nothing to judge it on, and the role
        filter downstream is the honest place to decide. A posting whose tags are all
        non-technical (``design``, ``sales``, ``non tech``) is dropped -- that is the whole
        purpose of the pass, since Remote OK offers no category parameter.
        """
        tags = entry.get("tags")
        if not isinstance(tags, list):
            return True
        normalized = {_normalize_tag(t) for t in tags}
        normalized.discard("")
        if not normalized:
            return True
        return bool(normalized & _DEV_TAGS)

    def _to_posting(self, entry: object) -> RawPosting | None:
        if not isinstance(entry, dict) or self._is_legal_notice(entry):
            return None
        if not self._is_dev_posting(entry):
            return None
        title = clean_one_line(entry.get("position"))
        company = clean_one_line(entry.get("company"))
        url = entry.get("url")
        if not isinstance(url, str) or not url.strip():
            url = entry.get("apply_url")
        if not title or not company or not isinstance(url, str) or not url.strip():
            return None
        # ``date`` is ISO-8601 with an offset; ``epoch`` is the same instant as a unix
        # timestamp. Preferring ``date`` and falling back keeps a posting dated even when one
        # of the two fields is missing, which happens on older entries.
        date_posted = parse_iso_datetime(entry.get("date")) or parse_epoch(entry.get("epoch"))
        return RawPosting(
            title=title,
            company=company,
            location=clean_one_line(entry.get("location")) or None,
            is_remote=True,
            url=url.strip(),
            description=html_to_text(entry.get("description")),
            date_posted=date_posted,
            applicant_band=None,
        )

    async def search(self, query: BoardQuery) -> BoardResult:
        try:
            body = await fetch_text(
                REMOTEOK_API_URL,
                board_label=self.display_name,
                # Remote OK serves the array as ``application/json`` only when asked; without
                # this it can answer the HTML page instead.
                headers={"Accept": "application/json"},
                timeout=self._timeout,
                transport=self._transport,
            )
        except FeedFetchError as exc:
            return BoardResult(items=[], status=exc.status, message=exc.message)
        except Exception:
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
        if not isinstance(payload, list):
            return BoardResult(
                items=[],
                status="error",
                message=f"{self.display_name} devolveu um formato inesperado (esperava uma lista).",
            )

        matches_role = role_matcher(query.roles)
        now = self._clock()
        items = [
            posting
            for posting in (self._to_posting(entry) for entry in payload)
            if posting is not None
            and matches_role(posting.title)
            and is_fresh(posting.date_posted, query.hours_old, now)
        ]
        return BoardResult(items=newest_first(items, query.results_wanted), status="ok")
