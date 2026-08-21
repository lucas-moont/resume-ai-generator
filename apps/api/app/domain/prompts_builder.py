"""User-prompt assembly for the generate/refine LLM calls -- extracted from app/main.py (B2).

``build_refine_user_msg`` was inlined identically in both ``/api/refine`` and
``/api/refine/stream``; extracting it here removes that duplication without changing the
resulting prompt text.
"""

import json

from app.domain.schemas import ProposalItem, ResumeDocument


def _format_agreed_improvements_block(items: list[ProposalItem]) -> str:
    """Renders the APPROVED IMPROVEMENT PLAN block (docs/v4-improvement-proposal.md §4.3).
    Strings are ``json.dumps``-quoted (not just wrapped in literal quotes) so a ``proposed``/
    ``rationale`` containing an internal ``"`` can never break the block's own quoting.

    QA-02: the hard rules below (see ``build_generation_user_msg``) set conservative defaults
    about which entries and skills survive -- exactly the conventions an approved plan may need
    to override (e.g. adding a skill, reordering projects). Without an explicit precedence
    statement, the LLM was resolving that conflict in favor of those defaults and silently
    dropping the plan items. This block states the plan wins over them -- only the truthfulness
    rule (never invent facts) still outranks it -- and ends with a checklist instruction so the
    model self-checks every item before returning.

    v6 (Relevance Filter) adds the DROP/COMPRESS gloss at the end: the ops are new enough to the
    plan vocabulary that spelling out what each one licenses is cheaper than hoping the model
    infers "omit entirely" from the word alone. See ``_format_agreed_item`` for the per-line
    shape."""
    lines = [_format_agreed_item(i, item) for i, item in enumerate(items, start=1)]
    return (
        "APPROVED IMPROVEMENT PLAN (agreed with the user in chat — implement EXACTLY these "
        "changes, nothing beyond them):\n" + "\n".join(lines) + "\n\n"
        "This plan takes precedence over the default conventions below regarding skill "
        "selection/order and experience/project order — it was agreed with the user in chat. "
        "Only the truthfulness rule (never invent facts not present in the profile) still "
        "outranks this plan.\n"
        "A DROP item is an instruction to OMIT the listed entries from the output entirely — "
        "the user agreed they do not belong on a resume for this job. A COMPRESS item keeps the "
        "entry (employer, title and dates unchanged) but reduces it to a single factual bullet.\n"
        "Before returning, verify EVERY numbered item above is reflected in the output."
    )


def _format_agreed_item(index: int, item: ProposalItem) -> str:
    """One numbered line of the APPROVED IMPROVEMENT PLAN block.

    A ``rewrite`` item renders exactly as it did before v6 (``current: ... -> proposed: ...``),
    which is what keeps the plan-block tests' golden strings valid. The v6 ops render in their
    own imperative shape instead, because "current -> proposed" reads as a text swap and the LLM
    was resolving such a line in favor of the conservative hard rules (the same failure mode
    QA-02 documented above) -- a DROP has to look like a removal to be obeyed as one.
    ``targets`` are ``json.dumps``-quoted for the same reason every other field is: an internal
    quote must never break the block's own quoting."""
    targets = ", ".join(json.dumps(t, ensure_ascii=False) for t in item.targets)
    if item.op == "drop":
        subject = targets or json.dumps(item.proposed, ensure_ascii=False)
        return (
            f"{index}. [{item.section}] DROP (remove from the resume entirely): {subject} "
            f"(rationale: {item.rationale})"
        )
    if item.op == "compress":
        subject = targets or json.dumps(item.proposed, ensure_ascii=False)
        return (
            f"{index}. [{item.section}] COMPRESS (keep the entry, reduce it to one factual "
            f"bullet): {subject} (rationale: {item.rationale})"
        )
    if item.op == "add":
        return (
            f"{index}. [{item.section}] ADD: {json.dumps(item.proposed, ensure_ascii=False)} "
            f"(rationale: {item.rationale})"
        )
    return (
        f"{index}. [{item.section}] current: "
        f"{'null' if item.current is None else json.dumps(item.current, ensure_ascii=False)} "
        f"-> proposed: {json.dumps(item.proposed, ensure_ascii=False)} (rationale: {item.rationale})"
    )


