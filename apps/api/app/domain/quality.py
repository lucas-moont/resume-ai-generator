"""Resume quality checks -- extracted from app/main.py (B2)."""

import re

from app.domain.keywords import extract_jd_keywords, normalize_token
from app.domain.schemas import ResumeDocument

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


def quality_issues(resume: ResumeDocument, job_description: str) -> list[str]:
    issues: list[str] = []

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

    if len(resume.skills) < 6:
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
