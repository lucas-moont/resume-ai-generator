"""The Search Profile: read, validated write, and the deterministic suggestion from the
Profile (v7 ticket 06).

What the user is looking for (CONTEXT.md: Search Profile) is a different thing from who they
are (the Profile). This module owns the whole difference:

* **Reading** never invents state on disk. With no saved row, ``get_search_profile`` returns a
  DEFAULT with ``updatedAt is None`` instead of writing one, because "no row" is a meaningful
  state everywhere else in v7 -- ``search_profile``'s own docstring says a Scan with no row has
  nothing to search for, and ``SearchProfileOut.updatedAt is None`` is the contract's way of
  saying "this was never saved". A GET that quietly persisted defaults would answer both
  questions with "yes, the user configured this", and the scheduler would start believing an
  empty role list was a choice.
* **Writing** is a PUT of the whole form (`jobs_repo.put_search_profile`), validated here
  rather than only at the HTTP edge. FastAPI already 422s a bad board id or interval because
  ``SearchProfileIn`` types them as ``Literal``s -- this is the second gate, for every caller
  that is not an HTTP request (the Scan engine, a script, a test) and so that "which boards
  exist" is answered by ``BOARD_SPECS``, the one catalog, and not by a Literal that could drift
  from it.
* **Suggesting** is deterministic and LLM-free. ``suggest_from_profile`` reads the Profile's
  ``headline`` and returns the segments VERBATIM. No headline means no roles -- the same rule
  the Baseline Resume's Career Target follows (``domain/baseline_brief.has_career_target``):
  with nothing stated there is nothing to be inferred, and inventing a career direction for
  the candidate is the one failure mode worth designing against. The suggestion is not saved;
  the user edits it into existence with a normal PUT.

Nothing here calls an LLM or the network.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, get_args

from sqlmodel import Session

from app.db.tables import SearchProfile
from app.domain.schemas import (
    BoardListOut,
    BoardOut,
    MaxApplicantBand,
    RemotePreference,
    ResumeDocument,
    ScanIntervalHours,
    SearchProfileIn,
    SearchProfileOut,
)
from app.repositories import jobs_repo
from app.services.jobboards.provider_registry import BOARD_SPECS, is_known_board, known_board_ids

# --- Defaults for a Search Profile nobody has saved yet ---------------------------------------

# "Brasil" + "Remote" rather than the user's city: the Profile's ``location`` is where they
# live, not where they will accept work, and a remote-friendly default is the one that cannot
# silently hide jobs. The user narrows it; we never narrow it for them.
DEFAULT_LOCATIONS: tuple[str, ...] = ("Brasil", "Remote")
# Languages of POSTINGS, deliberately not SUPPORTED_LOCALES (see ``SearchProfileIn.languages``).
DEFAULT_LANGUAGES: tuple[str, ...] = ("pt", "en")
DEFAULT_REMOTE: RemotePreference = "any"
# Every board ON by default. The opposite default (all off) would make a first Immediate Scan
# return nothing at all and read as a broken feature rather than as an empty configuration.
# ``maxApplicantBand`` defaults to ``None`` ("qualquer") and ``intervalHours`` to ``None``
# (off): a scheduler that started scanning seven boards before the user ever opened the form
# would be reaching the network on their behalf without being asked.

# Caps on the free-text lists. Not in the spec, added here because each role is a separate
# query sent to every enabled board: a pasted paragraph in the roles field is a hundred board
# calls, which is the one input in this form that costs something outside the process. The
# numbers are far above any real search (the web form is a tag input) so the 422 is only ever
# reached by a mistake or by a caller that is not the form.
MAX_LIST_ITEMS = 20
MAX_ITEM_LENGTH = 120

# How many roles a SUGGESTION may propose. A headline listing eight things is a person
# describing themselves, not a person asking for eight parallel searches; the rest are one
# edit away. Truncating is not inventing -- the kept roles are still verbatim.
MAX_SUGGESTED_ROLES = 5

# Attribution that Remotive's and Remote OK's terms require of anyone republishing their
# listings. Served with the catalog so the Search Profile form and the Listing Source chips
# read it from ONE place instead of hardcoding a legal obligation in the web app.
_ATTRIBUTION_NOTES: dict[str, str] = {
    "remotive": "Vagas fornecidas por Remotive (remotive.com).",
    "remoteok": "Vagas fornecidas por Remote OK (remoteok.com).",
}


class SearchProfileValidationError(ValueError):
    """A Search Profile the user may not save. Routers turn this into a 422."""


# --- Reads ------------------------------------------------------------------------------------


def default_search_profile() -> SearchProfileOut:
    """The Search Profile of a user who has never saved one. NOT persisted: ``updatedAt`` is
    ``None``, which on the wire means exactly "never saved" (the same state a suggestion is
    in)."""
    return SearchProfileOut(
        roles=[],
        locations=list(DEFAULT_LOCATIONS),
        remote=DEFAULT_REMOTE,
        languages=list(DEFAULT_LANGUAGES),
        boards=list(known_board_ids()),
        maxApplicantBand=None,
        intervalHours=None,
        updatedAt=None,
    )


def get_search_profile(session: Session) -> SearchProfileOut:
    """The saved Search Profile, or the default when the user has never saved one.

    Never a 404 and never a write: the form always has something to render, and whether the
    user has actually chosen anything is readable from ``updatedAt``.
    """
    row = jobs_repo.get_search_profile(session)
    if row is None:
        return default_search_profile()
    return _to_out(row)


def _to_out(row: SearchProfile) -> SearchProfileOut:
    """The stored row as the wire shape.

    Board ids are filtered against the catalog on the way OUT as well as in. The column holds
    plain strings precisely so a row written while a board existed still loads after that board
    is retired (``jobs_repo.get_boards``); without this filter that row would fail
    ``BoardId`` validation here and turn a retired board into a 500 on every GET.
    """
    return SearchProfileOut(
        roles=jobs_repo.get_roles(row),
        locations=jobs_repo.get_locations(row),
        remote=row.remote,  # type: ignore[arg-type]
        languages=jobs_repo.get_languages(row),
        boards=[b for b in jobs_repo.get_boards(row) if is_known_board(b)],  # type: ignore[misc]
        maxApplicantBand=row.max_applicant_band,  # type: ignore[arg-type]
        intervalHours=row.interval_hours,  # type: ignore[arg-type]
        updatedAt=row.updated_at,
    )


def list_boards() -> BoardListOut:
    """The Job Board catalog (``GET /api/jobs/boards``), straight from ``BOARD_SPECS``.

    Served by the backend rather than hardcoded in the web app so adding a board is a one-line
    widening of the catalog, and so the board's own minimum interval -- which makes a 1h user
    interval mean 6h for Remotive -- reaches the form from the same constant the Scan enforces.
    """
    return BoardListOut(
        boards=[
            BoardOut(
                id=spec.id,
                displayName=spec.display_name,
                minIntervalHours=spec.min_interval_hours,
                attributionNote=_ATTRIBUTION_NOTES.get(spec.id),
            )
            for spec in BOARD_SPECS
        ]
    )


# --- Write ------------------------------------------------------------------------------------


def put_search_profile(session: Session, incoming: SearchProfileIn) -> SearchProfileOut:
    """Validate, normalize and store the whole Search Profile. The caller commits.

    Takes the contract type, so an HTTP request has already been through Pydantic by the time
    it arrives; the validation below is what stands for every other caller (and it is where
    board ids are checked against ``BOARD_SPECS`` rather than against a Literal that could
    drift from the catalog). Tests reach it with ``SearchProfileIn.model_construct(...)``,
    which builds the shape without validating it.
    """
    clean = normalize_search_profile(incoming)
    row = jobs_repo.put_search_profile(
        session,
        roles=clean.roles,
        locations=clean.locations,
        remote=clean.remote,
        languages=clean.languages,
        boards=clean.boards,
        max_applicant_band=clean.maxApplicantBand,
        interval_hours=clean.intervalHours,
    )
    return _to_out(row)


def normalize_search_profile(incoming: SearchProfileIn) -> SearchProfileIn:
    """Everything that decides whether a Search Profile is savable, in one pass.

    Rejects (422): a remote preference, applicant band or interval outside the contract; an
    unknown board id; a list item that is empty, too long, or a list that is too long.
    Normalizes (silently, because none of it changes what the user asked for): surrounding
    whitespace, collapsed inner whitespace, case-insensitive duplicates, and board order --
    which is forced to catalog order so the saved list, the Scan's board loop and the
    BoardStatusBar all read the same way regardless of the order the checkboxes were clicked.
    """
    remote = _validate_choice(getattr(incoming, "remote", DEFAULT_REMOTE), RemotePreference, "remote")
    band = _validate_optional_choice(
        getattr(incoming, "maxApplicantBand", None), MaxApplicantBand, "maxApplicantBand"
    )
    interval = _validate_optional_choice(
        getattr(incoming, "intervalHours", None), ScanIntervalHours, "intervalHours"
    )
    return SearchProfileIn(
        roles=_clean_text_list(getattr(incoming, "roles", []), "roles"),
        locations=_clean_text_list(getattr(incoming, "locations", []), "locations"),
        remote=remote,
        languages=_clean_text_list(getattr(incoming, "languages", []), "languages"),
        boards=_clean_boards(getattr(incoming, "boards", [])),
        maxApplicantBand=band,
        intervalHours=interval,
    )


def _validate_choice(value: Any, literal: Any, field: str) -> Any:
    allowed = get_args(literal)
    # ``True`` is an ``int`` and equals 1, so a bool would pass an ``in`` test against
    # ``ScanIntervalHours`` and be stored as an interval of one hour nobody asked for.
    if isinstance(value, bool) or value not in allowed:
        raise SearchProfileValidationError(
            f"{field} must be one of {', '.join(repr(a) for a in allowed)}; got {value!r}"
        )
    return value


def _validate_optional_choice(value: Any, literal: Any, field: str) -> Any:
    if value is None:
        return None
    return _validate_choice(value, literal, field)


def _clean_boards(values: Any) -> list[str]:
    """Known ids only, deduplicated, in catalog order."""
    items = _as_sequence(values, "boards")
    for value in items:
        if not is_known_board(value):
            raise SearchProfileValidationError(
                f"unknown job board {value!r} (known: {', '.join(known_board_ids())})"
            )
    wanted = set(items)
    return [spec.id for spec in BOARD_SPECS if spec.id in wanted]


def _clean_text_list(values: Any, field: str) -> list[str]:
    items = _as_sequence(values, field)
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in items:
        if not isinstance(value, str):
            raise SearchProfileValidationError(f"{field} must contain only strings; got {value!r}")
        text = " ".join(value.split())
        if not text:
            # A blank tag is the form's own leftover, not a user's request -- dropped rather
            # than rejected, so a trailing empty chip never blocks a save.
            continue
        if len(text) > MAX_ITEM_LENGTH:
            raise SearchProfileValidationError(
                f"each entry in {field} must be at most {MAX_ITEM_LENGTH} characters "
                f"(got {len(text)})"
            )
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    if len(cleaned) > MAX_LIST_ITEMS:
        raise SearchProfileValidationError(
            f"{field} may hold at most {MAX_LIST_ITEMS} entries (got {len(cleaned)})"
        )
    return cleaned


def _as_sequence(values: Any, field: str) -> list[Any]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise SearchProfileValidationError(f"{field} must be a list; got {values!r}")
    return list(values)


# --- Suggestion from the Profile ---------------------------------------------------------------

# What separates two roles in a headline. Explicit separators, plus a dash and the
# conjunctions "e"/"and"/"&" ONLY when surrounded by whitespace: an intra-word hyphen belongs
# to the role ("Front-end Developer" is one job, not two), and the letter "e" inside a word is
# not a conjunction. Portuguese and English both, since a Profile may be written in either.
_ROLE_SEPARATOR = re.compile(
    r"""
      [|/;,•·]              # explicit separators a headline uses to list titles
    | \s[-–—]\s             # a dash used AS a separator, never an intra-word hyphen
    | \s+(?:e|and|&)\s+     # standalone conjunctions only
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Punctuation and whitespace a split leaves hanging on a segment's edges.
_SEGMENT_EDGE = " \t\r\n.,;:·•-–—@"

