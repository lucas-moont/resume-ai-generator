import asyncio
import json
import re
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from app.config import (
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_OLLAMA_MODEL,
    LLM_TIMEOUT_SECONDS,
    PROJECTS_DIR,
    PROMPTS_DIR,
    resolve_profile_json_path,
)
from app.services.ollama_client import list_installed_models
from app.models import (
    GenerateRequest,
    GitHubRepoInfo,
    PdfExportRequest,
    ProfileMaster,
    RefineRequest,
    ResumeDocument,
)
from app.prompt_loader import load_generate_system_prompt, load_prompt
from app.services.github_client import fetch_user_repos
from app.services.llm.resume_json_parser import parse_resume_json
from app.services.merge_projects import merge_github_with_markdown
from app.services.llm_client import chat_json, llm_backend_label
from app.services.secret_redaction import redact_secrets
from app.services.pdf_export import render_resume_pdf
from app.services.profile_pdf import format_profile_pdf_prompt_block, load_profile_pdf_excerpt
from app.services.projects_loader import (
    load_profile,
    looks_like_placeholder_profile,
    load_project_markdown_files,
)

app = FastAPI(title="Resume Agent API", version="0.1.0")
STREAM_LLM_TIMEOUT_SECONDS = LLM_TIMEOUT_SECONDS
STREAM_HEARTBEAT_SECONDS = 5

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


_CLAUDE_MODEL_SUGGESTIONS: list[dict[str, str]] = [
    {"value": "claude-opus-4-8", "label": "Claude Opus 4.8"},
    {"value": "claude-sonnet-5", "label": "Claude Sonnet 5"},
    {"value": "claude-haiku-4-5", "label": "Claude Haiku 4.5"},
]

