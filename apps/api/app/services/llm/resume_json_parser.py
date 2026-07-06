from __future__ import annotations

import json
import re

from app.models import ResumeDocument
from app.services.html_sanitize import sanitize_resume_for_display


def _looks_like_resume_core(d: dict) -> bool:
    return any(
        k in d
        for k in (
            "fullName",
            "headline",
            "summary",
            "experience",
            "skills",
            "projects",
            "name",
            "title",
            "description",
            "education",
        )
    )


def _unwrap_resume_dict(data: dict) -> dict:
    for key in ("resume", "body", "curriculum", "document", "data", "content", "cv", "output"):
        inner = data.get(key)
        if isinstance(inner, dict) and _looks_like_resume_core(inner):
            return dict(inner)
    if isinstance(data.get("body"), dict) and _looks_like_resume_core(data["body"]):
        return dict(data["body"])
    if _looks_like_resume_core(data):
        return dict(data)
    return dict(data)


_GENERIC_DOC_TITLES = frozenset(
    {"resume", "cv", "curriculum vitae", "curriculum", "curriculo", "currículo"}
)
_NON_TECH_SKILLS = frozenset(
    {
        "english",
        "inglês",
        "ingles",
        "portuguese",
        "português",
        "portugues",
        "spanish",
        "espanhol",
        "francês",
        "frances",
        "communication",
        "comunicação",
        "leadership",
        "liderança",
    }
)


def _pick_str(d: dict, *keys: str) -> str | None:
    for key in keys:
        v = d.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _unwrap_markdown_double_bold(text: str) -> str:
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    out = text
    while True:
        nxt = re.sub(r"\*\*([^*]+)\*\*", r"\1", out)
        if nxt == out:
            return out
        out = nxt


def _clean_technology_chip(label: str) -> str:
    x = (label or "").strip()
    x = _unwrap_markdown_double_bold(x)
    for _ in range(5):
        y = x.strip()
        if len(y) >= 2 and y[0] == y[-1] and y[0] in "\"'":
            x = y[1:-1].strip()
            continue
        if len(y) >= 2 and y.startswith("`") and y.endswith("`"):
            x = y[1:-1].strip()
            continue
        break
    return _unwrap_markdown_double_bold(x).strip()


def filter_skills_non_tech_inplace(data: dict) -> None:
    skills = data.get("skills")
    if not isinstance(skills, list):
        return
    data["skills"] = [
        s
        for s in skills
        if isinstance(s, str) and s.strip() and s.strip().lower() not in _NON_TECH_SKILLS
    ]


