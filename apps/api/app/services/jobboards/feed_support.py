"""What the three feed adapters (Remotive, We Work Remotely, Remote OK) all have to do (v7
ticket 05).

These boards are the *cheap* half of v7: a plain HTTP GET against a public JSON or RSS feed,
no scraping library, no browser, no key. What is NOT trivial is everything around the GET, and
it is identical for all three -- which is why it lives here once instead of three times:

* **Never raise.** ``JobBoardProvider.search`` reports trouble as a ``BoardResult``; a Scan is
  partial, not failed (CONTEXT.md: Scan). ``FeedFetchError`` is the internal shape a fetch
  failure takes on the way to that report, and it never escapes an adapter.
* **Refusal vs breakage.** A 403/429/451 is the board saying *no* (``blocked``: retry later,
  the flag the BoardStatusBar shows); a timeout or an unparseable payload is a breakage
  (``error``). Getting this wrong makes a rate limit look like a bug forever.
* **HTML to TEXT.** ``RawPosting.description`` is contractually clean text, and these boards
  serve HTML. See ``html_to_text``.
* **Filtering the adapter must do itself.** These feeds are category-wide firehoses: neither
  Remotive's ``software-dev`` nor WWR's programming RSS knows the user's target roles, and no
  feed honours ``hours_old``. The Scan engine receives a ``BoardQuery`` -> ``BoardResult``
  contract, so trimming to the query is the adapter's job.

The network seam is CONSTRUCTOR injection (``transport=httpx.MockTransport(...)``), not the
module-level ``_transport`` of ``services/model_catalog.py``: a board adapter is an object the
Scan engine is handed (ticket 03 decision 3 -- no mutable module singletons for boards), so the
test can wire a fake per instance instead of monkeypatching a global that leaks between tests.
"""

from __future__ import annotations

import html as html_module
import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

from app.domain.schemas import BoardReportedStatus, RawPosting
from app.services.html_sanitize import sanitize_plain_text

# Generous by feed standards and deliberately finite: a board that hangs must cost the Scan a
# bounded amount of time, since the engine gathers every board concurrently and waits for all.
DEFAULT_TIMEOUT_SECONDS = 15.0

# Remote OK's API returns 403 to a client with no User-Agent (httpx's default one included), so
# identifying ourselves is not politeness here, it is the difference between working and
# ``blocked``. The other two accept anything; sending the same string everywhere keeps our
# traffic attributable to one app in their logs.
USER_AGENT = "Agente-de-Curriculo/0.1 (Job Monitor; single-user local app)"

# The board REFUSED us rather than broke. 429 is the rate limit these feeds actually use; 403
# is what a bot filter answers; 401/407 mean a wall appeared where there was none; 451 is a
# legal block. Everything else that is not 2xx is a breakage on their side or ours.
BLOCKED_STATUS_CODES = frozenset({401, 403, 407, 429, 451})

_BR_TAG_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
# Closing CONTAINER tags. ``bleach`` breaks the line where it strips a block element such as
# ``<p>`` or ``<li>``, but not where a container ENDS -- so text that follows a list welds onto
# its last bullet ("Comfortable with AWSApply by September 30").
_BLOCK_END_RE = re.compile(
    r"</\s*(?:ul|ol|dl|table|tbody|blockquote|div|section|article|h[1-6]|p)\s*>",
    re.IGNORECASE,
)
_NON_WORD_RE = re.compile(r"[^0-9a-z]+")
_TRAILING_SPACE_RE = re.compile(r"[ \t]+(?=\n)")
_MANY_BLANK_LINES_RE = re.compile(r"\n{3,}")
_MANY_SPACES_RE = re.compile(r"[ \t]{2,}")


class FeedFetchError(Exception):
    """A fetch that must become a non-``ok`` ``BoardResult``.

    Carries the Board Status the adapter should report and a message written for the user, not
    for a log: it is rendered verbatim next to the board's name in the BoardStatusBar, so it
    never contains an exception repr, a stack trace or a URL with credentials.
    """

    def __init__(self, status: BoardReportedStatus, message: str) -> None:
        super().__init__(message)
        self.status: BoardReportedStatus = status
        self.message = message


def utc_now() -> datetime:
    """The adapters' clock, injected in the constructor so ``hours_old`` is testable against a
    recorded fixture whose dates are frozen in the past."""
    return datetime.now(timezone.utc)