_GEMINI_MODEL_SUGGESTIONS: list[dict[str, str]] = [
    {"value": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
    {"value": "gemini-2.5-flash-lite", "label": "Gemini 2.5 Flash-Lite"},
    {"value": "gemini-3-flash-preview", "label": "Gemini 3 Flash Preview"},
]


def _default_model_for_active_backend() -> str:
    backend = llm_backend_label()
    if backend == "claude":
        return DEFAULT_CLAUDE_MODEL
    if backend == "gemini":
        return DEFAULT_GEMINI_MODEL
    return DEFAULT_OLLAMA_MODEL or DEFAULT_CLAUDE_MODEL


def _ollama_model_label(name: str) -> str:
    if ":cloud" in name:
        return f"{name} (Ollama Cloud)"
    return f"{name} (Ollama, local)"


@app.get("/api/models")
async def list_models():
    ollama_names = await list_installed_models()
    seen: set[str] = set()
    models: list[dict[str, str]] = []
    for item in (*_CLAUDE_MODEL_SUGGESTIONS, *_GEMINI_MODEL_SUGGESTIONS):
        value = item["value"]
        if value in seen:
            continue
        seen.add(value)
        models.append(item)
    for name in ollama_names:
        if name in seen:
            continue
        seen.add(name)
        models.append({"value": name, "label": _ollama_model_label(name)})
    return {
        "default": _default_model_for_active_backend(),
        "models": models,
    }


def _sse(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _resolve_requested_model(model: str | None) -> str | None:
    if model is None:
        return None
    normalized = model.strip()
    return normalized or None


def _normalize_token(s: str) -> str:
    return re.sub(r"[^a-z0-9.+#-]+", "", s.lower())


# Weak bullet openers that signal generic, low-impact writing (checked case-insensitively).
_WEAK_BULLET_OPENERS = (
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

# Broad (not exhaustive) technology vocabulary used to spot job-description keywords.
_TECH_VOCAB = frozenset(
    _normalize_token(t)
    for t in (
        "javascript", "typescript", "python", "java", "kotlin", "swift", "go", "golang", "rust",
        "ruby", "php", "c", "c++", "c#", "scala", "elixir", "dart", "r", "matlab", "bash", "shell",
        "react", "react native", "next.js", "vue", "nuxt", "angular", "svelte", "solid", "astro",
        "redux", "tailwind", "bootstrap", "jquery", "html", "css", "sass", "webpack", "vite",
        "node.js", "node", "express", "nestjs", "fastapi", "flask", "django", "spring", "spring boot",
        ".net", "asp.net", "laravel", "rails", "graphql", "rest", "grpc", "websocket",
        "postgresql", "postgres", "mysql", "mariadb", "sqlite", "mongodb", "redis", "cassandra",
        "dynamodb", "elasticsearch", "kafka", "rabbitmq", "sql", "nosql", "prisma", "sqlalchemy",
        "aws", "azure", "gcp", "google cloud", "lambda", "s3", "ec2", "eks", "ecs", "cloudformation",
        "terraform", "ansible", "docker", "kubernetes", "k8s", "helm", "jenkins", "gitlab",
        "github actions", "ci/cd", "cicd", "linux", "nginx", "serverless",
        "git", "jira", "agile", "scrum", "kanban", "microservices", "tdd", "oauth", "jwt",
        "pandas", "numpy", "pytorch", "tensorflow", "scikit-learn", "spark", "airflow", "dbt",
        "machine learning", "deep learning", "nlp", "llm", "openai", "langchain",
        "playwright", "cypress", "jest", "pytest", "selenium", "storybook", "figma",
    )
)

_JD_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "you", "your", "our", "will", "are", "have", "has", "that",
        "this", "from", "who", "what", "when", "where", "how", "all", "any", "not", "but", "can",
        "team", "work", "role", "job", "experience", "years", "year", "strong", "good", "great",
        "para", "com", "que", "uma", "dos", "das", "por", "como", "seu", "sua", "mais", "nossa",
    }
)

# --- Locale auto-detection (pt-BR vs en) ---------------------------------------------------------
# The app only writes resumes in Portuguese or English, so a dependency-free, deterministic
# heuristic (distinctive function words + Portuguese diacritics) is preferred over a heavier
# language-detection library that would add non-determinism and an offline-unfriendly dependency.
_DEFAULT_LOCALE = "pt-BR"
_SUPPORTED_LOCALES = frozenset({"pt-BR", "en"})
_PT_DIACRITICS = frozenset("ãõáéíóúâêôàçÃÕÁÉÍÓÚÂÊÔÀÇ")
# Highly Portuguese-specific tokens (avoid forms that are also common English words).
_PT_LANG_WORDS = frozenset(
    {
        "de", "da", "do", "das", "dos", "para", "com", "uma", "que", "voce", "você", "não", "nao",
        "experiência", "experiencia", "desenvolvimento", "vaga", "requisitos", "conhecimento",
        "conhecimentos", "trabalho", "equipe", "habilidades", "ferramentas", "responsável",
        "responsavel", "desejável", "desejavel", "atuar", "sólidos", "solidos", "área", "area",
        "empresa", "atividades", "diferencial", "salário", "salario", "benefícios", "beneficios",
    }
)
# Highly English-specific tokens.
_EN_LANG_WORDS = frozenset(
    {
        "the", "and", "with", "for", "you", "your", "our", "are", "have", "will", "role",
        "experience", "development", "requirements", "skills", "work", "team", "ability",
        "knowledge", "strong", "must", "we", "responsibilities", "proficiency", "familiarity",
        "such", "including", "features", "code", "applications", "best", "practices",
    }
)


def _detect_locale(text: str) -> str | None:
    """Detect whether free-form text is Portuguese or English.

    Returns "pt-BR", "en", or None when there is not enough signal to decide.
    """
    if not text or not text.strip():
        return None
    lowered = text.lower()
    tokens = re.findall(r"[a-zà-ÿ]+", lowered)
    if not tokens:
        return None
    pt_hits = sum(1 for t in tokens if t in _PT_LANG_WORDS)
    en_hits = sum(1 for t in tokens if t in _EN_LANG_WORDS)
    # Diacritics are a near-certain Portuguese signal; weight them but do not let them dominate.
    diacritics = sum(1 for ch in text if ch in _PT_DIACRITICS)
    pt_score = pt_hits + min(diacritics, 8) * 0.5
    en_score = float(en_hits)
    if pt_score == en_score:
        return None
    return "pt-BR" if pt_score > en_score else "en"


def _resolve_locale(requested: str | None, job_description: str, profile_locale: str | None) -> str:
    """Resolve the output locale.

    Explicit "pt-BR"/"en" always win. "auto" (or empty) triggers job-description language
    detection, falling back to the profile locale and finally the app default.
    """
    if requested in _SUPPORTED_LOCALES:
        return requested  # explicit manual override
    detected = _detect_locale(job_description)
    if detected:
        return detected
    if profile_locale in _SUPPORTED_LOCALES:
        return profile_locale
    return _DEFAULT_LOCALE


def _extract_jd_keywords(job_description: str) -> list[str]:
    """Extract likely technology/skill keywords from a job description, stack-agnostically.

    Heuristics: known-tech vocabulary, tokens with tech punctuation (Node.js, C#, CI/CD),
    and acronyms/PascalCase identifiers (API, AWS, GraphQL, PostgreSQL).
    """
    raw_tokens = re.findall(r"[A-Za-z][A-Za-z0-9.+#/-]*", job_description)
    counts: dict[str, int] = {}
    order: list[str] = []
    for raw_tok in raw_tokens:
        # Drop sentence punctuation glued to the edges (e.g. "scalability." or "libraries,").
        tok = raw_tok.strip(".,;:/-")
        if not tok:
            continue
        norm = _normalize_token(tok)
        if len(norm) < 2 or norm in _JD_STOPWORDS:
            continue
        # Only treat punctuation as a tech signal when it is INTERNAL (Node.js, CI/CD) or a known
        # trailing form (C++, C#) — never a trailing sentence period.
        has_tech_punct = bool(re.search(r"[A-Za-z0-9][.+#/][A-Za-z0-9]", tok)) or tok.endswith(("++", "#"))
        is_acronym = tok.isupper() and len(tok) >= 2
        is_pascal = tok[0].isupper() and any(c.isupper() for c in tok[1:])
        looks_tech = norm in _TECH_VOCAB or has_tech_punct or is_acronym or is_pascal
        if not looks_tech:
            continue
        if norm not in counts:
            order.append(norm)
        counts[norm] = counts.get(norm, 0) + 1
    index_of = {n: i for i, n in enumerate(order)}
    order.sort(key=lambda n: (-counts[n], index_of[n]))
    return order


def _resume_keyword_blob(resume: ResumeDocument) -> set[str]:
    parts: list[str] = [resume.headline or "", resume.summary or "", *resume.skills]
    for e in resume.experience:
        parts.extend(e.highlights or [])
    for p in resume.projects:
        parts.append(p.description or "")
        parts.append(p.name or "")
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9.+#/]*", " ".join(parts))
    return {_normalize_token(t) for t in tokens if _normalize_token(t)}


def _has_weak_bullets(resume: ResumeDocument) -> bool:
    for e in resume.experience:
        for h in e.highlights or []:
            plain = re.sub(r"<[^>]+>", "", (h or "")).strip().lower()
            if not plain:
                continue
            if any(plain.startswith(op) for op in _WEAK_BULLET_OPENERS):
                return True
    return False


def _short_project_desc(text: str) -> str:
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned:
        return ""
    return cleaned[:220].rstrip()


def _build_project_context_map(md_entries: list[dict], repos: list[GitHubRepoInfo]) -> dict[str, str]:
    out: dict[str, str] = {}
    for e in md_entries:
        fm = e.get("frontmatter", {})
        slug = str(e.get("slug") or "").strip()
        name = str(fm.get("name") or slug).strip()
        body = _short_project_desc(str(e.get("body") or ""))
        if body:
            if slug:
                out[_normalize_token(slug)] = body
            if name:
                out[_normalize_token(name)] = body
            repo_full = str(fm.get("github_repo") or "").strip().lower()
            if repo_full:
                out[_normalize_token(repo_full)] = body
                out[_normalize_token(repo_full.split("/")[-1])] = body
    for r in repos:
        desc = _short_project_desc(r.description or "")
        if not desc:
            continue
        out[_normalize_token(r.name)] = desc
        out[_normalize_token(r.full_name)] = desc
    return out


def _enrich_projects_from_sources(
    resume: ResumeDocument, md_entries: list[dict], repos: list[GitHubRepoInfo]
) -> ResumeDocument:
    if not resume.projects:
        return resume
    context = _build_project_context_map(md_entries, repos)
    if not context:
        return resume
    patched = resume.model_dump()
    projects = patched.get("projects", [])
    for p in projects:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "").strip()
        desc = str(p.get("description") or "").strip()
        needs = len(desc) < 35 or desc.lower() in {"internal metrics dashboard", "sample project"}
        if not needs:
            continue
        candidates = [name, name.replace(" ", "-"), name.replace("-", " "), name.lower()]
        replacement = ""
        for c in candidates:
            key = _normalize_token(c)
            if key in context:
                replacement = context[key]
                break
        if replacement:
            p["description"] = replacement
    return ResumeDocument.model_validate(patched)