def _normalize_resume_dict(d: dict) -> dict:
    if "fullName" not in d:
        name = _pick_str(d, "fullName", "name", "full_name", "candidateName")
        if name:
            d["fullName"] = name
    if "headline" not in d and isinstance(d.get("professionalTitle"), str):
        d["headline"] = d["professionalTitle"]
    if "summary" not in d and isinstance(d.get("professionalSummary"), str):
        d["summary"] = d["professionalSummary"]
    if "summary" not in d and isinstance(d.get("description"), str) and d["description"].strip():
        d["summary"] = d["description"].strip()
    if "headline" not in d and isinstance(d.get("title"), str):
        t = d["title"].strip()
        if t and t.lower() not in _GENERIC_DOC_TITLES:
            d["headline"] = t
    if "email" not in d:
        email = _pick_str(d, "email", "emailAddress", "e-mail", "mail")
        if email:
            d["email"] = email
    for key, empty in (
        ("skills", []),
        ("experience", []),
        ("projects", []),
        ("education", []),
        ("links", []),
    ):
        if d.get(key) is None:
            d[key] = empty
    locale = d.get("locale")
    if isinstance(locale, dict):
        locale_language = _pick_str(locale, "language", "locale", "code")
        d["locale"] = locale_language or "pt-BR"
    projects_obj = d.get("projects")
    if isinstance(projects_obj, dict):
        flattened_projects: list[dict] = []
        for value in projects_obj.values():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        flattened_projects.append(item)
            elif isinstance(value, dict):
                flattened_projects.append(value)
        d["projects"] = flattened_projects
    skills = d.get("skills")
    if isinstance(skills, list):
        normalized_skills: list[str] = []
        for s in skills:
            if isinstance(s, str) and s.strip():
                normalized_skills.append(_clean_technology_chip(s))
                continue
            if isinstance(s, dict):
                skill_name = _pick_str(s, "skill", "name", "title", "label")
                if skill_name:
                    normalized_skills.append(skill_name)
        d["skills"] = [s for s in normalized_skills if s.strip().lower() not in _NON_TECH_SKILLS]

    exp = d.get("experience")
    if isinstance(exp, list):
        for e in exp:
            if not isinstance(e, dict):
                continue
            if "company" not in e:
                company = _pick_str(e, "company", "employer", "organization", "org")
                if company:
                    e["company"] = company
            if "title" not in e:
                title = _pick_str(e, "title", "role", "position", "jobTitle")
                if title:
                    e["title"] = title
            if "location" not in e:
                location = _pick_str(e, "location", "city")
                if location:
                    e["location"] = location
            if "start" not in e:
                start = _pick_str(e, "start", "startDate", "from")
                if start:
                    e["start"] = start
            if "end" not in e:
                end = _pick_str(e, "end", "endDate", "to")
                if end:
                    e["end"] = end
            highlights = e.get("highlights")
            if not isinstance(highlights, list):
                summary = _pick_str(e, "summary", "description", "details")
                e["highlights"] = [summary] if summary else []
            else:
                e["highlights"] = [h.strip() for h in highlights if isinstance(h, str) and h.strip()]
            if not isinstance(e.get("company"), str):
                e["company"] = ""
            if not isinstance(e.get("title"), str):
                e["title"] = ""
            if not isinstance(e.get("start"), str):
                e["start"] = ""

    projs = d.get("projects")
    if isinstance(projs, list):
        for p in projs:
            if not isinstance(p, dict):
                continue
            if "name" not in p and isinstance(p.get("full_name"), str):
                p["name"] = p["full_name"]
            if "name" not in p and isinstance(p.get("title"), str) and p["title"].strip():
                p["name"] = p["title"].strip()
            if "name" not in p or not str(p.get("name") or "").strip():
                p["name"] = "Project"
            desc = p.get("description")
            if desc is None:
                p["description"] = ""
            elif isinstance(desc, str) and not desc.strip():
                alt = p.get("summary") or p.get("details")
                p["description"] = alt.strip() if isinstance(alt, str) else ""
            elif not isinstance(desc, str):
                p["description"] = ""

    edu = d.get("education")
    if isinstance(edu, list):
        for e in edu:
            if not isinstance(e, dict):
                continue
            if "institution" not in e:
                inst = _pick_str(e, "institution", "school", "college", "university")
                if inst:
                    e["institution"] = inst
            if "degree" not in e:
                degree = _pick_str(e, "degree", "course", "program", "title")
                if degree:
                    e["degree"] = degree
            if "end" not in e:
                end = _pick_str(e, "end", "endDate", "date", "year")
                if end:
                    e["end"] = end
            if "details" not in e:
                details = _pick_str(e, "details", "description", "notes")
                if details:
                    e["details"] = details
            if "institution" not in e or not str(e.get("institution") or "").strip():
                e["institution"] = "Education"
            if "degree" not in e or not str(e.get("degree") or "").strip():
                e["degree"] = "N/A"
    return d


def _fill_missing_scalars_from_fallback(
    merged: dict,
    fallback: ResumeDocument,
    *,
    refine: bool,
) -> None:
    fb = fallback.model_dump()
    fb.pop("githubUsername", None)
    for key in ("fullName", "headline", "summary"):
        v = merged.get(key)
        if refine:
            if v is None:
                b = fb.get(key)
                merged[key] = b if isinstance(b, str) else ("" if b is None else str(b))
            continue
        if v is None or (isinstance(v, str) and not str(v).strip()):
            b = fb.get(key)
            merged[key] = b if isinstance(b, str) else ("" if b is None else str(b))


