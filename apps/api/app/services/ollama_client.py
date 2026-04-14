import json
import re

import httpx

from app.config import DEFAULT_OLLAMA_MODEL, OLLAMA_BASE_URL
from app.services.html_sanitize import sanitize_resume_for_display
from app.models import ResumeDocument


def _ollama_json_payload(model: str, system: str, user: str) -> dict:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": "json",
    }


def _generate_prompt(system: str, user: str) -> str:
    return (
        "You are a helpful assistant. Follow the system instructions exactly, "
        "then answer the user. Output only valid JSON when asked.\n\n"
        f"### System\n{system}\n\n### User\n{user}"
    )


def _ollama_http_error_message(r: httpx.Response, base: str, model: str) -> str:
    raw = (r.text or "")[:800]
    api_err = ""
    try:
        body = r.json()
        if isinstance(body.get("error"), str):
            api_err = body["error"].strip()
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    if api_err and "not found" in api_err.lower():
        return (
            f"{api_err} Run `ollama pull {model}` to install it, or set OLLAMA_MODEL in .env "
            f"to an exact name from `ollama list` (Ollama returns HTTP {r.status_code} for missing models)."
        )
    hint = (
        f"Ollama HTTP {r.status_code} at {r.request.url!s}. "
        f"Check OLLAMA_BASE_URL ({base}, no /v1 path), `ollama serve`, and that the model exists (`ollama list`)."
    )
    if api_err:
        return f"{api_err} {hint}"
    return f"{hint} Body: {raw or '(empty)'}"


async def chat_json(
    system: str,
    user: str,
    model: str | None = None,
) -> str:
    model = model or DEFAULT_OLLAMA_MODEL
    base = OLLAMA_BASE_URL.rstrip("/")
    chat_url = f"{base}/api/chat"
    gen_url = f"{base}/api/generate"

    async with httpx.AsyncClient(timeout=300.0) as client:
        r = await client.post(chat_url, json=_ollama_json_payload(model, system, user))
        if not r.is_success:
            r = await client.post(
                gen_url,
                json={
                    "model": model,
                    "prompt": _generate_prompt(system, user),
                    "stream": False,
                    "format": "json",
                },
            )
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(_ollama_http_error_message(r, base, model)) from e
        data = r.json()

    if isinstance(data.get("message"), dict):
        return (data.get("message") or {}).get("content", "") or ""
    if "response" in data:
        return (data.get("response") or "").strip()
    return ""


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
                normalized_skills.append(s.strip())
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


def _merge_llm_patch_into_profile(
    fallback: ResumeDocument,
    patch: dict,
    *,
    refine: bool,
) -> dict:
    out = fallback.model_dump()
    out.pop("githubUsername", None)
    scalar_keys = ("fullName", "headline", "summary", "location", "phone", "locale")
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
        if key in ("location", "phone"):
            # Keep canonical personal contact info unless profile is empty.
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
        merged = _merge_llm_patch_into_profile(fallback, patch, refine=refine)
        _fill_missing_scalars_from_fallback(merged, fallback, refine=refine)
    else:
        merged = patch
        for key in ("fullName", "headline", "summary"):
            merged.setdefault(key, "")
    sanitize_resume_for_display(merged)
    filter_skills_non_tech_inplace(merged)
    return ResumeDocument.model_validate(merged)
