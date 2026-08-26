"""One-click Resume and "Abrir no chat" (v7 ticket 10, spec Backend-5).

The two buttons on a Job Listing, and the two opposite answers to the same question -- what
does the user pay to turn a posting into a resume?

* **One-click Resume** (CONTEXT.md) generates the whole thing with no conversation: Analysis ->
  Improvement Proposal **auto-approved as produced** -> generation -> PDF. It is the ONE
  exception to "no Resume without an approved Improvement Proposal", and it is a narrow one --
  the proposal is real, itemized and persisted, only the human approval turn is skipped. The
  pipeline itself is not forked: both steps run ``chat_service``'s own sessionless seams
  (``propose_for_description`` / ``approve_and_generate``), so every guard-rail the chat has
  (Patch Validator, Relevance Filter, ``MIN_SKILLS_AFTER_DROPS``, "an employer never drops off
  the timeline") applies here without being restated.
* **Abrir no chat** spends nothing: it creates an ordinary ``kind='resume'`` session seeded
  with the posting and hands back its id. The user then sends it and gets the normal Analysis
  turn with a Pending Proposal to argue with. No new path through the chat exists for this --
  that is why the description is written as a plain ``user`` message and no LLM is called here.

Four rules this module owns, none of them expressible anywhere else:

1. **The second click is free.** The Listing Memory holds ``resume_version_id`` across Scans,
   so a listing that already has a One-click Resume re-renders the STORED document. Spending a
   second LLM call to answer "let me download that again" would be the whole feature's cost
   with none of its value. ``regenerate=True`` is the explicit, user-chosen way to pay it.
2. **A posting too thin to be a posting is refused, not guessed at.** ``looks_like_job
   _description`` is the same heuristic the chat's "generate" intent uses; below it there is no
   job to tailor to, and generating from a title and two lines would produce a confident,
   useless document.
3. **One One-click per listing at a time.** A double click is the normal way to get two
   concurrent generations, which would burn two LLM calls and race to write one memory.
4. **A failed generation leaves the memory exactly as it was.** Nothing is committed until the
   document exists, so a 502 costs the user a retry, never a listing that claims to have a
   resume it cannot produce.

The locale is the POSTING's (CONTEXT.md: Locale Authority), read off ``JobListing.locale``,
which the Scan already resolved from the description with the same ``detect_locale`` the chat
would run -- not re-derived here, so the badge the user saw and the resume they get agree.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass

from sqlmodel import Session

from app.db.tables import ChatSession, JobListing, ResumeVersion
from app.domain.chat_intent import looks_like_job_description
from app.domain.locale import DEFAULT_LOCALE, SUPPORTED_LOCALES, normalize_locale
from app.domain.schemas import ResumeDocument
from app.repositories import chat_repo, jobs_repo, resume_repo
from app.services import chat_service, settings_service
from app.services.jobs import listing_query
from app.services.llm_client import llm_backend_label
from app.services.pdf_export import render_resume_pdf
from app.services.profile_resolution import resolve_active_profile

# --- Errors ------------------------------------------------------------------------------
#
# One class per HTTP answer the router owes the user, rather than one carrying a status code:
# deciding what a failure MEANS is this module's job, deciding what number it wears is the
# router's (routers/jobs.py), and the same distinction already holds for the Scan engine's
# ``ScanAlreadyRunning``.


class OneClickError(Exception):
    """Base for every refusal below -- lets a caller that does not care which one, catch one."""


class ListingNotFound(OneClickError):
    """No such Job Listing in the LAST Scan -- which includes every id from a previous one."""


class DescriptionTooShort(OneClickError):
    """The posting is too thin to tailor a resume to (rule 2). Its message is the CODE
    ``description_too_short``, not copy: the web already owns the sentence it shows for this
    (ticket 13) and must not print a backend string in its place."""


class OneClickAlreadyRunning(OneClickError):
    """This listing is already generating (rule 3). Its message IS user-facing copy."""


class OneClickGenerationFailed(OneClickError):
    """The Analysis or the generation failed -- provider down, timeout, unusable output. Its
    message is user-facing copy naming what to do next; the underlying error is chained as
    ``__cause__`` for the log, never shown."""


class PdfRenderFailed(OneClickError):
    """The document exists and is saved; turning it into a PDF is what failed. Distinct from
    ``OneClickGenerationFailed`` because the retry is free -- the Resume is already in the
    Listing Memory, so the next click renders it without an LLM."""


DESCRIPTION_TOO_SHORT_CODE = "description_too_short"

_ALREADY_RUNNING_MESSAGE = (
    "Já estou gerando o currículo desta vaga. Espere alguns segundos e tente de novo."
)
_GENERATION_FAILED_MESSAGE = (
    "Não consegui gerar o currículo desta vaga: o provedor de IA não respondeu. "
    "Tente de novo em instantes, ou abra a vaga no chat para acompanhar a análise."
)
_PDF_FAILED_MESSAGE = (
    "O currículo foi gerado e está salvo, mas a conversão para PDF falhou. "
    "Clique de novo para baixar — não vai custar uma nova geração."
)


# --- One-click Resume ----------------------------------------------------------------------


@dataclass(frozen=True)
class OneClickPdf:
    """What the endpoint answers with: the bytes, the file name they should land under, and
    which ``resume_versions`` row produced them (``regenerated`` says whether this call paid
    for it or re-rendered what the memory already had -- asserted by the tests, and the honest
    thing to log)."""

    content: bytes
    filename: str
    resume_version_id: int
    regenerated: bool


# One ``asyncio.Lock`` per listing id, created on demand (rule 3). Not a global lock: two
# DIFFERENT listings being one-clicked at once is a perfectly reasonable thing to do and costs
# nothing shared. Entries are dropped on release, which is safe precisely because a contending
# click is REFUSED rather than queued -- a lock therefore never has waiters, so nobody can be
# left holding a lock that is no longer the one in the dict. Checking ``locked()`` and
# acquiring is not a race for the same reason ``ScanRunner.run``'s is not: there is no ``await``
# between them on this single event loop.
_locks: dict[int, asyncio.Lock] = {}


def _lock_for(listing_id: int) -> asyncio.Lock:
    """The listing's lock, refusing rather than queueing when it is already held."""
    lock = _locks.get(listing_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[listing_id] = lock
    if lock.locked():
        raise OneClickAlreadyRunning(_ALREADY_RUNNING_MESSAGE)
    return lock


def _release_lock(listing_id: int, lock: asyncio.Lock) -> None:
    lock.release()
    if _locks.get(listing_id) is lock and not lock.locked():
        del _locks[listing_id]


async def one_click_resume(
    session: Session,
    listing_id: int,
    *,
    regenerate: bool = False,
    model: str | None = None,
    backend_label: str | None = None,
) -> OneClickPdf:
    """Generate (or re-render) the One-click Resume for one Job Listing.

    Raises ``ListingNotFound`` / ``DescriptionTooShort`` / ``OneClickAlreadyRunning`` /
    ``OneClickGenerationFailed`` / ``PdfRenderFailed``, plus ``FileNotFoundError`` and
    ``ProfileValidationError`` straight from profile resolution -- there is no Profile to
    tailor in those two cases, and the app already answers them the same way everywhere else.
    """
    listing = jobs_repo.get_listing(session, listing_id)
    if listing is None:
        raise ListingNotFound(f"Job Listing {listing_id} not found")

    lock = _lock_for(listing_id)
    await lock.acquire()
    try:
        return await _one_click(
            session,
            listing,
            regenerate=regenerate,
            model=model,
            backend_label=backend_label or llm_backend_label(),
        )
    finally:
        _release_lock(listing_id, lock)


async def _one_click(
    session: Session,
    listing: JobListing,
    *,
    regenerate: bool,
    model: str | None,
    backend_label: str,
) -> OneClickPdf:
    identity_key = listing.identity_key
    memory = jobs_repo.get_memory(session, identity_key)

    if not regenerate and memory is not None and memory.resume_version_id is not None:
        stored = resume_repo.get(session, memory.resume_version_id)
        if stored is not None:
            return await _render(listing, stored, regenerated=False)
        # A dangling soft ref (the version was deleted out from under the memory -- see
        # db/tables.py on soft refs). Falling through and generating is better than 404ing over
        # bookkeeping the user never saw; the new id overwrites the dead one below.

    if not looks_like_job_description(listing.description):
        raise DescriptionTooShort(DESCRIPTION_TOO_SHORT_CODE)

    # Before the try: "there is no Profile" is not a generation failure, and dressing it up as
    # a 502 would tell the user to retry something that will never work until they add one.
    resolved_profile = resolve_active_profile(session)
    locale = resolve_listing_locale(listing)

    try:
        proposal, _parsed = await chat_service.propose_for_description(
            session,
            profile=resolved_profile.profile,
            job_description=listing.description,
            locale=locale,
            model=model,
            # CONTEXT.md (One-click Resume): auto-approved as produced. The proposal is real
            # and persisted, it just belongs to a Job Listing rather than to a conversation.
            session_id=None,
        )
        resume_row, _resume_doc = await chat_service.approve_and_generate(
            session,
            proposal=proposal,
            model=model,
            locale=locale,
            backend_label=backend_label,
        )
    except Exception as e:
        # Rule 4. ``propose_for_description`` only flushes, so a failure between the two calls
        # rolls the proposal away entirely; a failure inside the generation happens before
        # ``approve_and_generate``'s own commit. Either way nothing is left behind -- unlike
        # the chat, where a `proposed` row survives BECAUSE there is a conversation to
        # reapprove it in.
        session.rollback()
        raise OneClickGenerationFailed(_GENERATION_FAILED_MESSAGE) from e

    listing_query.remember_one_click_resume(
        session, identity_key, resume_version_id=int(resume_row.id or 0), memory=memory
    )
    session.commit()
    return await _render(listing, resume_row, regenerated=True)


def resolve_listing_locale(listing: JobListing) -> str:
    """The Resume's language: the POSTING's (CONTEXT.md: Locale Authority).

    ``JobListing.locale`` is a plain ``str`` for the same reason ``ResumeDocument.locale`` is,
    so it is folded onto the two supported languages here rather than trusted -- and threaded
    into generation as the EXPLICIT locale, which ``resolve_locale`` honours over its own
    detection. Re-sniffing the description here would risk disagreeing with the badge the user
    read on the card before clicking.
    """
    folded = normalize_locale(listing.locale)
    return folded if folded in SUPPORTED_LOCALES else DEFAULT_LOCALE


async def _render(listing: JobListing, row: ResumeVersion, *, regenerated: bool) -> OneClickPdf:
    resume = ResumeDocument.model_validate_json(row.data)
    try:
        content = await render_resume_pdf(resume, settings_service.get_resume_template())
    except Exception as e:
        raise PdfRenderFailed(_PDF_FAILED_MESSAGE) from e
    return OneClickPdf(
        content=content,
        filename=one_click_file_name(listing),
        resume_version_id=int(row.id or 0),
        regenerated=regenerated,
    )


_NON_SLUG = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFD", value) if not unicodedata.combining(ch)
    )
    return _NON_SLUG.sub("-", stripped.lower()).strip("-")