def _norm_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _anchor_generate_to_profile(fallback: ResumeDocument, patch: dict) -> dict:
    """Build a tailored resume that cannot fabricate facts.

    The canonical profile is the source of truth for identity/contact and, when it is
    populated, for the *set* of experiences, education, projects, and skills. The LLM is
    only allowed to:
      - author ``headline``/``summary`` prose;
      - rewrite ``highlights`` for an experience whose company/title matches a profile role;
      - rewrite the ``description`` of a project whose name matches a profile project;
      - select/reorder the profile's own skills.
    Anything the model invents with no match in the profile is discarded. When a section is
    empty in the profile (e.g. a name-only profile backed by a PDF), the LLM output for that
    section is passed through so PDF/GitHub-sourced facts are not lost.
    """
    out = fallback.model_dump()
    out.pop("githubUsername", None)

    # A "seed" profile (no name) means we are extracting a profile from a PDF: in that case the
    # LLM output IS the real data and may populate identity/contact. A populated profile means we
    # are tailoring, and identity/contact/structure must come only from the canonical profile.
    is_seed = not str(fallback.fullName or "").strip()

    llm_headline = patch.get("headline") if isinstance(patch.get("headline"), str) else None
    llm_summary = patch.get("summary") if isinstance(patch.get("summary"), str) else None
    if llm_headline and llm_headline.strip():
        out["headline"] = llm_headline.strip()
    if llm_summary and llm_summary.strip():
        out["summary"] = llm_summary.strip()
    locale = patch.get("locale")
    if isinstance(locale, str) and locale.strip():
        out["locale"] = locale.strip()

    if not str(out.get("fullName") or "").strip():
        pv = patch.get("fullName")
        if isinstance(pv, str) and pv.strip():
            out["fullName"] = pv.strip()
    # Contact details are never sourced from a tailoring LLM (it would fabricate them). Only a
    # seed/extraction profile adopts them from the patch (there they come from the real PDF).
    if is_seed:
        for key in ("email", "phone", "location"):
            if not str(out.get(key) or "").strip():
                pv = patch.get(key)
                if isinstance(pv, str) and pv.strip():
                    out[key] = pv.strip()
        if not out.get("links"):
            lp = patch.get("links")
            if isinstance(lp, list):
                out["links"] = [
                    {"label": str(l.get("label") or "").strip(), "url": str(l.get("url") or "").strip()}
                    for l in lp
                    if isinstance(l, dict) and str(l.get("label") or "").strip() and str(l.get("url") or "").strip()
                ]

    # Experience: anchor to profile roles, adopting rewritten highlights only on a match.
    base_exp = out.get("experience") or []
    patch_exp = patch.get("experience") if isinstance(patch.get("experience"), list) else []
    matched_any = False
    if base_exp:
        by_key: dict[str, dict] = {}
        for e in patch_exp:
            if not isinstance(e, dict):
                continue
            ck, tk = _norm_key(e.get("company")), _norm_key(e.get("title"))
            if ck or tk:
                by_key.setdefault(f"{ck}|{tk}", e)
                if ck:
                    by_key.setdefault(ck, e)
        anchored_exp = []
        for base in base_exp:
            ck, tk = _norm_key(base.get("company")), _norm_key(base.get("title"))
            match = by_key.get(f"{ck}|{tk}") or (by_key.get(ck) if ck else None)
            if match and isinstance(match.get("highlights"), list):
                cleaned = [h.strip() for h in match["highlights"] if isinstance(h, str) and h.strip()]
                if cleaned:
                    base = {**base, "highlights": cleaned}
                    matched_any = True
            anchored_exp.append(base)
        out["experience"] = anchored_exp
    else:
        out["experience"] = patch_exp

    # If the profile had real roles but the model matched none of them, it ignored the candidate
    # entirely (a generic template). Its summary/headline prose can't be trusted either — keep the
    # canonical ones instead of fabricated claims.
    if base_exp and not matched_any and not is_seed:
        out["headline"] = fallback.headline
        out["summary"] = fallback.summary

    # Projects: anchor to profile projects, adopting a rewritten description only on a match.
    base_proj = out.get("projects") or []
    patch_proj = patch.get("projects") if isinstance(patch.get("projects"), list) else []
    if base_proj:
        by_name = {}
        for p in patch_proj:
            if isinstance(p, dict) and _norm_key(p.get("name")):
                by_name.setdefault(_norm_key(p.get("name")), p)
        anchored_proj = []
        for base in base_proj:
            match = by_name.get(_norm_key(base.get("name")))
            if match and isinstance(match.get("description"), str) and match["description"].strip():
                base = {**base, "description": match["description"].strip()}
            anchored_proj.append(base)
        out["projects"] = anchored_proj
    else:
        out["projects"] = patch_proj

    # Education: never fabricated. Keep the profile's; only use the LLM's when the profile has none.
    if not (out.get("education") or []):
        pe = patch.get("education")
        if isinstance(pe, list):
            out["education"] = pe

    # Skills: restrict to the profile's real skills (LLM only reorders); pass through if empty.
    base_skills = [s for s in (out.get("skills") or []) if isinstance(s, str) and s.strip()]
    patch_skills = [s for s in (patch.get("skills") or []) if isinstance(s, str) and s.strip()]
    if base_skills:
        lookup = {_norm_key(s): s for s in base_skills}
        ordered: list[str] = []
        for s in patch_skills:
            canon = lookup.get(_norm_key(s))
            if canon and canon not in ordered:
                ordered.append(canon)
        for s in base_skills:
            if s not in ordered:
                ordered.append(s)
        out["skills"] = ordered
    else:
        out["skills"] = patch_skills
    return out


