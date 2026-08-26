"""The Fit Score, in two stages (v7 ticket 08).

CONTEXT.md (Fit Score): "0-100, how well the Profile matches a Job Listing. Two stages: a cheap
keyword pass discards clear misses, the LLM scores only the surviving top N. A percentage only
-- no written justification."

The two stages exist because a Scan is a fan-out: a broad board query brings back dozens of
postings, most of which are not close, and paying an LLM call for each of them is the one cost
in this product that scales with how badly the search is tuned. So:

**Stage 1 -- ``keyword_fit``.** Deterministic, free, and honest about being coarse: how much of
what the posting ASKS FOR the Profile actually claims, weighted so the terms a posting repeats
count for more than the ones it mentions once. Its number is marked ``estimated`` wherever it
survives to the UI, because it measures vocabulary overlap and nothing else -- it cannot tell
"five years of Python" from "Python is a plus".

**Stage 2 -- the LLM.** One call per listing, for the top ``FIT_LLM_TOP_N`` by stage 1 that do
not already have a usable Fit in the Listing Memory. Its number replaces the estimate and is
written to the memory with the hash of the description that produced it, so the same posting is
never paid for twice -- and a Repost whose text was rewritten is (``fit_description_hash``).

Three rules that shape every branch below:

1. **A Fit already paid for wins over the cheap pass.** A listing the model scored is never
   dropped by stage 1, however thin its keywords are: we already know better than the estimate.
2. **No evidence is not a bad score.** A posting whose description yields no keywords at all, or
   a Profile with no skills listed, gives stage 1 nothing to measure -- so it abstains
   (``has_evidence`` False) and the listing is kept rather than discarded. It ranks low, which
   is the conservative cost, instead of vanishing.
3. **A failed LLM call costs a promotion, never the Scan.** A timeout, a provider error or an
   unparseable answer for ONE listing leaves that listing on its keyword estimate and the Scan
   continues. Nothing is written to the memory for it, so the next Scan tries again.

This module owns no session and no transaction: it takes what the Listing Memory remembers as
plain values (``RememberedFit``) and hands back plain values (``FitOutcome``). The Scan engine
does the reading and the writing. That is what makes the whole two-stage policy testable with
no database at all.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from app import config as config_module
from app.config import LLM_TIMEOUT_SECONDS, PROMPTS_DIR
from app.domain.entity_identity import skill_token
from app.domain.keywords import extract_jd_keywords
from app.domain.schemas import ProfileMaster
from app.prompt_loader import load_job_fit_system_prompt
from app.services import llm_client
from app.services.llm.fit_json_parser import parse_fit_json

logger = logging.getLogger(__name__)

# The LLM seam: the same shape as ``llm_client.chat_json``, so a test passes ``FakeLlm``.
LlmCall = Callable[..., Awaitable[str]]

# How many of a posting's keywords stage 1 weighs. A job description repeats its real
# requirements and mentions everything else once, so ``extract_jd_keywords``' frequency ordering
# already puts what matters first; past twenty terms the tail is the benefits section, the
# company boilerplate and the ATS filler. Cutting there keeps a long posting from diluting its
# own requirements into a low score.
KEYWORD_WINDOW = 20

# How much of a description the stage-2 prompt carries. Postings run long (LinkedIn pads with
# company blurb and legal text) and the requirements are at the top; this bounds the cost of a
# call that is repeated up to ``FIT_LLM_TOP_N`` times per Scan.
DESCRIPTION_CHARS_FOR_PROMPT = 6000

# How much of the Profile the stage-2 prompt carries, per part.
SUMMARY_CHARS_FOR_PROMPT = 600
MAX_EXPERIENCE_ENTRIES = 8
MAX_SKILLS = 60

FitSource = Literal["memory", "llm", "keyword"]


def description_hash(description: str) -> str:
    """sha256 of a posting's description -- what ``listing_memory.fit_description_hash`` stores.

    Lives here rather than in the Scan engine (where ticket 07 first put it, and from where it
    is still re-exported for its callers) because it is a Fit concept end to end: the column it
    feeds is named after the Fit, and the only question it answers is "was the stored Fit Score
    computed for THIS text?". A Repost whose description was rewritten must return to stage 2;
    the same text coming back must not.
    """
    return hashlib.sha256((description or "").encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RememberedFit:
    """What the Listing Memory remembers about one job's Fit, as plain values.

    Deliberately not the ``ListingMemory`` row itself: this module runs across ``await``
    boundaries while no Session is open, and a detached ORM instance is a lazy-load waiting to
    raise. Two fields are all the policy needs.
    """

    fit_score: int | None = None
    description_hash: str | None = None

    def matches(self, current_hash: str) -> bool:
        """Whether this remembered Fit may be reused for the description that hashes to
        ``current_hash``. Both halves are required: a Fit with no hash was never produced by
        stage 2 (nothing else writes one), and a hash that no longer matches belongs to text the
        model has not seen."""
        return self.fit_score is not None and self.description_hash == current_hash


@dataclass(frozen=True)
class FitCandidate:
    """One job to score: its Listing Memory key and the description to score it against."""

    key: str
    description: str


@dataclass(frozen=True)
class KeywordFit:
    """Stage 1's answer, with the evidence it rests on.

    ``score`` alone cannot distinguish "measured, and the overlap is nothing" from "there was
    nothing to measure", and those two must not lead to the same decision -- see rule 2 of the
    module docstring. ``has_evidence`` carries that distinction, and it takes BOTH sides: a
    posting whose text yields no keywords and a Profile that lists no technologies are the same
    situation seen from opposite ends. ``keywords``/``matched`` stay factual about the posting
    either way (and make a failing test say WHICH terms matched, which a bare integer never
    does).
    """

    score: int
    keywords: tuple[str, ...]
    matched: tuple[str, ...]
    has_evidence: bool


@dataclass(frozen=True)
class FitOutcome:
    """One listing's Fit after both stages, ready for the ``job_listings`` row.

    ``estimated`` is exactly ``job_listings.fit_estimated``: True means "this is the keyword
    pass's number", which the card renders as an approximation rather than a score.
    ``discarded`` means stage 1 judged it a clear miss -- the Scan drops the listing entirely
    rather than showing it at the bottom.
    """

    score: int
    estimated: bool
    source: FitSource
    description_hash: str
    discarded: bool = False

    @property
    def should_remember(self) -> bool:
        """Whether the Scan must write this Fit (and its hash) into the Listing Memory.

        Only stage 2's number is worth remembering. Persisting an ESTIMATE with a hash would be
        worse than not persisting it: the hash is exactly what tells a later Scan "this one is
        already scored, skip it", so a cached estimate would lock the listing out of stage 2
        forever.
        """
        return self.source == "llm"


# --- Stage 1: the keyword pass -----------------------------------------------------------------


def profile_tokens(profile: ProfileMaster | None) -> frozenset[str]:
    """Every technology the Profile CLAIMS, as ``skill_token``s.

    Two sources, both of them things the candidate asserted about themselves: the global
    ``skills`` list, and each role's Key Technologies (CONTEXT.md: Key Technologies -- "it names
    4-8 technologies THAT ROLE used"). Nothing else. Free prose (the summary, the bullets) is
    deliberately excluded: a bullet reading "migrated away from Oracle" would otherwise make
    Oracle a claimed skill, and stage 1's whole job is to be a conservative filter.
    """
    if profile is None:
        return frozenset()
    tokens: set[str] = set()
    for skill in profile.skills:
        token = skill_token(skill)
        if token:
            tokens.add(token)
    for entry in profile.experience:
        for technology in entry.keyTechnologies:
            token = skill_token(technology)
            if token:
                tokens.add(token)
    return frozenset(tokens)


def keyword_fit_detail(tokens: frozenset[str], description: str) -> KeywordFit:
    """Stage 1 for one posting, given the Profile's tokens (hoisted out of the loop by
    ``score_listings`` -- they are the same for every listing in a Scan).

    Coverage, weighted by rank: the posting's keywords come back from ``extract_jd_keywords``
    ordered by how often the posting repeats them, and the weight decays linearly across the
    window, so the term a posting names five times counts for more than the one it names once.
    Score = covered weight / total weight.

    Matching is EXACT ``skill_token`` equality, never substring -- the same discipline as Drop
    Targets (CONTEXT.md). Substring matching would make "Java" match "JavaScript" and hand a
    frontend candidate a backend posting, which is precisely the mistake this pass exists to
    avoid making cheaply.
    """
    keywords = tuple(extract_jd_keywords(description or "")[:KEYWORD_WINDOW])
    if not keywords or not tokens:
        # No evidence either way: an abstention, not a zero (module docstring, rule 2). The
        # score is 0 because there is genuinely nothing matched -- ``has_evidence`` is what the
        # caller reads to know it must not act on it.
        return KeywordFit(score=0, keywords=keywords, matched=(), has_evidence=False)
    total = 0.0
    covered = 0.0
    matched: list[str] = []
    count = len(keywords)
    for index, keyword in enumerate(keywords):
        weight = float(count - index)
        total += weight
        if keyword in tokens:
            covered += weight
            matched.append(keyword)
    score = int(round(100.0 * covered / total)) if total else 0
    return KeywordFit(
        score=max(0, min(100, score)),
        keywords=keywords,
        matched=tuple(matched),
        has_evidence=True,
    )


def keyword_fit(profile: ProfileMaster | None, description: str) -> int:
    """Stage 1's number for one posting, ``0..100`` -- the public, single-shot entry point.

    ``score_listings`` uses ``keyword_fit_detail`` instead, because it needs the evidence flag
    and computes the Profile's tokens once for the whole Scan.
    """
    return keyword_fit_detail(profile_tokens(profile), description).score


# --- Stage 2: the LLM ---------------------------------------------------------------------------


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "\n[...]"


def compact_profile(profile: ProfileMaster) -> str:
    """The Profile as the few lines stage 2 needs to judge a match.

    Not the full ``ProfileMaster`` JSON: this prompt runs up to ``FIT_LLM_TOP_N`` times per
    Scan, and the model is being asked for one integer, not for prose grounded in every bullet.
    What survives is what a recruiter's first pass reads -- the headline, a short summary, the
    skills, and each role's title/company/dates plus its Key Technologies. What is dropped is
    everything that only matters when WRITING a resume: the bullets, the links, the contact
    details (which must not travel to a provider for a ranking call at all).
    """
    lines: list[str] = [f"Headline: {profile.headline.strip() or '(none)'}"]
    summary = _truncate(profile.summary, SUMMARY_CHARS_FOR_PROMPT)
    if summary:
        lines.append(f"Summary: {summary}")
    if profile.skills:
        lines.append("Skills: " + ", ".join(s.strip() for s in profile.skills[:MAX_SKILLS] if s.strip()))
    if profile.experience:
        lines.append("Experience:")
        for entry in profile.experience[:MAX_EXPERIENCE_ENTRIES]:
            period = f"{entry.start or '?'} - {entry.end or 'present'}"
            line = f"- {entry.title} @ {entry.company} ({period})"
            technologies = [t.strip() for t in entry.keyTechnologies if t.strip()]
            if technologies:
                line += " | Key technologies: " + ", ".join(technologies)
            lines.append(line)
    if profile.education:
        lines.append(
            "Education: "
            + "; ".join(
                f"{e.degree} - {e.institution}".strip(" -") for e in profile.education[:4]
            )
        )
    return "\n".join(lines)


def build_fit_user_msg(profile: ProfileMaster, description: str) -> str:
    """The user half of the stage-2 call. Two labelled blocks and no instructions: every rule
    lives in the system prompt (``prompts/skills/job-fit.md``), which is the half a provider can
    cache across the twenty-five calls of one Scan."""
    return (
        "## Candidate profile\n"
        f"{compact_profile(profile)}\n\n"
        "## Job posting\n"
        f"{_truncate(description, DESCRIPTION_CHARS_FOR_PROMPT) or '(the board returned no description)'}"
    )


async def _score_one(
    candidate: FitCandidate,
    *,
    system: str,
    user: str,
    call: LlmCall,
    model: str | None,
    timeout_seconds: int,
    semaphore: asyncio.Semaphore,
) -> tuple[str, int | None]:
    """One stage-2 call. Returns ``(key, fit)``, with ``fit`` ``None`` for anything that went
    wrong -- rule 3 of the module docstring: the caller keeps the estimate.

    ``asyncio.CancelledError`` is deliberately NOT swallowed (it is a ``BaseException``, so
    ``except Exception`` lets it through): a cancelled Scan must stop, not quietly report that
    every listing failed to score.
    """
    async with semaphore:
        try:
            raw = await asyncio.wait_for(
                call(system, user, model=model), timeout=timeout_seconds
            )
        except TimeoutError:
            logger.warning(
                "job fit: stage 2 timed out after %ds for %s -- keeping the keyword estimate",
                timeout_seconds,
                candidate.key,
            )
            return candidate.key, None
        except Exception as exc:
            logger.warning(
                "job fit: stage 2 failed for %s (%s) -- keeping the keyword estimate",
                candidate.key,
                type(exc).__name__,
            )
            return candidate.key, None
    fit = parse_fit_json(raw)
    if fit is None:
        logger.info(
            "job fit: unusable stage 2 answer for %s -- keeping the keyword estimate",
            candidate.key,
        )
    return candidate.key, fit


async def score_listings(
    profile: ProfileMaster | None,
    candidates: Sequence[FitCandidate],
    memory: Mapping[str, RememberedFit] | None = None,
    *,
    llm: LlmCall | None = None,
    model: str | None = None,
    top_n: int | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, FitOutcome]:
    """Both stages for a whole Scan. Returns one ``FitOutcome`` per candidate, keyed by
    ``FitCandidate.key``.

    Order of decisions per listing, and why:

    1. **Stage 1 always runs** -- it is free, and its number is the fallback for everything
       downstream.
    2. **A usable remembered Fit wins** (``RememberedFit.matches``): the model already answered
       for this exact text, so the listing is neither discarded nor re-scored. This is the rule
       that keeps a Scan every hour from re-paying for the same fifty postings.
    3. **Below ``FIT_KEYWORD_FLOOR``, with evidence, is discarded** -- the clear miss the cheap
       pass exists to remove.
    4. **Everything else is a stage-2 candidate**, ranked by stage 1, capped at ``FIT_LLM_TOP_N``
       CALLS. The cap counts calls, not listings: a listing served from memory in step 2 costs
       nothing and must not consume a slot.

    A Scan with no Profile (none saved yet, or one that failed to load) skips stage 2 entirely
    and discards nothing: with nothing to match against, every number here would be an artifact
    of the empty side.
    """
    remembered = memory or {}
    tokens = profile_tokens(profile)
    floor = config_module.FIT_KEYWORD_FLOOR
    limit = config_module.FIT_LLM_TOP_N if top_n is None else top_n

    outcomes: dict[str, FitOutcome] = {}
    pending: list[tuple[int, FitCandidate, str]] = []  # (stage-1 score, candidate, hash)

    for candidate in candidates:
        current_hash = description_hash(candidate.description)
        stage1 = keyword_fit_detail(tokens, candidate.description)
        previous = remembered.get(candidate.key)
        if previous is not None and previous.matches(current_hash):
            outcomes[candidate.key] = FitOutcome(
                score=int(previous.fit_score or 0),
                estimated=False,
                source="memory",
                description_hash=current_hash,
            )
            continue
        if profile is not None and stage1.has_evidence and stage1.score < floor:
            outcomes[candidate.key] = FitOutcome(
                score=stage1.score,
                estimated=True,
                source="keyword",
                description_hash=current_hash,
                discarded=True,
            )
            continue
        outcomes[candidate.key] = FitOutcome(
            score=stage1.score,
            estimated=True,
            source="keyword",
            description_hash=current_hash,
        )
        pending.append((stage1.score, candidate, current_hash))

    if profile is None or not pending or limit <= 0:
        return outcomes

    # Deterministic order: stage-1 score descending, then the identity key, so two listings with
    # the same score never swap places between Scans (and a test can name the winner).
    pending.sort(key=lambda item: (-item[0], item[1].key))
    chosen = pending[:limit]

    system = load_job_fit_system_prompt(PROMPTS_DIR)
    call = llm or llm_client.chat_json
    semaphore = asyncio.Semaphore(max(1, config_module.fit_llm_concurrency()))
    timeout = LLM_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds

    results = await asyncio.gather(
        *(
            _score_one(
                candidate,
                system=system,
                user=build_fit_user_msg(profile, candidate.description),
                call=call,
                model=model,
                timeout_seconds=timeout,
                semaphore=semaphore,
            )
            for _score, candidate, _hash in chosen
        )
    )

    scored = 0
    for (key, fit), (_score, _candidate, current_hash) in zip(results, chosen):
        if fit is None:
            continue  # the keyword estimate already sitting in ``outcomes`` stands
        outcomes[key] = FitOutcome(
            score=fit,
            estimated=False,
            source="llm",
            description_hash=current_hash,
        )
        scored += 1
    logger.info(
        "job fit: %d candidates, %d reused from memory, %d discarded, %d sent to the LLM, %d scored",
        len(candidates),
        sum(1 for o in outcomes.values() if o.source == "memory"),
        sum(1 for o in outcomes.values() if o.discarded),
        len(chosen),
        scored,
    )
    return outcomes