def _quality_issues(resume: ResumeDocument, job_description: str) -> list[str]:
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

    if _has_weak_bullets(resume):
        issues.append(
            "Rewrite bullets that start with weak openers (e.g. 'Responsible for', "
            "'Worked on', pronouns) using strong action verbs."
        )

    if len(resume.skills) < 6:
        issues.append("List the relevant technologies the candidate actually has (aim for 8-16).")

    jd_keywords = _extract_jd_keywords(job_description)
    if jd_keywords:
        blob = _resume_keyword_blob(resume)
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


def _build_generation_user_msg(
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


async def _auto_improve_if_needed(
    *,
    resume: ResumeDocument,
    profile: ResumeDocument,
    job_description: str,
    model: str,
) -> ResumeDocument:
    issues = _quality_issues(resume, job_description)
    if not issues:
        return resume
    system = load_prompt("system/refine.md", PROMPTS_DIR)
    user_msg = f"""Current resume JSON:
{resume.model_dump_json(indent=2)}

Quality issues to fix:
- {"\n- ".join(issues)}

Job description:
---
{job_description.strip()}
---

Revise the resume to address issues without inventing facts. Return full JSON only."""
    raw = await chat_json(system, user_msg, model=model)
    # Anchor to the profile (refine=False) so a hallucinated improvement pass cannot
    # reintroduce fabricated identity/structure; only prose/bullets are adopted.
    improved = parse_resume_json(raw, profile, refine=False)
    return improved


@app.get("/api/profile")
async def get_profile():
    try:
        profile = load_profile(resolve_profile_json_path())
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid profile JSON: {e}") from e
    return profile.model_dump()


@app.get("/api/github/repos")
async def github_repos(username: str | None = None):
    try:
        profile = load_profile(resolve_profile_json_path())
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Profile JSON not found — see README (data/profile/resume.json).",
        ) from None
    user = username or profile.githubUsername
    if not user:
        return {"repos": [], "warning": "No githubUsername in profile and no username query"}
    repos, warn = await fetch_user_repos(user)
    return {
        "repos": [r.model_dump() for r in repos],
        "warning": warn,
    }


