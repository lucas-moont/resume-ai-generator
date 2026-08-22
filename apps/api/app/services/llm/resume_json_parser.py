from __future__ import annotations

import json
import re

from app.domain.entity_identity import (
    build_skill_lookup,
    entity_key,
    match_education_entries,
    match_experience_entries,
    skill_token,
)
from app.domain.schemas import ProposalItem
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


def _agreed_skills_text(agreed_improvements: list[ProposalItem] | None) -> str:
    """Normalized (``skill_token``-style: lowercased, ``.+#-``-preserving, everything else
    stripped) blob of every approved item's ``proposed`` text for ``section == "skills"``.

    A patch skill outside the profile is admitted only when its own ``skill_token`` is a
    substring of this blob -- the user approved that name literally, in the Improvement
    Proposal they agreed to (v4 ticket QA-04); anything the model pastes in beyond that is
    still a fabrication and stays discarded.
    """
    if not agreed_improvements:
        return ""
    texts = [
        item.proposed
        for item in agreed_improvements
        if getattr(item, "section", None) == "skills" and isinstance(getattr(item, "proposed", None), str)
    ]
    return skill_token(" ".join(texts))


# Absolute floor for the Relevance Filter's skill subtraction: however aggressively the approved
# plan prunes, a resume that reaches the reader with fewer than this many skills is worse than one
# carrying some noise (and would immediately trip quality.py's own "list the technologies" gate).
# When honoring every approved drop would land below it, NO skill drop is applied at all -- an
# all-or-nothing fallback, deliberately chosen over a partial one because "which of the approved
# drops did we silently ignore?" is not a question the user can answer from the rendered resume.
MIN_SKILLS_AFTER_DROPS = 4


def _dropped_targets(
    agreed_improvements: list[ProposalItem] | None,
    *,
    section: str,
    normalizer,
) -> set[str]:
    """Normalized identity keys of everything an approved ``op == "drop"`` item removes from
    ``section`` (v6, Relevance Filter).

    Only an item's ``targets`` are read -- never its prose. Matching downstream is exact
    equality on ``normalizer`` output, so "Analytics" is never collateral damage from a drop
    aimed at "Google Analytics" (a substring blob, as ``_agreed_skills_text`` uses for the
    much safer *admit* direction, would have removed both)."""
    if not agreed_improvements:
        return set()
    keys: set[str] = set()
    for item in agreed_improvements:
        if getattr(item, "section", None) != section or getattr(item, "op", None) != "drop":
            continue
        for target in getattr(item, "targets", None) or []:
            key = normalizer(target)
            if key:
                keys.add(key)
    return keys


