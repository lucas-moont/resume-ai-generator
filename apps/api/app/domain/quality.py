"""Resume quality checks -- extracted from app/main.py (B2)."""

import re

from app.domain.keywords import extract_jd_keywords, normalize_token
from app.domain.locale import detect_locale
from app.domain.schemas import ProposalItem, ResumeDocument

# Weak bullet openers that signal generic, low-impact writing (checked case-insensitively).
WEAK_BULLET_OPENERS = (
    "responsible for",
    "responsável por",
    "responsavel por",
    "worked on",
    "worked with",
    "helped",
    "assisted",
    "tasked with",
    "duties included",
    "in charge of",
    "participated in",
    "i ",
    "we ",
    "my ",
    "atuei",
    "trabalhei",
    "ajudei",
    "fui responsável",
)


def resume_keyword_blob(resume: ResumeDocument) -> set[str]:
    parts: list[str] = [resume.headline or "", resume.summary or "", *resume.skills]
    for e in resume.experience:
        parts.extend(e.highlights or [])
        # Key Technologies is a keyword line by design (v7) -- it exists precisely so an ATS
        # matches the posting's technology names, so it counts toward coverage here.
        parts.extend(e.keyTechnologies or [])
    for p in resume.projects:
        parts.append(p.description or "")
        parts.append(p.name or "")
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9.+#/]*", " ".join(parts))
    return {normalize_token(t) for t in tokens if normalize_token(t)}


def has_weak_bullets(resume: ResumeDocument) -> bool:
    for e in resume.experience:
        for h in e.highlights or []:
            plain = re.sub(r"<[^>]+>", "", (h or "")).strip().lower()
            if not plain:
                continue
            if any(plain.startswith(op) for op in WEAK_BULLET_OPENERS):
                return True
    return False


def allows_lean_skills(agreed_improvements: list[ProposalItem] | None) -> bool:
    """Whether an approved plan deliberately shortened the skills list (v6, Relevance Filter).

    The skills-count check below exists to catch a lazy generation, and it only ever pushes
    UPWARD ("aim for 8-16"). Once the user has approved dropping their irrelevant skills, that
    same check fires on the intended result and hands the auto-improve refine pass an explicit
    instruction to re-inflate the list -- undoing the subtraction one step after the anchor
    honored it. Suppressing it here is what makes the drop survive the quality pass."""
    if not agreed_improvements:
        return False
    return any(
        getattr(item, "section", None) == "skills" and getattr(item, "op", None) == "drop"
        for item in agreed_improvements
    )


def _resume_language_sections(resume: ResumeDocument) -> list[str]:
    """The reader-visible PROSE of a resume, grouped into sections for language detection.

    Only fields whose wording is the LLM's own: summary, bullets, job titles, degrees, project
    write-ups. Deliberately excludes ``skills`` and ``keyTechnologies`` (technology names look
    identical in both languages and would dilute the signal toward English) and the contact
    fields (proper nouns and addresses, no language content at all).

    Grouped, NOT glued into one blob: judged as a single aggregate, one section
    drifting to the other language (an English summary above Portuguese bullets) nets out as the
    majority language and ships. Each section is detected on its own so a drifted one is visible.
    Sections are kept large enough to clear the per-section floor -- the experience block carries
    every title and bullet together, since a title on its own is too short to detect.
    """
    top = " ".join(p for p in (resume.summary or "", resume.headline or "") if p)
    experience: list[str] = []
    for e in resume.experience:
        experience.append(e.title or "")
        experience.extend(e.highlights or [])
    projects = " ".join(p.description or "" for p in resume.projects if p.description)
    education: list[str] = []
    for e in resume.education:
        education.append(e.degree or "")
        education.append(e.details or "")
    sections = [
        top,
        " ".join(p for p in experience if p),
        projects,
        " ".join(p for p in education if p),
    ]
    return [s for s in sections if s.strip()]


# A section shorter than this has too little prose for detect_locale to be trusted; below it the
# section is skipped rather than judged wrongly. Lower than a whole-document floor by design: a
# single section (a summary) is judged here, not the concatenation of every section at once.
_SECTION_MIN_WORDS = 15