@app.post("/api/generate", response_model=ResumeDocument)
async def generate(body: GenerateRequest):
    try:
        profile = load_profile(resolve_profile_json_path())
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid profile: {e}") from e
    pdf_text, pdf_path, pdf_err = load_profile_pdf_excerpt()
    if pdf_err and pdf_path is not None:
        raise HTTPException(
            status_code=400,
            detail=f"Profile PDF found at {pdf_path} but text extraction failed: {pdf_err}",
        ) from None
    if looks_like_placeholder_profile(profile):
        if not (pdf_text and pdf_path is not None):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Profile appears to be the example template. Add real data to "
                    "data/profile/resume.json or provide data/profile/Profile.pdf for extraction."
                ),
            ) from None
        extraction_system = """Extract a professional resume JSON from the provided PDF text.
Output JSON only with this schema:
{
  "fullName": string,
  "headline": string,
  "location": string or null,
  "email": string or null,
  "phone": string or null,
  "links": [ { "label": string, "url": string } ],
  "summary": string,
  "experience": [ { "company": string, "title": string, "location": string or null, "start": string, "end": string or null, "highlights": string[] } ],
  "projects": [ { "name": string, "description": string } ],
  "skills": string[],
  "education": [ { "institution": string, "degree": string, "end": string or null, "details": string or null } ],
  "locale": "pt-BR" or "en"
}
Do not invent facts. Use empty arrays/strings only when data is unavailable."""
        extraction_user = f"""Extract from this PDF text:
---
{pdf_text}
---
Return JSON only."""
        try:
            extracted_raw = await chat_json(
                extraction_system,
                extraction_user,
                model=_resolve_requested_model(body.model),
            )
            seed = ResumeDocument(fullName="", headline="", summary="", locale="pt-BR")
            extracted_profile = parse_resume_json(extracted_raw, seed, refine=False)
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"LLM error ({llm_backend_label()}) extracting Profile.pdf: {redact_secrets(str(e))}",
            ) from e
        if not extracted_profile.fullName.strip() or not extracted_profile.summary.strip():
            raise HTTPException(
                status_code=400,
                detail=(
                    "Could not extract enough data from Profile.pdf. "
                    "Please complete data/profile/resume.json with your real details."
                ),
            ) from None
        profile = ProfileMaster.model_validate({**extracted_profile.model_dump(), "githubUsername": None})

    md_entries = load_project_markdown_files(PROJECTS_DIR)
    repos: list[GitHubRepoInfo] = []
    if profile.githubUsername:
        repos, _gh_warn = await fetch_user_repos(profile.githubUsername)

    projects_unified = merge_github_with_markdown(md_entries, repos)

    pdf_block = ""
    if pdf_text and pdf_path is not None:
        pdf_block = format_profile_pdf_prompt_block(pdf_text, pdf_path.name)

    system = load_generate_system_prompt(PROMPTS_DIR)
    model = _resolve_requested_model(body.model)
    locale = _resolve_locale(body.locale, body.job_description, profile.locale)

    user_msg = _build_generation_user_msg(
        job_description=body.job_description,
        profile=profile,
        pdf_block=pdf_block,
        project_notes=projects_unified if md_entries else "",
        locale=locale,
    )

    try:
        raw = await chat_json(system, user_msg, model=model)
        resume = parse_resume_json(raw, profile, refine=False)
        resume = _enrich_projects_from_sources(resume, md_entries, repos)
        resume = await _auto_improve_if_needed(
            resume=resume,
            profile=profile,
            job_description=body.job_description,
            model=model,
        )
        resume = _enrich_projects_from_sources(resume, md_entries, repos)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"LLM returned invalid JSON: {e}") from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error ({llm_backend_label()}): {redact_secrets(str(e))}") from e
    return resume