# Below this a segment is punctuation noise ("Sr", "IA" survive; "|" and "e" do not).
_MIN_ROLE_LENGTH = 2


def roles_from_headline(headline: str | None) -> list[str]:
    """The target roles a headline states, verbatim, in order.

    Splitting is the whole algorithm: each segment is kept exactly as the user wrote it, only
    trimmed. Nothing is expanded, translated, or inferred -- "Desenvolvedor" does not become
    "Desenvolvedor de Software", and an empty headline yields an empty list rather than a
    plausible guess. The cost of the rule is visible and cheap ("Engenheiro de Dados e Software"
    yields "Software" as its own role, which the user deletes); the cost of the alternative is
    a search running for a career the candidate never claimed.
    """
    text = (headline or "").strip()
    if not text:
        return []
    roles: list[str] = []
    seen: set[str] = set()
    for segment in _ROLE_SEPARATOR.split(text):
        role = " ".join(segment.split()).strip(_SEGMENT_EDGE)
        if len(role) < _MIN_ROLE_LENGTH:
            continue
        key = role.casefold()
        if key in seen:
            continue
        seen.add(key)
        roles.append(role)
        if len(roles) == MAX_SUGGESTED_ROLES:
            break
    return roles


def suggest_from_profile(profile: ResumeDocument) -> SearchProfileOut:
    """A Search Profile SUGGESTION built from the Profile -- deterministic, never persisted.

    Only ``roles`` is derived; every other field is the default. The Profile has nothing else
    to say about what the user WANTS: its ``location`` is where they live rather than where
    they would work, and its ``skills`` -- which the spec's one-line sketch mentions -- have no
    field to land in, since the frozen contract's Search Profile has no skills. Reading skills
    into ``roles`` would turn "Python" and "Docker" into job titles to search for, which is
    exactly the invention the headline rule exists to prevent.

    ``updatedAt`` stays ``None``: this was never saved, and the form renders it as a draft the
    user PUTs.
    """
    suggestion = default_search_profile()
    suggestion.roles = roles_from_headline(getattr(profile, "headline", None))
    return suggestion