def _merge_llm_patch_into_profile(
    fallback: ResumeDocument,
    patch: dict,
    *,
    refine: bool,
) -> dict:
    out = fallback.model_dump()
    out.pop("githubUsername", None)
    scalar_keys = ("fullName", "headline", "summary", "location", "email", "phone", "locale")
    list_keys = ("experience", "projects", "skills", "education", "links")

    if refine:
        for key in scalar_keys:
            if key in patch:
                out[key] = patch[key]
        for key in list_keys:
            if key in patch and isinstance(patch[key], list):
                out[key] = patch[key]
        return out

    for key in scalar_keys:
        if key not in patch:
            continue
        p = patch[key]
        if key in ("location", "email", "phone"):
            # Preserve canonical personal contact info; only fill when profile is empty.
            if (out.get(key) is None or str(out.get(key)).strip() == "") and isinstance(p, str):
                out[key] = p
            continue
        if key == "locale":
            if isinstance(p, str) and p.strip():
                out[key] = p
            continue
        if isinstance(p, str) and p.strip():
            out[key] = p
    for key in list_keys:
        if key not in patch:
            continue
        val = patch[key]
        if isinstance(val, list):
            if key == "skills":
                merged: list[str] = []
                for s in [*out.get("skills", []), *val]:
                    if isinstance(s, str) and s.strip():
                        ss = s.strip()
                        if ss.lower() in _NON_TECH_SKILLS:
                            continue
                        if ss not in merged:
                            merged.append(ss)
                out[key] = merged
            elif key == "links":
                merged_links: list[dict] = []
                seen: set[str] = set()
                for link in [*out.get("links", []), *val]:
                    if not isinstance(link, dict):
                        continue
                    label = str(link.get("label") or "").strip()
                    url = str(link.get("url") or "").strip()
                    if not label or not url:
                        continue
                    sig = f"{label.lower()}|{url.lower()}"
                    if sig in seen:
                        continue
                    seen.add(sig)
                    merged_links.append({"label": label, "url": url})
                out[key] = merged_links
            else:
                out[key] = val
    return out


def parse_resume_json(
    raw: str,
    fallback: ResumeDocument | None = None,
    *,
    refine: bool = False,
) -> ResumeDocument:
    raw = raw.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if m:
        raw = m.group(1).strip()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    patch = _normalize_resume_dict(_unwrap_resume_dict(data))
    if fallback is not None:
        if refine:
            merged = _merge_llm_patch_into_profile(fallback, patch, refine=True)
        else:
            merged = _anchor_generate_to_profile(fallback, patch)
        _fill_missing_scalars_from_fallback(merged, fallback, refine=refine)
    else:
        merged = patch
        for key in ("fullName", "headline", "summary"):
            merged.setdefault(key, "")
    sanitize_resume_for_display(merged)
    filter_skills_non_tech_inplace(merged)
    return ResumeDocument.model_validate(merged)