@app.post("/api/generate/stream")
async def generate_stream(body: GenerateRequest):
    async def event_stream():
        try:
            yield _sse("stage", {"step": "preparing_context", "progress": 10, "message": "Loading profile and PDF"})
            try:
                profile = load_profile(resolve_profile_json_path())
            except FileNotFoundError as e:
                yield _sse("error", {"message": str(e)})
                return
            except Exception as e:
                yield _sse("error", {"message": f"Invalid profile: {e}"})
                return

            pdf_text, pdf_path, pdf_err = load_profile_pdf_excerpt()
            if pdf_err and pdf_path is not None:
                yield _sse(
                    "error",
                    {"message": f"Profile PDF found at {pdf_path} but text extraction failed: {pdf_err}"},
                )
                return

            if looks_like_placeholder_profile(profile):
                if not (pdf_text and pdf_path is not None):
                    yield _sse(
                        "error",
                        {
                            "message": (
                                "Profile appears to be the example template. Add real data to "
                                "data/profile/resume.json or provide data/profile/Profile.pdf for extraction."
                            )
                        },
                    )
                    return
                yield _sse(
                    "stage",
                    {"step": "extracting_profile_pdf", "progress": 25, "message": "Extracting profile data from PDF"},
                )
                extraction_system = """Extract a professional resume JSON from the provided PDF text.
Output JSON only with this schema:
{
  "fullName": string,
  "headline": string,
  "location": string or null,
  "email": string or null,
  "phone": string or null,
  "links": [ { "label": string, "url": string } ],
  "summary": string,
  "experience": [ { "company": string, "title": string, "location": string or null, "start": string, "end": string or null, "highlights": string[] } ],
  "projects": [ { "name": string, "description": string } ],
  "skills": string[],
  "education": [ { "institution": string, "degree": string, "end": string or null, "details": string or null } ],
  "locale": "pt-BR" or "en"
}
Do not invent facts. Use empty arrays/strings only when data is unavailable."""
                extraction_user = f"""Extract from this PDF text:
---
{pdf_text}
---
Return JSON only."""
                try:
                    extract_task = asyncio.create_task(
                        chat_json(
                            extraction_system,
                            extraction_user,
                            model=_resolve_requested_model(body.model),
                        )
                    )
                    elapsed = 0
                    while not extract_task.done():
                        await asyncio.sleep(STREAM_HEARTBEAT_SECONDS)
                        elapsed += STREAM_HEARTBEAT_SECONDS
                        if elapsed >= STREAM_LLM_TIMEOUT_SECONDS:
                            extract_task.cancel()
                            yield _sse(
                                "error",
                                {
                                    "message": (
                                        "Timed out while extracting Profile.pdf "
                                        f"after {STREAM_LLM_TIMEOUT_SECONDS}s."
                                    )
                                },
                            )
                            return
                        yield _sse(
                            "stage",
                            {
                                "step": "extracting_profile_pdf",
                                "progress": 25,
                                "message": f"Extracting profile data from PDF... ({elapsed}s)",
                            },
                        )
                    extracted_raw = await extract_task
                    seed = ResumeDocument(fullName="", headline="", summary="", locale="pt-BR")
                    extracted_profile = parse_resume_json(extracted_raw, seed, refine=False)
                except Exception as e:
                    yield _sse(
                        "error",
                        {"message": f"LLM error ({llm_backend_label()}) extracting Profile.pdf: {e}"},
                    )
                    return
                if not extracted_profile.fullName.strip() or not extracted_profile.summary.strip():
                    yield _sse(
                        "error",
                        {
                            "message": (
                                "Could not extract enough data from Profile.pdf. "
                                "Please complete data/profile/resume.json with your real details."
                            )
                        },
                    )
                    return
                profile = ProfileMaster.model_validate({**extracted_profile.model_dump(), "githubUsername": None})

            yield _sse(
                "stage",
                {"step": "preparing_context", "progress": 35, "message": "Loading projects and GitHub context"},
            )
            md_entries = load_project_markdown_files(PROJECTS_DIR)
            repos: list[GitHubRepoInfo] = []
            if profile.githubUsername:
                repos, _gh_warn = await fetch_user_repos(profile.githubUsername)

            projects_unified = merge_github_with_markdown(md_entries, repos)

            pdf_block = ""
            if pdf_text and pdf_path is not None:
                pdf_block = format_profile_pdf_prompt_block(pdf_text, pdf_path.name)

            system = load_generate_system_prompt(PROMPTS_DIR)
            model = _resolve_requested_model(body.model)
            locale = _resolve_locale(body.locale, body.job_description, profile.locale)

            user_msg = _build_generation_user_msg(
                job_description=body.job_description,
                profile=profile,
                pdf_block=pdf_block,
                project_notes=projects_unified if md_entries else "",
                locale=locale,
            )

            yield _sse(
                "stage",
                {
                    "step": "calling_ai",
                    "progress": 60,
                    "message": f"Generating tailored resume with {llm_backend_label()}",
                },
            )
            llm_task = asyncio.create_task(chat_json(system, user_msg, model=model))
            elapsed = 0
            while not llm_task.done():
                await asyncio.sleep(STREAM_HEARTBEAT_SECONDS)
                elapsed += STREAM_HEARTBEAT_SECONDS
                if elapsed >= STREAM_LLM_TIMEOUT_SECONDS:
                    llm_task.cancel()
                    yield _sse(
                        "error",
                        {
                            "message": (
                                "Timed out waiting for LLM response "
                                f"after {STREAM_LLM_TIMEOUT_SECONDS}s."
                            )
                        },
                    )
                    return
                yield _sse(
                    "stage",
                    {
                        "step": "calling_ai",
                        "progress": 60,
                        "message": (
                            f"Generating tailored resume with {llm_backend_label()}... ({elapsed}s)"
                        ),
                    },
                )
            raw = await llm_task
            yield _sse("stage", {"step": "validating_response", "progress": 85, "message": "Validating AI response"})
            resume = parse_resume_json(raw, profile, refine=False)
            resume = _enrich_projects_from_sources(resume, md_entries, repos)
            issues = _quality_issues(resume, body.job_description)
            if issues:
                yield _sse(
                    "stage",
                    {"step": "validating_response", "progress": 90, "message": "Applying automatic quality pass"},
                )
                resume = await _auto_improve_if_needed(
                    resume=resume,
                    profile=profile,
                    job_description=body.job_description,
                    model=model,
                )
                resume = _enrich_projects_from_sources(resume, md_entries, repos)
            yield _sse("stage", {"step": "finalizing", "progress": 95, "message": "Finalizing resume document"})
            yield _sse("done", {"progress": 100, "resume": resume.model_dump()})
        except json.JSONDecodeError as e:
            yield _sse("error", {"message": f"LLM returned invalid JSON: {e}"})
        except Exception as e:
            yield _sse("error", {"message": f"LLM error ({llm_backend_label()}): {redact_secrets(str(e))}"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/refine", response_model=ResumeDocument)
async def refine(body: RefineRequest):
    pdf_text, pdf_path, pdf_err = load_profile_pdf_excerpt()
    if pdf_err and pdf_path is not None:
        raise HTTPException(
            status_code=400,
            detail=f"Profile PDF found at {pdf_path} but text extraction failed: {pdf_err}",
        ) from None
    pdf_block = ""
    if pdf_text and pdf_path is not None:
        pdf_block = format_profile_pdf_prompt_block(pdf_text, pdf_path.name)

    system = load_prompt("system/refine.md", PROMPTS_DIR)
    model = _resolve_requested_model(body.model)
    user_msg = f"""Current resume JSON:
{body.resume.model_dump_json(indent=2)}

{pdf_block}User instruction:
{body.message.strip()}

Return the full updated resume JSON only."""
    try:
        raw = await chat_json(system, user_msg, model=model)
        resume = parse_resume_json(raw, body.resume, refine=True)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"LLM returned invalid JSON: {e}") from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error ({llm_backend_label()}): {redact_secrets(str(e))}") from e
    return resume


@app.post("/api/refine/stream")
async def refine_stream(body: RefineRequest):
    async def event_stream():
        try:
            yield _sse("stage", {"step": "preparing_context", "progress": 20, "message": "Preparing refinement context"})
            pdf_text, pdf_path, pdf_err = load_profile_pdf_excerpt()
            if pdf_err and pdf_path is not None:
                yield _sse(
                    "error",
                    {"message": f"Profile PDF found at {pdf_path} but text extraction failed: {pdf_err}"},
                )
                return
            pdf_block = ""
            if pdf_text and pdf_path is not None:
                pdf_block = format_profile_pdf_prompt_block(pdf_text, pdf_path.name)

            system = load_prompt("system/refine.md", PROMPTS_DIR)
            model = _resolve_requested_model(body.model)
            user_msg = f"""Current resume JSON:
{body.resume.model_dump_json(indent=2)}

{pdf_block}User instruction:
{body.message.strip()}

Return the full updated resume JSON only."""
            yield _sse(
                "stage",
                {
                    "step": "calling_ai",
                    "progress": 60,
                    "message": f"Applying refinement with {llm_backend_label()}",
                },
            )
            llm_task = asyncio.create_task(chat_json(system, user_msg, model=model))
            elapsed = 0
            while not llm_task.done():
                await asyncio.sleep(STREAM_HEARTBEAT_SECONDS)
                elapsed += STREAM_HEARTBEAT_SECONDS
                if elapsed >= STREAM_LLM_TIMEOUT_SECONDS:
                    llm_task.cancel()
                    yield _sse(
                        "error",
                        {
                            "message": (
                                "Timed out waiting for LLM response "
                                f"after {STREAM_LLM_TIMEOUT_SECONDS}s."
                            )
                        },
                    )
                    return
                yield _sse(
                    "stage",
                    {
                        "step": "calling_ai",
                        "progress": 60,
                        "message": f"Applying refinement with {llm_backend_label()}... ({elapsed}s)",
                    },
                )
            raw = await llm_task
            yield _sse("stage", {"step": "validating_response", "progress": 85, "message": "Validating refinement"})
            resume = parse_resume_json(raw, body.resume, refine=True)
            yield _sse("done", {"progress": 100, "resume": resume.model_dump()})
        except json.JSONDecodeError as e:
            yield _sse("error", {"message": f"LLM returned invalid JSON: {e}"})
        except Exception as e:
            yield _sse("error", {"message": f"LLM error ({llm_backend_label()}): {redact_secrets(str(e))}"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/export/pdf")
async def export_pdf(body: PdfExportRequest):
    try:
        pdf_bytes = await render_resume_pdf(body.resume, body.template)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF failed: {e}") from e
    fname = f"curriculo-{datetime.now().strftime('%Y%m%d-%H%M')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
