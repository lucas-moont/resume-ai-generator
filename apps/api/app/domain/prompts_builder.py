"""User-prompt assembly for the generate/refine LLM calls -- extracted from app/main.py (B2).

``build_refine_user_msg`` was inlined identically in both ``/api/refine`` and
``/api/refine/stream``; extracting it here removes that duplication without changing the
resulting prompt text.
"""

from app.domain.schemas import ResumeDocument


def build_generation_user_msg(
    *,
    job_description: str,
    profile: ResumeDocument,
    pdf_block: str,
    project_notes: str,
    locale: str,
) -> str:
    """Compose a lean, directive generation prompt.

    Supporting sources are appended only when they carry content: empty placeholder blocks and
    a raw GitHub dump were observed to derail smaller local models into emitting a generic
    template resume. The profile stays the single authoritative source.
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
    return f"""Job description:
---
{job_description.strip()}
---

Tailor a resume for the candidate described in the CANDIDATE PROFILE below. Hard rules:
- Use ONLY facts present in the profile (and supporting sources). Do NOT invent employers, job titles, dates, schools, certifications, projects, or metrics.
- Keep the candidate's name and contact details EXACTLY as in the profile.
- Keep the same set of experience entries, education, and projects; you may rewrite their wording (bullets/descriptions) and reorder/select skills from the profile.
- If the profile lacks something the job wants, omit it — never fabricate it.

CANDIDATE PROFILE (authoritative JSON — the single source of truth):
{profile.model_dump_json(indent=2)}{sources_block}

Target locale for labels and prose: {locale}
Return the tailored resume as JSON only, using the same schema as the profile."""


def build_refine_user_msg(*, resume: ResumeDocument, pdf_block: str, message: str) -> str:
    """Compose the refine user prompt (shared by /api/refine and /api/refine/stream)."""
    return f"""Current resume JSON:
{resume.model_dump_json(indent=2)}

{pdf_block}User instruction:
{message.strip()}

Return the full updated resume JSON only."""