def wrong_language_issue(resume: ResumeDocument, expected_locale: str | None) -> str | None:
    """The issue text when any section of the resume's PROSE is not in ``expected_locale``.

    This is the one place a quality issue is allowed to ask for a rewrite of everything, and the
    one case where doing so cannot fabricate anything: translating a stated fact leaves the fact
    identical (``prompts/system/generate.md`` already declares translating a title or degree
    required, and explicitly not invention). Contrast the contact gaps handled on the client --
    those the model genuinely cannot fill, so they are never issues.

    Detection runs on the generated prose, NOT on the ``locale`` field: since v6 that field is
    pinned by the server, so it always says the right thing and can no longer reveal the drift.
    It runs per section so a single drifted section cannot hide behind the correct
    ones -- an English summary over Portuguese bullets no longer nets out as Portuguese.
    """
    if not expected_locale:
        return None
    for section in _resume_language_sections(resume):
        if len(section.split()) < _SECTION_MIN_WORDS:
            continue
        detected = detect_locale(section)
        if detected is not None and detected != expected_locale:
            return (
                f"Part of the resume is written in {detected} but this job requires "
                f"{expected_locale}. Rewrite EVERY reader-visible field in {expected_locale} -- "
                "summary, all bullets, job titles, degrees and project descriptions -- keeping "
                "every fact identical. Company, institution, product and technology names stay "
                "as they are."
            )
    return None


def quality_issues(
    resume: ResumeDocument,
    job_description: str,
    *,
    allow_lean_skills: bool = False,
    expected_locale: str | None = None,
) -> list[str]:
    issues: list[str] = []

    # First, because it is the only issue that invalidates the whole document: a resume in the
    # wrong language fails the reader no matter how good its bullets are.
    language_issue = wrong_language_issue(resume, expected_locale)
    if language_issue:
        issues.append(language_issue)

    summary_words = len((resume.summary or "").split())
    if summary_words < 25:
        issues.append(
            "Write a stronger 2-4 sentence professional summary (role, seniority, "
            "domain, and top job-relevant strengths)."
        )

    if resume.experience:
        first = resume.experience[0]
        if len(first.highlights or []) < 3:
            issues.append(
                "Add 3-5 achievement bullets to the most recent role "
                "(action verb + what + how + outcome)."
            )
        short_bullets = any(
            len(re.sub(r"<[^>]+>", "", h or "").strip()) < 30
            for e in resume.experience
            for h in (e.highlights or [])
        )
        if short_bullets:
            issues.append("Expand thin experience bullets into concrete, one-line achievements.")

    if has_weak_bullets(resume):
        issues.append(
            "Rewrite bullets that start with weak openers (e.g. 'Responsible for', "
            "'Worked on', pronouns) using strong action verbs."
        )

    if len(resume.skills) < 6 and not allow_lean_skills:
        issues.append("List the relevant technologies the candidate actually has (aim for 8-16).")

    jd_keywords = extract_jd_keywords(job_description)
    if jd_keywords:
        blob = resume_keyword_blob(resume)
        top = jd_keywords[:12]
        missing = [k for k in top if k not in blob]
        if top and len(missing) > max(2, len(top) // 2):
            issues.append(
                "Align skills, summary, and bullets with key job terms where the candidate "
                f"has real evidence: {', '.join(missing[:8])}."
            )

    if len(resume.links) < 2:
        issues.append("Include at least two useful links (preferably LinkedIn + GitHub/Portfolio).")
    has_github_or_portfolio = any(
        ("github" in (l.label or "").lower())
        or ("github.com" in (l.url or "").lower())
        or ("portfolio" in (l.label or "").lower())
        for l in resume.links
    )
    if resume.links and not has_github_or_portfolio:
        issues.append("Include GitHub or Portfolio link when available.")

    weak_projects = [p for p in resume.projects if len((p.description or "").strip()) < 35]
    if resume.projects and weak_projects:
        issues.append("Expand project descriptions with concrete impact, stack, and scope.")
    return issues
