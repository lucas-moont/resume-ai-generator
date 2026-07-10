import asyncio
import json
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
# Aliased to their historical private names: main.py's own body (and tests/unit's
# characterization suite, e.g. `from app.main import _quality_issues`) still refer to these by
# the underscore-prefixed names main.py used to define; the new app.domain.* modules expose a
# clean public API instead, so the alias lives here at the one call site that needs it.
from app.domain.keywords import extract_jd_keywords as _extract_jd_keywords, normalize_token as _normalize_token
from app.domain.locale import detect_locale as _detect_locale, resolve_locale as _resolve_locale
from app.domain.prompts_builder import (
    build_generation_user_msg as _build_generation_user_msg,
    build_refine_user_msg as _build_refine_user_msg,
)
from app.domain.quality import quality_issues as _quality_issues
from app.domain.schemas import (
    GenerateRequest,
    GitHubRepoInfo,
    PdfExportRequest,
    ProfileMaster,
    RefineRequest,
    ResumeDocument,
)
from app.services.ollama_client import list_installed_models
from app.prompt_loader import load_generate_system_prompt, load_prompt
from app.services import llm_client
from app.services.extraction_service import extract_profile_from_text
from app.services.github_client import fetch_user_repos
from app.services.llm.resume_json_parser import parse_resume_json
from app.services.merge_projects import merge_github_with_markdown
from app.services.llm_client import llm_backend_label
from app.services.secret_redaction import redact_secrets
from app.services.pdf_export import render_resume_pdf
from app.services.profile_pdf import format_profile_pdf_prompt_block, load_profile_pdf_excerpt
from app.services.projects_loader import (
    load_profile,
    looks_like_placeholder_profile,
    load_project_markdown_files,
)
# _sse aliased to its historical private name (main.py's own body uses it as a bare `_sse(...)`
# call throughout); run_with_heartbeat is new, no historical name to preserve.
from app.services.streaming import sse as _sse, run_with_heartbeat

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


def _resolve_requested_model(model: str | None) -> str | None:
    if model is None:
        return None
    normalized = model.strip()
    return normalized or None


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
    raw = await llm_client.chat_json(system, user_msg, model=model)
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
        try:
            extracted_profile = await extract_profile_from_text(
                pdf_text, model=_resolve_requested_model(body.model)
            )
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
        raw = await llm_client.chat_json(system, user_msg, model=model)
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
                try:
                    extract_task = asyncio.create_task(
                        extract_profile_from_text(pdf_text, model=_resolve_requested_model(body.model))
                    )
                    timed_out = False
                    async for is_timeout, frame in run_with_heartbeat(
                        extract_task,
                        heartbeat_seconds=STREAM_HEARTBEAT_SECONDS,
                        timeout_seconds=STREAM_LLM_TIMEOUT_SECONDS,
                        tick=lambda elapsed: _sse(
                            "stage",
                            {
                                "step": "extracting_profile_pdf",
                                "progress": 25,
                                "message": f"Extracting profile data from PDF... ({elapsed}s)",
                            },
                        ),
                        on_timeout=lambda elapsed: _sse(
                            "error",
                            {
                                "message": (
                                    "Timed out while extracting Profile.pdf "
                                    f"after {STREAM_LLM_TIMEOUT_SECONDS}s."
                                )
                            },
                        ),
                    ):
                        yield frame
                        timed_out = is_timeout
                    if timed_out:
                        return
                    extracted_profile = extract_task.result()
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
            llm_task = asyncio.create_task(llm_client.chat_json(system, user_msg, model=model))
            timed_out = False
            async for is_timeout, frame in run_with_heartbeat(
                llm_task,
                heartbeat_seconds=STREAM_HEARTBEAT_SECONDS,
                timeout_seconds=STREAM_LLM_TIMEOUT_SECONDS,
                tick=lambda elapsed: _sse(
                    "stage",
                    {
                        "step": "calling_ai",
                        "progress": 60,
                        "message": f"Generating tailored resume with {llm_backend_label()}... ({elapsed}s)",
                    },
                ),
                on_timeout=lambda elapsed: _sse(
                    "error",
                    {"message": f"Timed out waiting for LLM response after {STREAM_LLM_TIMEOUT_SECONDS}s."},
                ),
            ):
                yield frame
                timed_out = is_timeout
            if timed_out:
                return
            raw = llm_task.result()
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
    user_msg = _build_refine_user_msg(resume=body.resume, pdf_block=pdf_block, message=body.message)
    try:
        raw = await llm_client.chat_json(system, user_msg, model=model)
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
            user_msg = _build_refine_user_msg(resume=body.resume, pdf_block=pdf_block, message=body.message)
            yield _sse(
                "stage",
                {
                    "step": "calling_ai",
                    "progress": 60,
                    "message": f"Applying refinement with {llm_backend_label()}",
                },
            )
            llm_task = asyncio.create_task(llm_client.chat_json(system, user_msg, model=model))
            timed_out = False
            async for is_timeout, frame in run_with_heartbeat(
                llm_task,
                heartbeat_seconds=STREAM_HEARTBEAT_SECONDS,
                timeout_seconds=STREAM_LLM_TIMEOUT_SECONDS,
                tick=lambda elapsed: _sse(
                    "stage",
                    {
                        "step": "calling_ai",
                        "progress": 60,
                        "message": f"Applying refinement with {llm_backend_label()}... ({elapsed}s)",
                    },
                ),
                on_timeout=lambda elapsed: _sse(
                    "error",
                    {"message": f"Timed out waiting for LLM response after {STREAM_LLM_TIMEOUT_SECONDS}s."},
                ),
            ):
                yield frame
                timed_out = is_timeout
            if timed_out:
                return
            raw = llm_task.result()
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
