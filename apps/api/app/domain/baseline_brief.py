"""Target Brief for a Baseline Resume (v6) -- the synthetic "posting" a no-posting request runs on.

Every generation path in this app is anchored to a job description: the Analysis compares Profile
x posting, the Improvement Proposal's rationales must cite the posting, ``resolve_locale`` reads
the posting's language, and ``improvement_proposals.job_description`` is NOT NULL. A request for
an open resume ("um curriculo generalista pro meu Indeed") has no posting, so rather than carving
a second, parallel pipeline that skips the Proposal step -- and with it the review the user
actually wants -- a baseline request builds a **Target Brief**: a short, explicit statement of the
career target and of the fact that there is no single posting, which every existing stage then
consumes exactly where a job description used to go.

This keeps ONE generation pipeline and one invariant ("no Resume without an approved Proposal"),
at the cost of the ``job_description`` column now holding either a real posting or a brief. That
tradeoff is deliberate and recorded in CONTEXT.md (Target Brief) and on the table itself.

The brief is prompt text, never shown to the user, so it is written in English regardless of the
resume's own locale -- like every other system prompt in ``prompts/``. The output language is
carried separately, by ``resolve_locale``'s own argument.
"""

from __future__ import annotations

from app.domain.schemas import ResumeDocument

# Job boards a baseline resume typically gets published on. Named in the brief only to tell the
# model who the reader is (many recruiters, many ATS setups) -- never to target one board's format.
_PUBLISHING_CONTEXT = "a public job board profile (e.g. Indeed), read by many recruiters across many companies"


def has_career_target(profile: ResumeDocument) -> bool:
    """Whether the Profile states what this person does.

    A baseline resume still needs ONE career target: broad is not the same as unfocused, and a
    resume that argues for nothing in particular fails every screen it reaches. The headline is
    that target. Without it there is nothing to be broad *about*, and the caller asks instead of
    inventing a direction for the candidate's career.
    """
    return bool((profile.headline or "").strip())


def build_baseline_brief(profile: ResumeDocument, user_message: str) -> str:
    """Compose the Target Brief that stands in for a job description.

    The career target comes from the Profile's own ``headline``, and the user's own words are
    appended verbatim as a note rather than parsed. That is deliberate: extracting "front-end"
    from "quero um generalista de front-end" with a heuristic is exactly the kind of guess that
    goes wrong quietly, while the model reading the note handles it correctly and, when the note
    names no target, simply has nothing to override. Determinism where it decides routing;
    language understanding where it is language.
    """
    target = (profile.headline or "").strip()
    note = " ".join((user_message or "").split()).strip()
    note_block = f"\nThe candidate's own words for this request: \"{note}\"\n" if note else ""
    # The "follow their words" rule belongs to the note block, not to the fixed body: with no note
    # there are no words to follow, and instructing the model to obey something absent from the
    # prompt invites it to invent what that something said.
    note_rule = (
        "\n- If the candidate's own words above name a different or narrower target than the "
        "career target\n  line, follow THEIR words: they know which door they are knocking on."
        if note
        else ""
    )

    return f"""TARGET BRIEF — there is no specific job posting for this resume.

The candidate is not applying to one posting. They want an open, baseline resume for {_PUBLISHING_CONTEXT}.

Career target: {target}
{note_block}
Because there is no single posting to match, judge relevance against the career target above, and
favour BREADTH within that target over precision against any one job:

- Keep what a recruiter hiring for this career target would look for across the COMMON variations
  of the role — not one company's particular stack.
- Still leave out what has no bearing on the career target at all. An open resume is broad, not
  unfocused: it argues for one kind of role, to many companies.
- Prefer widely recognized, market-standard terminology over any one employer's internal
  vocabulary, since this document is filtered by many different ATS setups.
- Keep the summary positioning-led — who this professional is and what they do — rather than
  addressed to a particular company or team.{note_rule}

Everything else is unchanged: never invent a fact, and never claim a skill or experience the
Profile does not contain."""


# The brief's own first line, used as its marker. A Target Brief is stored in the same
# ``improvement_proposals.job_description`` column a real posting goes into, so any later stage
# that reads that column and cares whether it holds a posting checks with ``is_target_brief``.
_BRIEF_MARKER = "TARGET BRIEF"


def is_target_brief(text: str | None) -> bool:
    """Whether this ``job_description`` value is a Target Brief rather than a real posting.

    Exists for one specific reason, found by a test: the brief is ENGLISH prompt text, so any
    stage that resolves the output locale by sniffing the job description's language reads "en"
    off it and ships a Portuguese-targeted baseline resume in English. Callers use this to skip
    language detection on a brief and fall back to the Profile's locale instead.
    """
    return bool(text) and text.lstrip().startswith(_BRIEF_MARKER)