def build_generation_user_msg(
    *,
    job_description: str,
    profile: ResumeDocument,
    pdf_block: str,
    project_notes: str,
    locale: str,
    agreed_improvements: list[ProposalItem] | None = None,
) -> str:
    """Compose a lean, directive generation prompt.

    Supporting sources are appended only when they carry content: empty placeholder blocks and
    a raw GitHub dump were observed to derail smaller local models into emitting a generic
    template resume. The profile stays the single authoritative source.

    ``agreed_improvements`` (v4 ticket B2): when the user approved an Improvement Proposal in
    chat, its items are injected as an APPROVED IMPROVEMENT PLAN block right before the hard
    rules, directing the LLM to implement exactly those changes. Omitting it (the default)
    leaves the prompt byte-identical to the pre-v4 output -- see
    ``tests/unit/test_prompts_builder.py::TestBuildGenerationUserMsgCharacterization``.
    """
    sources: list[str] = []
    if pdf_block and pdf_block.strip():
        sources.append(pdf_block.strip())
    if project_notes and project_notes.strip():
        sources.append("Project notes:\n" + project_notes.strip())
    sources_block = ""
    if sources:
        sources_block = (
            "\n\nSupporting sources (use ONLY to choose wording and which real facts to emphasize; "
            "never introduce employers, roles, projects, or numbers that are not in the profile):\n"
            + "\n\n".join(sources)
        )
    plan_block = ""
    if agreed_improvements:
        plan_block = _format_agreed_improvements_block(agreed_improvements) + "\n\n"
    return f"""Job description:
---
{job_description.strip()}
---

{plan_block}Tailor a resume for the candidate described in the CANDIDATE PROFILE below. Hard rules:
- Use ONLY facts present in the profile (and supporting sources). Do NOT invent employers, job titles, dates, schools, certifications, projects, or metrics.
- Keep the candidate's name and contact details EXACTLY as in the profile.
- Keep every employer, role, dates and school from the profile — never open a gap in the timeline. You may rewrite their wording (bullets/descriptions) freely.
- Relevance beats completeness. Give each role space proportional to how much it serves THIS job: a directly relevant role gets its full 3-5 bullets, a role with little bearing on the job gets one factual bullet (never zero). Same for skills and projects — select the ones this job actually calls for and leave the rest out, rather than listing everything the profile happens to contain. A focused resume of 9 skills beats a padded one of 16.
- If the profile lacks something the job wants, omit it — never fabricate it.

CANDIDATE PROFILE (authoritative JSON — the single source of truth):
{profile.model_dump_json(indent=2)}{sources_block}

Target locale for labels and prose: {locale}
Return the tailored resume as JSON only, using the same schema as the profile."""


def build_proposal_analysis_user_msg(
    *,
    profile: ResumeDocument,
    job_description: str,
    locale: str,
) -> str:
    """Compose the Analysis user message (v4 ticket B2, spec §4.1): Profile JSON + job
    description + locale ONLY -- deliberately lean (no PDF/project-notes/GitHub context), unlike
    ``build_generation_user_msg``'s ``sources_block``, since the Analysis only needs to compare
    the profile against the job, not author a full resume."""
    return f"""Candidate profile (authoritative JSON):
{profile.model_dump_json(indent=2)}

Job description:
---
{job_description.strip()}
---

Target locale for "message" and every item's "proposed"/"rationale": {locale}
Return the Improvement Proposal as JSON only, following the schema in the system prompt."""


def build_proposal_turn_user_msg(
    *,
    items: list[ProposalItem],
    revision: int,
    history_text: str,
    message: str,
    locale: str,
) -> str:
    """Compose the Proposal Turn user message (v4 ticket B2, spec §4.2): the current proposal
    (items + revision), recent chat history (already formatted by the caller, e.g.
    ``chat_service._format_history`` -- this builder does not know how history is assembled),
    the user's message, and locale."""
    items_json = json.dumps([item.model_dump() for item in items], ensure_ascii=False, indent=2)
    history_block = f"\n\n{history_text}" if history_text.strip() else ""
    return f"""Current Improvement Proposal (revision {revision}):
{items_json}{history_block}

User's message:
{message.strip()}

Target locale for "reply" and any item's "proposed"/"rationale": {locale}
Return the classification as JSON only, following the schema in the system prompt."""


def build_analysis_user_msg(
    *,
    message: str,
    locale: str,
    linkedin_pdf_block: str = "",
) -> str:
    """Compose the Analysis Turn user message (v5, docs/v5-profile-analysis.md §Backend.4).

    Two input modes feed one motor: a conversational per-section request (``message`` carries
    the user's text, e.g. "melhora meu headline, atual é X, minha área é Y") and/or a LinkedIn
    PDF export whose extracted text arrives as ``linkedin_pdf_block`` (default empty, additive).
    The PDF is explicitly framed as material to critique, NEVER profile truth to ingest -- it is
    the user's LinkedIn, analyzed, and never runs through the Merge pipeline (spec §Backend.6)."""
    pdf_section = ""
    if linkedin_pdf_block and linkedin_pdf_block.strip():
        pdf_section = (
            "\n\nLinkedIn profile (extracted from the user's uploaded PDF export — analyze this "
            "whole profile section by section; it is material to critique, NOT profile truth to "
            "ingest):\n" + linkedin_pdf_block.strip()
        )
    return f"""User request:
{message.strip()}{pdf_section}

Target locale for every reader-visible string (suggestion, rationale, summary, reply): {locale}
Return the analysis or a clarifying question as JSON only, following the schema in the system prompt."""


def build_refine_user_msg(
    *,
    resume: ResumeDocument,
    pdf_block: str,
    message: str,
    project_sources_block: str = "",
) -> str:
    """Compose the refine user prompt (shared by /api/refine and /api/refine/stream).

    ``project_sources_block`` (default empty, additive) lets a caller append project
    context (local notes and/or GitHub) the same way ``build_generation_user_msg`` appends
    its ``sources_block`` -- keeping the two prompts consistent when refine also has this
    context available.
    """
    sources_block = ""
    if project_sources_block and project_sources_block.strip():
        sources_block = (
            "\n\nSupporting sources (use ONLY to choose wording and which real facts to emphasize; "
            "never introduce employers, roles, projects, or numbers that are not in the profile):\n"
            + project_sources_block.strip()
        )
    return f"""Current resume JSON:
{resume.model_dump_json(indent=2)}

{pdf_block}User instruction:
{message.strip()}{sources_block}

Return the full updated resume JSON only."""