def _anchor_generate_to_profile(
    fallback: ResumeDocument,
    patch: dict,
    *,
    agreed_improvements: list[ProposalItem] | None = None,
    expected_locale: str | None = None,
) -> dict:
    """Build a tailored resume that cannot fabricate facts.

    The canonical profile is the source of truth for identity/contact and, when it is
    populated, for the *set* of experiences, education, projects, and skills. The LLM is
    only allowed to:
      - author ``headline``/``summary`` prose;
      - rewrite ``highlights``/``title`` for an experience matched to a profile role by
        company + start date (language-independent, so a translated title, e.g. pt-BR, is
        adopted while company/dates always stay anchored to the profile);
      - rewrite the ``description`` of a project whose name matches a profile project;
      - rewrite ``degree``/``details`` for an education entry matched to a profile entry by
        institution;
      - select/reorder the profile's own skills.
    Anything the model invents with no match in the profile is discarded. When a section is
    empty in the profile (e.g. a name-only profile backed by a PDF), the LLM output for that
    section is passed through so PDF/GitHub-sourced facts are not lost.

    ``agreed_improvements`` (v4 ticket QA-04, default ``None``/additive) relaxes exactly two
    of the above restrictions, and ONLY when present -- with it omitted this function stays
    byte-identical to the pre-QA-04 behavior:
      - a patch skill outside the profile is admitted when the user approved an Improvement
        Proposal item literally naming it (``_agreed_skills_text``);
      - the profile's projects are reordered to the patch's order (instead of the profile's
        own order) when the user approved a "projects" item -- the *set* never changes, only
        the order and, as before, the description of a matched project.
    Both exist because the anchor previously discarded these two categories unconditionally,
    even when the user had just explicitly approved them in the Proposal Turn (Bug 2 of the
    v4 QA live pass) -- the fix is scoped to what was actually agreed to, never a blanket
    relaxation.

    v6 (Relevance Filter) adds the mirror-image relaxation, for the same reason and with the
    same scoping. Everything above describes an anchor that cannot let the LLM ADD -- but it
    equally could not let it REMOVE: the skill tail pass re-appended every profile skill the
    model left out, and the project loop iterated the profile's own set, so a tailored resume
    always carried the candidate's whole inventory no matter how little of it the job asked
    for. "Never invent" and "never omit" had been implemented as one rule; they are now two.
    An approved ``op == "drop"`` item (and ONLY an approved one -- with no plan this function
    stays no-drop, exactly as before) prunes its ``targets`` from:
      - ``skills``, unless honoring every drop would leave fewer than
        ``MIN_SKILLS_AFTER_DROPS`` (then none is applied);
      - ``projects``, with no floor -- a resume with no Projects section is a valid outcome.
    Experience and education are never pruned here, at any approval: an omitted employer or
    degree is a timeline gap, so an off-topic role is compressed to one bullet by the LLM
    instead (``op == "compress"``, instruction-only -- this function already adopts whatever
    non-empty highlight list a matched role comes back with).
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
    # Locale: the server's resolved value is the authority when it has one (v6), exactly like
    # company and dates above. Before v6 the LLM's own claim was adopted unconditionally, so a
    # model that decided to answer in the wrong language also got to relabel the document as
    # that language -- leaving nothing downstream able to tell the mistake from a choice.
    if expected_locale:
        out["locale"] = expected_locale
    else:
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

    # Experience: anchor to profile roles, adopting the rewritten (possibly translated) title
    # and highlights only on a match. Matching is done by normalized company + start date --
    # NOT title -- for two reasons: (1) the LLM legitimately translates the title (e.g. pt-BR),
    # so a title-based key would never match a translated role; (2) the profile can have two
    # roles at the same company (e.g. "Savvi": "Full Stack Developer" and, earlier, "Development
    # Intern"). Company + start date is language-independent and unique, so it tells the two
    # roles apart; a title-based (or company-only) key would collapse both onto the same patch
    # entry and duplicate its highlights across both roles. Each patch entry is "claimed" (used)
    # at most once so that can never happen even in the date-mismatch fallback pass below.
    base_exp = out.get("experience") or []
    patch_exp = patch.get("experience") if isinstance(patch.get("experience"), list) else []
    matched_any = False
    if base_exp:
        # Identity match is now app.domain.entity_identity.match_experience_entries: (company,
        # start) primary key, company-only fallback, each candidate claimed at most once. See
        # that module for the full rationale (same two-pass algorithm, extracted verbatim).
        matched_for = match_experience_entries(base_exp, patch_exp)

        anchored_exp = []
        for i, base in enumerate(base_exp):
            match = matched_for[i]
            if match is not None:
                new_role = dict(base)
                # Adopt the LLM's (possibly translated) title, but company/start/end/location
                # always stay the profile's -- only wording, never the anchor, comes from the LLM.
                llm_title = match.get("title")
                if isinstance(llm_title, str) and llm_title.strip():
                    new_role["title"] = llm_title.strip()
                highlights = match.get("highlights")
                if isinstance(highlights, list):
                    cleaned = [h.strip() for h in highlights if isinstance(h, str) and h.strip()]
                    if cleaned:
                        new_role["highlights"] = cleaned
                        matched_any = True
                base = new_role
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

    # Projects: the LLM SELECTS from the profile's projects; it can never add one.
    #
    # Until v6 the anchor iterated the profile's own list and appended every project the model
    # left out, so a resume always carried the candidate's entire project inventory however
    # little of it spoke to the job -- "at most 4, only the relevant ones" in the prompt was
    # simply overruled downstream. Projects are the showcase section: shipping five, three of
    # them study exercises, buries the two that argue for the role.
    #
    # Selection is now honored, and the anti-fabrication guarantee is unchanged -- a project not
    # in the profile is still discarded, matched by ``entity_key``, and only the DESCRIPTION of a
    # matched project may be rewritten. Omitting a real project is curation, not a lie; inventing
    # one is. This also collapses what used to be two branches (with/without an approved
    # "projects" item), since reordering is just a special case of selecting everything.
    #
    # The floor: if the model matched NOTHING in the profile, that is not curation, it is the
    # model ignoring the candidate (the same signal the experience block treats as a generic
    # template above) -- so the profile's own list is kept intact rather than emptied.
    base_proj = out.get("projects") or []
    patch_proj = patch.get("projects") if isinstance(patch.get("projects"), list) else []
    # An approved "projects" drop (v6) prunes the *set* before either branch runs -- the only
    # case where the anchor lets the profile's project set shrink. No floor here (unlike skills):
    # a resume with no Projects section at all is a legitimate outcome when none of the
    # candidate's projects speak to the job, and the templates render the section as empty.
    #
    # ``profile_had_projects`` is captured BEFORE pruning on purpose: the `else` branch below is
    # the PDF/seed passthrough (profile genuinely has no projects, so the LLM's list is the only
    # source there is). Letting a drop that empties the set fall into it would turn the anchor's
    # anti-fabrication guarantee inside out -- every real project removed, and an invented one
    # the model happened to emit waved straight through in their place.
    profile_had_projects = bool(base_proj)
    dropped_proj = _dropped_targets(agreed_improvements, section="projects", normalizer=entity_key)
    if dropped_proj:
        base_proj = [b for b in base_proj if entity_key(b.get("name")) not in dropped_proj]
        patch_proj = [
            p
            for p in patch_proj
            if not isinstance(p, dict) or entity_key(p.get("name")) not in dropped_proj
        ]
    if not base_proj and profile_had_projects:
        # Every profile project was dropped by the approved plan: the resume ships without a
        # Projects section, and the patch's own list is discarded rather than promoted.
        out["projects"] = []
    elif base_proj:
        base_by_key: dict[str, dict] = {}
        for b in base_proj:
            base_by_key.setdefault(entity_key(b.get("name")), b)
        selected_proj: list[dict] = []
        used_keys: set[str] = set()
        for p in patch_proj:
            if not isinstance(p, dict):
                continue
            key = entity_key(p.get("name"))
            base = base_by_key.get(key)
            if not key or base is None or key in used_keys:
                continue  # invented, unnamed, or already taken -- never promoted
            merged = dict(base)
            desc = p.get("description")
            if isinstance(desc, str) and desc.strip():
                merged["description"] = desc.strip()
            selected_proj.append(merged)
            used_keys.add(key)
        # No match at all means the model ignored the profile, not that it chose nothing.
        out["projects"] = selected_proj if selected_proj else base_proj
    else:
        out["projects"] = patch_proj

    # Education: never fabricated. The *set* of degrees always comes from the profile; only the
    # LLM's when the profile has none at all (PDF/seed passthrough). When the profile does have
    # education, match each entry to a patch entry by normalized institution (consuming each
    # patch entry at most once, same rationale as experience) so a translated degree/details can
    # be adopted without ever inventing one for an institution the LLM didn't mention.
    base_edu = out.get("education") or []
    if base_edu:
        patch_edu = patch.get("education") if isinstance(patch.get("education"), list) else []
        matched_edu = match_education_entries(base_edu, patch_edu)
        anchored_edu = []
        for i, base in enumerate(base_edu):
            match = matched_edu[i]
            if match is not None:
                new_edu = dict(base)
                llm_degree = match.get("degree")
                if isinstance(llm_degree, str) and llm_degree.strip():
                    new_edu["degree"] = llm_degree.strip()
                llm_details = match.get("details")
                if isinstance(llm_details, str) and llm_details.strip():
                    new_edu["details"] = llm_details.strip()
                base = new_edu
            anchored_edu.append(base)
        out["education"] = anchored_edu
    else:
        pe = patch.get("education")
        if isinstance(pe, list):
            out["education"] = pe

    # Skills: restrict to the profile's real skills (LLM only reorders); pass through if empty.
    # With an agreed "skills" item, ALSO admit a patch skill outside the profile when its own
    # token is literally named in that item's approved text (QA-04) -- a skill the user never
    # approved (anywhere in the plan) is still a fabrication and stays discarded.
    base_skills = [s for s in (out.get("skills") or []) if isinstance(s, str) and s.strip()]
    patch_skills = [s for s in (patch.get("skills") or []) if isinstance(s, str) and s.strip()]
    if base_skills:
        # Skills are matched by app.domain.entity_identity.skill_token, NOT entity_key --
        # skill_token preserves ".+#-" (e.g. "C++" != "C"), a deliberate distinction from the
        # entity-name matching above (see that module's docstring).
        lookup = build_skill_lookup(base_skills)
        agreed_skills_text = _agreed_skills_text(agreed_improvements)
        dropped = _dropped_targets(agreed_improvements, section="skills", normalizer=skill_token)
        # Guard the floor BEFORE pruning anything, so the decision is all-or-nothing (see
        # MIN_SKILLS_AFTER_DROPS): count what would survive, and abandon the whole drop set if
        # that leaves the resume too thin.
        if dropped:
            surviving = [s for s in base_skills if skill_token(s) not in dropped]
            if len(surviving) < MIN_SKILLS_AFTER_DROPS:
                dropped = set()
        ordered: list[str] = []
        admitted_tokens: set[str] = set()
        for s in patch_skills:
            tok = skill_token(s)
            if tok in dropped:
                continue
            canon = lookup.get(tok)
            if canon:
                if canon not in ordered:
                    ordered.append(canon)
                continue
            if tok and agreed_skills_text and tok in agreed_skills_text and tok not in admitted_tokens:
                cleaned = s.strip()
                if cleaned:
                    ordered.append(cleaned)
                    admitted_tokens.add(tok)
        # The tail pass is what makes the anchor no-drop by default: every profile skill the
        # model left out is appended back. An approved drop is the ONE thing that exempts a
        # skill from it -- without this filter the user's approved subtraction was undone here,
        # silently, on every generation.
        for s in base_skills:
            if skill_token(s) in dropped:
                continue
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
    expected_locale: str | None = None,
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
        # A refine may legitimately change the document's language -- but only when the user
        # ASKED. ``expected_locale`` is how the caller says "this instruction was not about
        # language, so keep the one the document already had" (refine_service decides, since it
        # is the only layer holding the user's message). 13 of the 14 locale drifts measured in
        # the local DB happened here: the model quietly answered in English and relabeled the
        # document to match, off the back of an instruction that never mentioned language.
        if expected_locale:
            out["locale"] = expected_locale
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
    agreed_improvements: list[ProposalItem] | None = None,
    expected_locale: str | None = None,
) -> ResumeDocument:
    """``expected_locale`` (v6, optional/additive): the locale the CALLER has authority over --
    the value resolved from the job description for a generation, or the document's current
    language for a refine that was not about language. Supplied, it overrides whatever the LLM
    claimed; omitted, behavior is byte-identical to pre-v6."""
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
            merged = _merge_llm_patch_into_profile(
                fallback, patch, refine=True, expected_locale=expected_locale
            )
        else:
            merged = _anchor_generate_to_profile(
                fallback,
                patch,
                agreed_improvements=agreed_improvements,
                expected_locale=expected_locale,
            )
        _fill_missing_scalars_from_fallback(merged, fallback, refine=refine)
    else:
        merged = patch
        for key in ("fullName", "headline", "summary"):
            merged.setdefault(key, "")
    sanitize_resume_for_display(merged)
    filter_skills_non_tech_inplace(merged)
    return ResumeDocument.model_validate(merged)


def try_parse_refine_question(raw: str) -> str | None:
    """Detect the refine "question" shape (``{"type": "question", "reply": "..."}"``) without
    ever raising: any malformed/unexpected input just means "not a question" for the caller,
    which then falls through to the normal ``parse_resume_json`` path."""
    raw = raw.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if m:
        raw = m.group(1).strip()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("type") != "question":
        return None
    reply = data.get("reply")
    if isinstance(reply, str) and reply.strip():
        return reply.strip()
    return None