async def fetch_text(
    url: str,
    *,
    board_label: str,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """GET ``url`` and return the body as text, or raise ``FeedFetchError``.

    ``follow_redirects`` is on because all three boards redirect (http -> https, and WWR
    redirects its category feeds); without it a 301 would surface as an empty ``error``.
    """
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    try:
        async with httpx.AsyncClient(
            timeout=timeout, transport=transport, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params, headers=request_headers)
    except httpx.TimeoutException:
        raise FeedFetchError(
            "error", f"{board_label} não respondeu a tempo ({timeout:.0f}s)."
        ) from None
    except httpx.HTTPError:
        # ConnectError, ReadError, TooManyRedirects, InvalidURL... all the same to the user:
        # we could not reach the board. The exception type would tell them nothing.
        raise FeedFetchError("error", f"Não foi possível acessar {board_label}.") from None

    if response.status_code in BLOCKED_STATUS_CODES:
        raise FeedFetchError(
            "blocked",
            f"{board_label} recusou a consulta (HTTP {response.status_code}); "
            "tentamos de novo no próximo Scan.",
        )
    if response.status_code >= 400:
        raise FeedFetchError("error", f"{board_label} respondeu HTTP {response.status_code}.")
    return response.text


def html_to_text(raw: str | None) -> str:
    """A board's HTML description as the clean text ``RawPosting.description`` promises.

    Three passes, in this order and for these reasons:

    1. ``<br>`` and closing container tags become newlines FIRST. ``bleach`` already turns
       block elements (``<p>``, ``<li>``) into line breaks when it strips them, but a stripped
       ``<br>`` would weld two lines together ("linebreak") -- and these feeds format whole
       descriptions with it -- while the end of a ``<ul>`` would weld the paragraph after a
       list onto its last bullet.
    2. ``sanitize_plain_text`` (the repo's single sanitizer, ``services/html_sanitize.py``)
       removes every tag. Markup can no longer be produced from here: what comes out is data.
    3. ``html.unescape`` decodes the entities bleach leaves escaped. Skipping this ships
       ``R&amp;D`` and ``&nbsp;`` into the LLM prompt, the Fit keyword pass and the PDF. The
       cost is that a description that *displayed* the text ``<script>`` (i.e. wrote
       ``&lt;script&gt;``) now contains those characters literally -- which is correct, because
       this field is TEXT by contract: React escapes it and the LaTeX renderer escapes it, and
       no consumer may hand it to ``innerHTML``.
    """
    if not isinstance(raw, str) or not raw.strip():
        return ""
    with_breaks = _BLOCK_END_RE.sub(lambda m: m.group(0) + "\n", _BR_TAG_RE.sub("\n", raw))
    stripped = sanitize_plain_text(with_breaks)
    return normalize_text(html_module.unescape(stripped))


def normalize_text(text: str) -> str:
    """Collapse a feed's whitespace without destroying its paragraphs: runs of blank lines
    become one blank line, non-breaking spaces become spaces, trailing spaces go."""
    out = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    out = _MANY_SPACES_RE.sub(" ", out)
    out = _TRAILING_SPACE_RE.sub("", out)
    out = _MANY_BLANK_LINES_RE.sub("\n\n", out)
    return out.strip()


def clean_one_line(text: str | None) -> str:
    """A short field (title, company, location) as one line of text."""
    if not isinstance(text, str):
        return ""
    return " ".join(html_to_text(text).split())


def _tokens(text: str) -> list[str]:
    return [t for t in _NON_WORD_RE.sub(" ", _deaccent(text).lower()).split() if t]


def _deaccent(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def _compact(text: str) -> str:
    return "".join(_tokens(text))


def role_matcher(roles: Sequence[str]) -> Callable[[str], bool]:
    """A predicate over a posting TITLE for the query's target roles.

    Empty ``roles`` matches everything -- the Search Profile without roles means "the whole
    category", which is exactly what these feeds already return.

    A role matches on either of two readings, because the feeds write titles both ways:

    * every word of the role appears in the title ("Backend Engineer" matches "Senior Backend
      Engineer, Payments" and "Engineer, Backend");
    * the role with separators removed appears in the title with separators removed
      ("Front-End Developer" matches "Front End Developer" and "FrontEnd Developer").

    Loose on purpose. Dropping a real posting here makes it invisible to the whole product;
    keeping a near miss only costs it rank, since Fit scores it later anyway.
    """
    prepared = [(set(_tokens(r)), _compact(r)) for r in roles if isinstance(r, str) and r.strip()]
    if not prepared:
        return lambda _title: True

    def matches(title: str) -> bool:
        title_tokens = set(_tokens(title))
        title_compact = _compact(title)
        return any(
            (tokens and tokens <= title_tokens) or (compact and compact in title_compact)
            for tokens, compact in prepared
        )

    return matches


def is_fresh(date_posted: datetime | None, hours_old: int, now: datetime) -> bool:
    """Whether a posting falls inside the query's ``hours_old`` window.

    An unknown date PASSES. The alternative -- dropping it -- would let a board that simply
    stopped publishing dates go silently empty; keeping it costs only rank, since a posting
    with no date already scores as the oldest bucket in the Visibility Score.
    """
    if date_posted is None:
        return True
    if hours_old <= 0:
        return True
    return date_posted >= now - timedelta(hours=hours_old)


def to_utc(value: datetime | None) -> datetime | None:
    """Every ``RawPosting.date_posted`` is aware UTC (contract, ticket 01 decision 9). A feed
    that publishes a naive timestamp is publishing UTC -- all three document it that way."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_iso_datetime(value: object) -> datetime | None:
    """An ISO-8601 timestamp as aware UTC, or ``None`` for anything unparseable.

    A date-only value ("2026-08-20") resolves to 00:00 UTC of that day: rounding a posting DOWN
    in freshness can only cost it rank, never inflate it (ticket 01 decision 9).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return to_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def parse_rfc822_datetime(value: object) -> datetime | None:
    """An RSS ``pubDate`` ("Tue, 19 Aug 2026 14:03:11 +0000") as aware UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return to_utc(parsedate_to_datetime(value.strip()))
    except (TypeError, ValueError):
        return None


def parse_epoch(value: object) -> datetime | None:
    """A unix timestamp (Remote OK's ``epoch``) as aware UTC."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def newest_first(postings: Iterable[RawPosting], limit: int) -> list[RawPosting]:
    """Cap a board's answer at ``results_wanted``, keeping the FRESHEST postings.

    The cap has to fall somewhere and the Scan engine ranks by Visibility (of which recency is
    a term), so cutting the oldest is the cut that loses the least. Dateless postings sort
    last for the same reason they score as the oldest bucket.
    """
    oldest_possible = datetime.min.replace(tzinfo=timezone.utc)
    ordered = sorted(
        postings,
        key=lambda p: (p.date_posted is not None, p.date_posted or oldest_possible),
        reverse=True,
    )
    if limit > 0:
        return ordered[:limit]
    return ordered
