"""The four JobSpy-backed Job Boards: LinkedIn, Indeed, Glassdoor and Google Jobs (v7 t04).

One adapter class, four instances -- the boards differ only in which ``site_name`` they hand
``jobspy.scrape_jobs`` and in whether the Applicant Band step runs afterwards. Everything else
(query planning, the DataFrame mapping, how a refusal becomes a Board Status) is one
implementation, because seven near-copies of a tolerant DataFrame reader is how the sixth one
quietly stops handling a missing column.

Three things about the JobSpy boundary shape this file, and none of them are obvious:

1. **``scrape_jobs`` is synchronous and slow.** It does real HTTP on the calling thread and
   fans its own sites out over a ``ThreadPoolExecutor``. Called directly from the Scan's event
   loop it would freeze the API for the duration, so every call goes through
   ``run_in_executor``.

2. **A refusal does not always raise.** Glassdoor and Google raise their own exceptions on a
   429, but LinkedIn's scraper *logs* ``"429 Response - Blocked by LinkedIn for too many
   requests"`` and returns an empty result. Trusting exceptions alone would report the board
   most likely to block us as ``ok`` with zero jobs -- indistinguishable from "no matches
   today", which is exactly the confusion the Board Status exists to prevent. So the call also
   watches JobSpy's own loggers for the duration and treats a blocking message as a refusal.
   (Side effect, accepted: attaching a handler before JobSpy's ``create_logger`` runs means it
   sees ``logger.handlers`` as non-empty and skips adding its stderr handler for that logger.
   We are a server; we log through ``logging`` ourselves.)

3. **The DataFrame is not a fixed shape.** With no results ``scrape_jobs`` returns a bare
   ``pd.DataFrame()`` -- no columns at all -- and the columns it does return are assembled
   per-site with missing ones filled as ``None``/``NaN``. The mapping below therefore asks for
   nothing it cannot do without, and pandas is never imported here: ``NaN``/``NaT`` are
   detected with ``value != value``, which is true of both and of nothing else we care about.

What this adapter deliberately does NOT do: retry, rotate proxies, or widen a search that came
back thin. A blocked board is reported and tried again next Scan (spec: proxies are out of
scope for v7).
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Any, Callable, Sequence

from app.domain.schemas import (
    BoardId,
    BoardQuery,
    BoardReportedStatus,
    BoardResult,
    RawPosting,
)
from app.services.jobboards import linkedin_applicants
from app.services.jobboards.provider_registry import board_spec
from app.services.secret_redaction import redact_secrets

logger = logging.getLogger(__name__)

# board id -> JobSpy ``site_name``. Identical strings today, spelled out anyway: the ids are our
# frozen ``BoardId`` contract and JobSpy's ``Site`` enum is JobSpy's, and one of them renaming a
# value should be a one-line change here rather than a board that silently scrapes nothing.
SITE_NAMES: dict[str, str] = {
    "linkedin": "linkedin",
    "indeed": "indeed",
    "glassdoor": "glassdoor",
    "google": "google",
}

# ``country_indeed`` is required by Indeed and Glassdoor (it picks the domain) and ignored by
# the others. This is the fallback when no location in the BoardQuery names a country -- the
# product's single local user is in Brazil, so defaulting to JobSpy's own ``"usa"`` would
# quietly search the wrong country. Overridable per instance.
DEFAULT_COUNTRY_INDEED = "brazil"

# One BoardQuery can carry several roles and several locations, and JobSpy takes ONE of each
# per call, so a query fans out into a small grid of calls. The cap is what keeps a Search
# Profile with five roles and four locations from turning one Scan into twenty scrapes of the
# board whose rate limit ``min_interval_hours`` exists to respect.
MAX_QUERIES_PER_SEARCH = 6

# JobSpy asks for the description as markdown; ``RawPosting.description`` wants clean text and
# markdown is text (this is the same content the One-click Resume later reads as a job
# description, so keeping its headings and bullets is worth more than flattening them).
DESCRIPTION_FORMAT = "markdown"

# A location that is not a place. Closed vocabulary on purpose -- the same discipline as ticket
# 03's title-noise list: guessing that an unrecognized string means "remote" would send
# ``location="Anywhere in LatAm"`` to a board as a city. A remote token in the Search Profile's
# locations becomes its own query (no location, remote filter on) rather than a location.
_REMOTE_TOKENS = frozenset(
    {
        "remote",
        "remoto",
        "remota",
        "remotely",
        "home office",
        "homeoffice",
        "trabalho remoto",
        "100% remoto",
        "anywhere",
        "worldwide",
    }
)

# Location text -> JobSpy country. Closed and small on purpose: JobSpy validates this string
# against its own ``Country`` enum and RAISES on anything it does not know, so the adapter may
# only ever pass a value it is sure of and must fall back to ``default_country`` otherwise.
# Portuguese spellings are here because the Search Profile is written by a Portuguese-speaking
# user ("Brasil", not "Brazil") -- accents are stripped before lookup, so both forms hit.
_COUNTRY_BY_LOCATION_TOKEN: dict[str, str] = {
    "brasil": "brazil",
    "brazil": "brazil",
    "br": "brazil",
    "portugal": "portugal",
    "pt": "portugal",
    "estados unidos": "usa",
    "eua": "usa",
    "usa": "usa",
    "us": "usa",
    "united states": "usa",
    "canada": "canada",
    "reino unido": "uk",
    "uk": "uk",
    "united kingdom": "uk",
    "inglaterra": "uk",
    "espanha": "spain",
    "spain": "spain",
    "alemanha": "germany",
    "germany": "germany",
    "franca": "france",
    "france": "france",
    "irlanda": "ireland",
    "ireland": "ireland",
    "holanda": "netherlands",
    "paises baixos": "netherlands",
    "netherlands": "netherlands",
    "italia": "italy",
    "italy": "italy",
    "mexico": "mexico",
    "argentina": "argentina",
    "chile": "chile",
    "colombia": "colombia",
    "uruguai": "uruguay",
    "uruguay": "uruguay",
    "australia": "australia",
    "india": "india",
    "japao": "japan",
    "japan": "japan",
    "polonia": "poland",
    "poland": "poland",
}

# The 26 Brazilian states plus the Federal District, by code and by name. Closed set, and the
# reason "São Paulo, SP" and "Belo Horizonte, MG" resolve to Brazil without a list of cities:
# the biggest Brazilian cities share their state's name, and the two-letter code is how a
# Brazilian writes a location anyway.
_BR_STATE_CODES = frozenset(
    "ac al ap am ba ce df es go ma mt ms mg pa pb pr pe pi rj rn rs ro rr sc sp se to".split()
)
_BR_STATE_NAMES = frozenset(
    {
        "acre",
        "alagoas",
        "amapa",
        "amazonas",
        "bahia",
        "ceara",
        "distrito federal",
        "espirito santo",
        "goias",
        "maranhao",
        "mato grosso",
        "mato grosso do sul",
        "minas gerais",
        "para",
        "paraiba",
        "parana",
        "pernambuco",
        "piaui",
        "rio de janeiro",
        "rio grande do norte",
        "rio grande do sul",
        "rondonia",
        "roraima",
        "santa catarina",
        "sao paulo",
        "sergipe",
        "tocantins",
        "brasilia",
    }
)

# Substrings that turn an exception or a JobSpy log line into ``blocked`` rather than ``error``.
# The distinction is what the user is told: ``blocked`` means "this board refused us, we will
# try next Scan" (nothing to fix), ``error`` means something broke.
_BLOCKING_MARKERS = (
    "429",
    "403",
    "999",
    "blocked",
    "too many requests",
    "rate limit",
    "captcha",
    "challenge",
    "authwall",
    "forbidden",
    "access denied",
)

# JobSpy's loggers are ``JobSpy:<Name>`` with ``propagate = False``, so they are only reachable
# by attaching to each name. Both spellings are listed because the scraper modules use
# ``create_logger("LinkedIn")`` while ``scrape_jobs`` itself uses ``site.value.capitalize()``.
_JOBSPY_LOGGER_NAMES: dict[str, tuple[str, ...]] = {
    "linkedin": ("JobSpy:LinkedIn", "JobSpy:Linkedin"),
    "indeed": ("JobSpy:Indeed",),
    "glassdoor": ("JobSpy:Glassdoor",),
    "google": ("JobSpy:Google",),
}

_URL_RE = re.compile(r"https?://\S+")
_WS_RE = re.compile(r"\s+")
_MAX_MESSAGE_CHARS = 200


# --- small tolerant converters --------------------------------------------------------------


def _is_missing(value: object) -> bool:
    """``None``, ``NaN`` or pandas' ``NaT``.

    ``value != value`` is the whole trick: those two are the only values in a DataFrame cell
    that are not equal to themselves, and it costs no pandas import. It matters for ``NaT``
    especially, which IS a ``datetime`` instance and would otherwise sail through the date
    conversion below as a real timestamp.
    """
    if value is None:
        return True
    try:
        return bool(value != value)
    except Exception:  # noqa: BLE001 -- an exotic cell type is simply "present"
        return False


def _clean_str(value: object) -> str:
    if _is_missing(value):
        return ""
    text = value if isinstance(value, str) else str(value)
    return text.strip()


def _as_bool(value: object) -> bool:
    if _is_missing(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "remote"}
    try:
        return bool(value)
    except Exception:  # noqa: BLE001
        return False


def _as_utc_datetime(value: object) -> datetime | None:
    """A cell's ``date_posted`` as an aware UTC ``datetime``, or ``None``.

    JobSpy models this as a calendar ``date``, which is the case the frozen contract calls out:
    a date-only board resolves to 00:00 UTC of that day. That rounds the posting DOWN in
    freshness, which can only cost it rank in the Visibility Score -- never inflate it.
    """
    if _is_missing(value):
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(
            tzinfo=timezone.utc
        )
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = _clean_str(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    for parse in (datetime.fromisoformat, lambda t: datetime.combine(date.fromisoformat(t), datetime.min.time())):
        try:
            parsed = parse(normalized)
        except (ValueError, TypeError):
            continue
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(
            tzinfo=timezone.utc
        )
    return None


def _deaccent(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def _safe_message(text: str, *, fallback: str) -> str:
    """A Board Status message fit to render verbatim.

    The contract says this string is shown as-is and must never be a raw exception repr or a
    URL with credentials, so: URLs out, whitespace collapsed, secrets redacted (the same
    ``redact_secrets`` every error path in the app goes through), length capped.
    """
    cleaned = _WS_RE.sub(" ", _URL_RE.sub("[url]", text or "")).strip()
    cleaned = redact_secrets(cleaned)
    if not cleaned:
        return fallback
    if len(cleaned) > _MAX_MESSAGE_CHARS:
        cleaned = cleaned[: _MAX_MESSAGE_CHARS - 1].rstrip() + "…"
    return cleaned


def _looks_blocked(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _BLOCKING_MARKERS)


# --- query planning -------------------------------------------------------------------------


def _is_remote_token(location: str) -> bool:
    return _deaccent(location).strip().lower() in _REMOTE_TOKENS


def country_for_location(location: str | None) -> str | None:
    """The JobSpy country a location string names, or ``None`` when it names none.

    Reads the segments right-to-left ("São Paulo, SP" -> "sp" -> Brazil) because that is where
    the country/state lives in every way a location is written. Recognizes only the closed
    vocabularies above -- an unknown string is ``None`` and the caller falls back to its
    default, which is the safe direction: passing a guess to JobSpy raises.
    """
    if not location:
        return None
    normalized = _deaccent(location).lower()
    segments = [seg.strip() for seg in re.split(r"[,/|]|\s+-\s+", normalized) if seg.strip()]
    for segment in reversed(segments or [normalized.strip()]):
        if segment in _COUNTRY_BY_LOCATION_TOKEN:
            return _COUNTRY_BY_LOCATION_TOKEN[segment]
        if segment in _BR_STATE_CODES or segment in _BR_STATE_NAMES:
            return "brazil"
    return None


class _QueryPlan:
    """One ``scrape_jobs`` call: a role, a place (or none), and whether to filter to remote."""

    __slots__ = (
        "search_term",
        "location",
        "is_remote",
        "country",
        "results_wanted",
        "hours_old",
    )

    def __init__(
        self,
        *,
        search_term: str | None,
        location: str | None,
        is_remote: bool,
        country: str,
        results_wanted: int,
        hours_old: int | None,
    ) -> None:
        self.search_term = search_term
        self.location = location
        self.is_remote = is_remote
        self.country = country
        self.results_wanted = results_wanted
        # ``None``, not 0: JobSpy treats a falsy ``hours_old`` as "no age filter", and passing 0
        # would silently widen a query the Search Profile meant to narrow.
        self.hours_old = hours_old

    def __repr__(self) -> str:  # pragma: no cover -- debugging aid
        return (
            f"_QueryPlan(search_term={self.search_term!r}, location={self.location!r}, "
            f"is_remote={self.is_remote}, country={self.country!r}, "
            f"results_wanted={self.results_wanted}, hours_old={self.hours_old})"
        )


# --- the adapter ----------------------------------------------------------------------------


class JobSpyBoard:
    """A ``JobBoardProvider`` backed by one JobSpy site.

    ``scrape`` and ``enrich`` are injectable seams, not production configuration: by default
    the adapter imports ``jobspy.scrape_jobs`` LAZILY, at call time. That matters twice over --
    the package pulls pandas and a TLS stack that no other part of the API needs at import, and
    a venv without it (see requirements.txt: its pins do not resolve on every Python) still
    boots the whole app, with these four boards reporting ``error`` and the other three working.
    """

    def __init__(
        self,
        board_id: BoardId,
        *,
        default_country: str = DEFAULT_COUNTRY_INDEED,
        max_queries: int = MAX_QUERIES_PER_SEARCH,
        fetch_applicant_bands: bool | None = None,
        scrape: Callable[..., Any] | None = None,
        enrich: Callable[[Sequence[RawPosting]], Any] | None = None,
    ) -> None:
        spec = board_spec(board_id)
        if spec.id not in SITE_NAMES:
            raise ValueError(
                f"job board {spec.id!r} is not backed by JobSpy "
                f"(known: {', '.join(sorted(SITE_NAMES))})"
            )
        self.id: BoardId = spec.id
        self.display_name = spec.display_name
        self.min_interval_hours = spec.min_interval_hours
        self.site_name = SITE_NAMES[spec.id]
        self.default_country = default_country
        self.max_queries = max(1, max_queries)
        # Only LinkedIn has an applicant count to fetch; the flag exists so a test (or a user
        # who would rather not send LinkedIn one request per posting) can turn it off.
        self.fetch_applicant_bands = (
            spec.id == "linkedin" if fetch_applicant_bands is None else fetch_applicant_bands
        )
        self._scrape = scrape
        self._enrich = enrich

    # -- JobBoardProvider ---------------------------------------------------------------

    async def search(self, query: BoardQuery) -> BoardResult:
        """Run this board for one BoardQuery. Reports, never raises."""
        try:
            plans = self._plans(query)
        except Exception as exc:  # noqa: BLE001 -- a bad query is this board's error, not a crash
            return BoardResult(
                items=[],
                status="error",
                message=_safe_message(str(exc), fallback="could not build the board query"),
            )

        loop = asyncio.get_running_loop()
        items: list[RawPosting] = []
        seen_urls: set[str] = set()
        blocked_message: str | None = None
        error_message: str | None = None

        for plan in plans:
            # Sequential on purpose: the plans of ONE board all hit the same host, and firing
            # them together is the difference between a search and a burst that gets a 429.
            try:
                status, postings, message = await loop.run_in_executor(
                    None, self._scrape_plan, plan
                )
            except Exception as exc:  # noqa: BLE001 -- last line of "never raises"
                logger.warning("job board %s raised past its own guard", self.id, exc_info=True)
                status, postings, message = (
                    "error",
                    [],
                    _safe_message(
                        str(exc), fallback=f"{self.display_name} could not be searched"
                    ),
                )
            if status == "blocked" and blocked_message is None:
                blocked_message = message
            elif status == "error" and error_message is None:
                error_message = message
            for posting in postings:
                if posting.url in seen_urls:
                    # The same job can answer to two roles ("Backend Engineer" and "Python
                    # Developer"); dedup by URL here so this board reports it once. Cross-board
                    # identity dedup is the Scan engine's job, not ours.
                    continue
                seen_urls.add(posting.url)
                items.append(posting)

        if self.fetch_applicant_bands and items:
            items = await self._enrich_bands(items)

        status, message = self._aggregate(blocked_message, error_message)
        return BoardResult(items=items, status=status, message=message)

    # -- internals ----------------------------------------------------------------------

    def _aggregate(
        self, blocked: str | None, errored: str | None
    ) -> tuple[BoardReportedStatus, str | None]:
        """One Board Status for a board that may have run several queries.

        ``blocked`` wins even when some postings came back, and that is the deliberate call: a
        board that refused half our queries returned a partial list, and reporting ``ok`` would
        tell the user "this is what LinkedIn has" when it is not. The items ride along with the
        ``blocked`` status precisely so nothing found is thrown away -- the Scan engine keeps
        ``BoardResult.items`` regardless of status.
        """
        if blocked is not None:
            return "blocked", blocked
        if errored is not None:
            return "error", errored
        return "ok", None

    def _plans(self, query: BoardQuery) -> list[_QueryPlan]:
        roles = [role.strip() for role in (query.roles or []) if role and role.strip()]
        locations = [loc.strip() for loc in (query.locations or []) if loc and loc.strip()]

        remote_only = query.remote == "remote_only"
        places = [loc for loc in locations if not _is_remote_token(loc)]
        # Only an explicit remote TOKEN in the locations adds the extra place-less query.
        # ``remote_only`` must not: with "Brasil" + remote_only the user asked for remote jobs
        # IN BRAZIL, and a location-less remote query would quietly search the whole world.
        wants_remote_slot = any(_is_remote_token(loc) for loc in locations)

        # (location, is_remote) pairs. A remote token in the Search Profile is not a place: it
        # becomes one extra query with no location and the board's remote filter on.
        slots: list[tuple[str | None, bool]] = [(place, remote_only) for place in places]
        if wants_remote_slot:
            slots.append((None, True))
        if not slots:
            slots.append((None, remote_only))

        fallback_country = self._country_for_query(locations)
        combos = [(role, slot) for role in (roles or [None]) for slot in slots]
        combos = combos[: self.max_queries]
        # ``results_wanted`` is the board's budget for the whole BoardQuery, so it is split
        # across the queries the query fans out into rather than multiplied by them.
        per_plan = max(1, -(-max(1, query.results_wanted) // max(1, len(combos))))
        hours_old = query.hours_old if query.hours_old and query.hours_old > 0 else None

        return [
            _QueryPlan(
                search_term=role,
                location=location,
                is_remote=is_remote,
                country=country_for_location(location) or fallback_country,
                results_wanted=per_plan,
                hours_old=hours_old,
            )
            for role, (location, is_remote) in combos
        ]

    def _country_for_query(self, locations: Sequence[str]) -> str:
        for location in locations:
            country = country_for_location(location)
            if country:
                return country
        return self.default_country

    def _scrape_jobs(self) -> Callable[..., Any]:
        if self._scrape is not None:
            return self._scrape
        from jobspy import scrape_jobs  # noqa: PLC0415 -- lazy by design, see the class docstring

        return scrape_jobs

    def _scrape_plan(
        self, plan: _QueryPlan
    ) -> tuple[BoardReportedStatus, list[RawPosting], str | None]:
        """One ``scrape_jobs`` call, on a worker thread. Returns, never raises."""
        try:
            scrape = self._scrape_jobs()
        except ImportError as exc:
            return (
                "error",
                [],
                _safe_message(
                    f"python-jobspy is not installed ({exc})",
                    fallback="python-jobspy is not installed",
                ),
            )

        with _JobSpyLogWatch(self.id) as watch:
            try:
                frame = scrape(
                    site_name=[self.site_name],
                    search_term=plan.search_term,
                    location=plan.location,
                    is_remote=plan.is_remote,
                    results_wanted=plan.results_wanted,
                    hours_old=plan.hours_old,
                    country_indeed=plan.country,
                    description_format=DESCRIPTION_FORMAT,
                    linkedin_fetch_description=self.id == "linkedin",
                    verbose=0,
                )
            except Exception as exc:  # noqa: BLE001 -- an adapter reports, it does not raise
                logger.warning("job board %s failed: %s", self.id, exc, exc_info=True)
                text = str(exc) or exc.__class__.__name__
                if _looks_blocked(text) or _looks_blocked(exc.__class__.__name__):
                    return "blocked", [], _safe_message(
                        text, fallback=f"{self.display_name} refused the request"
                    )
                return "error", [], _safe_message(
                    text, fallback=f"{self.display_name} could not be searched"
                )

        blocking_line = watch.blocking_message()
        postings = _postings_from_frame(frame)
        if blocking_line is not None:
            # LinkedIn's path: the scraper swallowed the 429 and handed us an empty (or short)
            # frame. Whatever it did return is kept; the status tells the truth about it.
            return "blocked", postings, _safe_message(
                blocking_line, fallback=f"{self.display_name} refused the request"
            )
        return "ok", postings, None

    async def _enrich_bands(self, items: list[RawPosting]) -> list[RawPosting]:
        try:
            if self._enrich is not None:
                enriched = self._enrich(items)
                if asyncio.iscoroutine(enriched):
                    enriched = await enriched
                return list(enriched)
            return await linkedin_applicants.enrich_applicant_bands(items)
        except Exception:  # noqa: BLE001 -- the band is a nice-to-have, the postings are not
            logger.warning("applicant band enrichment failed for %s", self.id, exc_info=True)
            return items


class _JobSpyLogWatch:
    """Collects JobSpy's own log records for one board, for the duration of one call.

    Exists for a single reason, spelled out in the module docstring: LinkedIn reports a 429 by
    logging it and returning nothing. Everything captured is discarded unless it looks like a
    refusal.
    """

    def __init__(self, board_id: str) -> None:
        self._names = _JOBSPY_LOGGER_NAMES.get(board_id, ())
        self._records: list[str] = []
        self._handler: logging.Handler | None = None
        self._attached: list[logging.Logger] = []

    def __enter__(self) -> "_JobSpyLogWatch":
        records = self._records

        class _Collector(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                if record.levelno < logging.WARNING:
                    return
                try:
                    records.append(record.getMessage())
                except Exception:  # noqa: BLE001 -- a broken record must not break the scrape
                    pass

        self._handler = _Collector(level=logging.WARNING)
        for name in self._names:
            log = logging.getLogger(name)
            log.addHandler(self._handler)
            self._attached.append(log)
        return self

    def __exit__(self, *exc_info: object) -> None:
        for log in self._attached:
            if self._handler is not None:
                log.removeHandler(self._handler)
        self._attached.clear()

    def blocking_message(self) -> str | None:
        for message in self._records:
            if _looks_blocked(message):
                return message
        return None


def _postings_from_frame(frame: Any) -> list[RawPosting]:
    """A JobSpy result DataFrame as ``RawPosting``s, asking for nothing it cannot do without.

    Tolerances that are all real JobSpy behaviour, not defensive padding: an empty result is a
    DataFrame with NO columns; per-site frames are concatenated so a column only one site fills
    is ``NaN`` everywhere else; ``date_posted`` is a calendar date, or ``NaT``; a description
    can be empty. The two fields with no sane default are ``title`` and ``url`` -- a posting
    without either is not a posting -- and those rows are dropped.

    ``company`` is NOT required. A missing one is left empty rather than dropping the row: two
    company-less postings with the same title would merge into one Job Listing keeping both
    source links, which is a smaller loss than a real job never being shown.
    """
    if frame is None:
        return []
    try:
        to_dict = getattr(frame, "to_dict", None)
        if to_dict is None or len(frame) == 0:
            return []
        rows = to_dict(orient="records")
    except Exception:  # noqa: BLE001 -- an unexpected payload is "no postings", not a crash
        logger.warning("could not read the job board result frame", exc_info=True)
        return []

    postings: list[RawPosting] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = _clean_str(row.get("title"))
        url = _clean_str(row.get("job_url")) or _clean_str(row.get("job_url_direct"))
        if not title or not url:
            continue
        postings.append(
            RawPosting(
                title=title,
                company=_clean_str(row.get("company")),
                location=_clean_str(row.get("location")) or None,
                is_remote=_as_bool(row.get("is_remote")),
                url=url,
                description=_clean_str(row.get("description")),
                date_posted=_as_utc_datetime(row.get("date_posted")),
                applicant_band=None,
            )
        )
    return postings


def linkedin_board(**kwargs: Any) -> JobSpyBoard:
    return JobSpyBoard("linkedin", **kwargs)


def indeed_board(**kwargs: Any) -> JobSpyBoard:
    return JobSpyBoard("indeed", **kwargs)


def glassdoor_board(**kwargs: Any) -> JobSpyBoard:
    return JobSpyBoard("glassdoor", **kwargs)


def google_board(**kwargs: Any) -> JobSpyBoard:
    return JobSpyBoard("google", **kwargs)


__all__ = [
    "DEFAULT_COUNTRY_INDEED",
    "MAX_QUERIES_PER_SEARCH",
    "SITE_NAMES",
    "JobSpyBoard",
    "country_for_location",
    "glassdoor_board",
    "google_board",
    "indeed_board",
    "linkedin_board",
]