def one_click_file_name(listing: JobListing) -> str:
    """``curriculo-<empresa>-<cargo>.pdf`` -- the same rule as the web's ``oneClickFileName``
    (ticket 13), so the ``Content-Disposition`` this endpoint sends and the name the browser
    saves under agree instead of quietly differing. A downloads folder holding ten
    ``resume.pdf`` files is what both exist to avoid."""
    parts = [part for part in (_slugify(listing.company), _slugify(listing.title)) if part]
    return f"curriculo-{'-'.join(parts)}.pdf" if parts else "curriculo.pdf"


# --- Abrir no chat ---------------------------------------------------------------------------


def open_in_chat(session: Session, listing_id: int) -> ChatSession:
    """Create the chat session for a Job Listing and seed it with the posting. No LLM call.

    The session is an ORDINARY ``kind='resume'`` one -- it shows up in the sidebar, it is
    renamable, it rehydrates like any other -- and the description is stored twice on purpose:
    on ``chat_sessions.job_description`` (what the composer reads) and as the first ``user``
    message (what the transcript shows). The message carries no ``intent``, exactly like every
    user message the chat itself writes: intent is what the SERVER decides when a turn runs,
    and stamping a guess on a message nobody has sent yet would be the first place in this
    codebase where a stored intent was not the one that actually routed.

    Nothing is generated here. When the user sends that description,
    ``classify_intent`` sees a session with no active resume and no Pending Proposal and routes
    it to "generate" -> the Analysis -> a Pending Proposal, which is precisely the flow the
    button promises ("the full flow, with the proposal reviewed"). The caller commits.
    """
    listing = jobs_repo.get_listing(session, listing_id)
    if listing is None:
        raise ListingNotFound(f"Job Listing {listing_id} not found")

    chat_session = chat_repo.create_session(
        session,
        title=chat_session_title(listing),
        job_description=listing.description,
        locale=resolve_listing_locale(listing),
        kind="resume",
    )
    chat_repo.append_message(
        session,
        session_id=int(chat_session.id or 0),
        role="user",
        content=listing.description,
    )
    chat_repo.touch_session(session, int(chat_session.id or 0))
    return chat_session


def chat_session_title(listing: JobListing) -> str:
    """"Empresa · Cargo" (spec Backend-5). The Analysis will rename the session to the title the
    LLM reads off the posting on the first turn (``_handle_propose_turn``); until then this is
    what the sidebar shows, and it is better than "Nova conversa" because the user already knows
    which job they clicked."""
    company = listing.company.strip()
    title = listing.title.strip()
    if company and title:
        return f"{company} · {title}"
    return company or title or "Vaga"
