"""We Work Remotely, through its category RSS feeds (v7 ticket 05).

WWR has no JSON API; what it has is a per-category RSS feed, which is enough and costs nothing.
Four feeds are read per Scan -- the umbrella programming category plus full-stack, back-end and
front-end -- because WWR files a job under exactly ONE category, so a back-end role never
appears in the front-end feed and the umbrella feed does not always carry the specialised ones.

Two shapes of this board make it the odd one out among the three feed adapters:

* **A partial answer is still ``ok``.** Four requests mean four chances to fail. Reporting
  ``error`` because one of four feeds timed out would hide the jobs the other three returned;
  the Scan is partial by design (CONTEXT.md: Scan) and so is this board's own answer, with the
  degradation named in ``message``. Only when EVERY feed fails does the board report failure.
* **The company is inside the title.** WWR writes ``<title>Acme Corp: Senior Rails Engineer``,
  so the split is the parse -- and a posting whose company cannot be recovered is dropped,
  because ``identity_key`` (company + title) is what dedup across boards runs on and an empty
  company side would collide every such posting into one Job Listing.

Parsing is ``xml.etree.ElementTree`` from the standard library: no new dependency, and RSS is
the one XML format simple enough not to want one.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
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
    parse_rfc822_datetime,
    role_matcher,
    utc_now,
)
from app.services.jobboards.provider_registry import board_spec

_BASE = "https://weworkremotely.com/categories"

# Declaration order is fallback order for duplicates: a job listed in both the umbrella feed
# and a specialised one keeps whichever copy is seen first, and they are identical anyway.
WWR_FEED_URLS: tuple[str, ...] = (
    f"{_BASE}/remote-programming-jobs.rss",
    f"{_BASE}/remote-full-stack-programming-jobs.rss",
    f"{_BASE}/remote-back-end-programming-jobs.rss",
    f"{_BASE}/remote-front-end-programming-jobs.rss",
)

# "Acme Corp: Senior Rails Engineer" -- and only the FIRST colon splits, since titles like
# "Acme: Engineer, Platform: Payments" exist and the company is never the second half.
_TITLE_SEPARATOR = ":"


def _text(item: ET.Element, tag: str) -> str | None:
    node = item.find(tag)
    if node is None or node.text is None:
        return None
    return node.text


class WeWorkRemotelyBoard:
    """``JobBoardProvider`` for We Work Remotely."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        clock: Callable[[], datetime] = utc_now,
        feed_urls: tuple[str, ...] = WWR_FEED_URLS,
    ) -> None:
        spec = board_spec("weworkremotely")
        self.id = spec.id
        self.display_name = spec.display_name
        self.min_interval_hours = spec.min_interval_hours
        self._transport = transport
        self._timeout = timeout
        self._clock = clock
        self._feed_urls = feed_urls

    def _split_company_and_title(self, item: ET.Element) -> tuple[str, str]:
        """``(company, title)`` for one ``<item>``, either of which may be empty.

        An explicit ``<company>`` element wins when the feed provides one (some WWR categories
        do), because splitting a title that happens to contain a colon would otherwise invent a
        company out of what is really part of the role name ("Engineer, Platform: Payments").
        The title still gets the company prefix removed, but only when it IS that company's
        name -- WWR writes it either way and "Acme Corp: Acme Corp: Engineer" is not a title.
        """
        raw_title = clean_one_line(_text(item, "title"))
        explicit_company = clean_one_line(_text(item, "company"))
        head, sep, tail = raw_title.partition(_TITLE_SEPARATOR)
        if explicit_company:
            if sep and head.strip().casefold() == explicit_company.casefold():
                return explicit_company, tail.strip()
            return explicit_company, raw_title
        if sep:
            return head.strip(), tail.strip()
        return "", raw_title

    def _to_posting(self, item: ET.Element) -> tuple[str, RawPosting] | None:
        """``(dedup key, posting)``, or ``None`` when the item is unusable."""
        company, title = self._split_company_and_title(item)
        link = (_text(item, "link") or "").strip()
        guid = (_text(item, "guid") or "").strip()
        if not company or not title or not (link or guid):
            return None
        url = link or guid
        region = clean_one_line(_text(item, "region"))
        return (
            # WWR's ``guid`` is the stable per-job identifier and the reason the same job in
            # two category feeds is imported once. Falling back to the link keeps a feed
            # without guids working instead of importing every item twice.
            guid or url,
            RawPosting(
                title=title,
                company=company,
                location=region or None,
                # The board is remote-only; ``region`` narrows WHERE remote is allowed from
                # ("Anywhere in the World", "USA Only"), it does not make a job on-site.
                is_remote=True,
                url=url,
                description=html_to_text(_text(item, "description")),
                date_posted=parse_rfc822_datetime(_text(item, "pubDate")),
                applicant_band=None,
            ),
        )

    async def _fetch_feed(self, url: str) -> list[ET.Element]:
        """The ``<item>`` elements of one feed. Raises ``FeedFetchError`` for a fetch failure
        or a body that is not parseable XML."""
        body = await fetch_text(
            url,
            board_label=self.display_name,
            timeout=self._timeout,
            transport=self._transport,
        )
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            raise FeedFetchError(
                "error", f"{self.display_name} devolveu um RSS que não pôde ser lido."
            ) from None
        return list(root.iter("item"))

    async def search(self, query: BoardQuery) -> BoardResult:
        matches_role = role_matcher(query.roles)
        now = self._clock()
        by_key: dict[str, RawPosting] = {}
        failures: list[FeedFetchError] = []

        for url in self._feed_urls:
            try:
                items = await self._fetch_feed(url)
            except FeedFetchError as exc:
                failures.append(exc)
                continue
            except Exception:
                failures.append(
                    FeedFetchError(
                        "error", f"Falha inesperada ao ler um feed de {self.display_name}."
                    )
                )
                continue
            for item in items:
                parsed = self._to_posting(item)
                if parsed is None:
                    continue
                key, posting = parsed
                if key in by_key:
                    continue
                if not matches_role(posting.title):
                    continue
                if not is_fresh(posting.date_posted, query.hours_old, now):
                    continue
                by_key[key] = posting

        if failures and len(failures) == len(self._feed_urls):
            # Every feed failed: report the first failure's kind, so a site-wide 429 reads as
            # ``blocked`` (retry next Scan) rather than as a bug.
            blocked = next((f for f in failures if f.status == "blocked"), None)
            worst = blocked or failures[0]
            return BoardResult(items=[], status=worst.status, message=worst.message)

        message = None
        if failures:
            message = (
                f"{len(failures)} de {len(self._feed_urls)} feeds de {self.display_name} "
                "falharam; a lista pode estar incompleta."
            )
        return BoardResult(
            items=newest_first(by_key.values(), query.results_wanted),
            status="ok",
            message=message,
        )
