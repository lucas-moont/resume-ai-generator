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
    ``rationale`` containing an internal ``"`` can never break the block's own quoting."""
    lines = [
        f"{i}. [{item.section}] current: "
        f"{'null' if item.current is None else json.dumps(item.current, ensure_ascii=False)} "
        f"-> proposed: {json.dumps(item.proposed, ensure_ascii=False)} (rationale: {item.rationale})"
        for i, item in enumerate(items, start=1)
    ]
    return (
        "APPROVED IMPROVEMENT PLAN (agreed with the user in chat — implement EXACTLY these "
        "changes, nothing beyond them):\n" + "\n".join(lines)
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
- Keep the same set of experience entries, education, and projects; you may rewrite their wording (bullets/descriptions) and reorder/select skills from the profile.
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


def build_refine_user_msg(*, resume: ResumeDocument, pdf_block: str, message: str) -> str:
    """Compose the refine user prompt (shared by /api/refine and /api/refine/stream)."""
    return f"""Current resume JSON:
{resume.model_dump_json(indent=2)}

{pdf_block}User instruction:
{message.strip()}

Return the full updated resume JSON only."""
