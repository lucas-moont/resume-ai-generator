"""Unified generate pipeline (profile -> prompt -> LLM -> parse -> quality pass) --
extracted from app/main.py (B4).

``generate_resume_events`` is the ONE function that serves both /api/generate and
/api/generate/stream: it is an async generator yielding ``(event, data)`` tuples where
``event`` is ``"stage"`` (progress) or ``"done"`` (data == {"progress": 100, "resume":
ResumeDocument}). The stream router forwards every event as an SSE frame; the sync router
drains the same generator, discards "stage" events, and returns the resume from the terminal
"done" event. Errors are raised (not yielded) as ``FileNotFoundError`` (profile JSON missing),
``ProfileValidationError`` (any other profile-resolution problem), ``ExtractionError`` (the
Profile.pdf extraction LLM call failed), ``TimeoutError`` (an LLM call exceeded its heartbeat
timeout), or the raw exception from a failed main-generation LLM/JSON-parse call -- each
router translates these into its own transport (HTTPException vs SSE error frame).

As of v2 ticket 01, this function no longer resolves the profile itself: it takes an
already-resolved ``ResolvedProfile`` (see ``app.services.profile_resolution``) from its
caller, which by now has a DB ``Session`` in scope (``routers/generate.py`` for the legacy
sync/stream endpoints, ``chat_service.handle_chat_turn`` for the chat "generate" intent).
This closes the v1 provenance drift: the profile actually used in the LLM prompt is now
guaranteed to be the SAME row ``resolved_profile.profile_version_id`` points at, instead of
each caller re-resolving (and each generate call reading disk directly, independent of
whatever ``profile_versions`` row a caller separately looked up to stamp on the result).

As of v4 ticket B5, ``agreed_improvements`` (default ``None``, additive) lets a caller --
``chat_service._handle_approve_branch``, once a Pending Proposal's items are agreed to -- inject
them into the generation prompt as an APPROVED IMPROVEMENT PLAN block
(``build_generation_user_msg``, spec SS4.3). Omitted, the prompt is byte-identical to the
pre-v4 output (``tests/unit/test_prompts_builder.py``'s characterization test).

Design note on sharing the heartbeat-wrapped LLM calls with the sync endpoint: before B4, the
sync /api/generate awaited chat_json() directly with no explicit timeout wrapper, relying on
the underlying HTTP client's own timeout (LLM_TIMEOUT_SECONDS -- the SAME ceiling used by the
heartbeat timeout below). Sharing one implementation means the sync path now also gets
heartbeat-based cancellation and the "Timed out waiting for LLM response after Ns." message on
a hang, instead of whatever the raw HTTP client's timeout exception looked like. This is not
exercised by the B1 characterization suite (no test hangs a request that long) and is judged a
strict improvement (a clearer message and graceful task cancellation) rather than a
regression -- flagged here per the "document deviations" convention carried from B1-B3.
"""

import asyncio
from collections.abc import AsyncIterator

from app.config import LLM_TIMEOUT_SECONDS, PROJECTS_DIR, PROMPTS_DIR
from app.domain.keywords import normalize_token
from app.domain.locale import resolve_locale
from app.domain.prompts_builder import build_generation_user_msg
from app.domain.quality import quality_issues
from app.domain.schemas import GitHubRepoInfo, ProposalItem, ResumeDocument
from app.prompt_loader import load_generate_system_prompt, load_prompt
from app.services import llm_client, streaming
from app.services.extraction_service import extract_profile_from_text
from app.services.github_client import fetch_user_repos
from app.services.llm.resume_json_parser import parse_resume_json
from app.services.merge_projects import merge_github_with_markdown
from app.services.profile_pdf import format_profile_pdf_prompt_block
from app.services.profile_resolution import (
    ProfileValidationError,
    ResolvedProfile,
    finish_profile_from_extraction,
)
from app.services.projects_loader import load_project_markdown_files
from app.services.streaming import run_with_heartbeat

STREAM_LLM_TIMEOUT_SECONDS = LLM_TIMEOUT_SECONDS


class ExtractionError(Exception):
    """Raised when the LLM call that extracts a profile from Profile.pdf fails.

    Wraps the original exception WITHOUT pre-formatting a message: the sync and stream
    routers format ``.original`` themselves, because they apply different treatment to it
    (the sync path redacts secrets in this specific message, the stream path pre-existingly
    does not -- see B3's report; formatting here once would have made one of the two routers
    double-wrap the message when it applies its own "LLM error (...): ..." prefix on top).
    """

    def __init__(self, original: Exception) -> None:
        super().__init__(str(original))
        self.original = original


def short_project_desc(text: str) -> str:
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned:
        return ""
    return cleaned[:220].rstrip()


def build_project_context_map(md_entries: list[dict], repos: list[GitHubRepoInfo]) -> dict[str, str]:
    out: dict[str, str] = {}
    for e in md_entries:
        fm = e.get("frontmatter", {})
        slug = str(e.get("slug") or "").strip()
        name = str(fm.get("name") or slug).strip()
        body = short_project_desc(str(e.get("body") or ""))
        if body:
            if slug:
                out[normalize_token(slug)] = body
            if name:
                out[normalize_token(name)] = body
            repo_full = str(fm.get("github_repo") or "").strip().lower()
            if repo_full:
                out[normalize_token(repo_full)] = body
                out[normalize_token(repo_full.split("/")[-1])] = body
    for r in repos:
        desc = short_project_desc(r.description or "")
        if not desc:
            continue
        out[normalize_token(r.name)] = desc
        out[normalize_token(r.full_name)] = desc
    return out


def enrich_projects_from_sources(
    resume: ResumeDocument, md_entries: list[dict], repos: list[GitHubRepoInfo]
) -> ResumeDocument:
    if not resume.projects:
        return resume
    context = build_project_context_map(md_entries, repos)
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
            key = normalize_token(c)
            if key in context:
                replacement = context[key]
                break
        if replacement:
            p["description"] = replacement
    return ResumeDocument.model_validate(patched)


async def auto_improve_if_needed(
    *,
    resume: ResumeDocument,
    profile: ResumeDocument,
    job_description: str,
    model: str,
) -> ResumeDocument:
    issues = quality_issues(resume, job_description)
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


async def generate_resume_events(
    *,
    resolved_profile: ResolvedProfile,
    job_description: str,
    model: str | None,
    locale: str | None,
    backend_label: str,
    agreed_improvements: list[ProposalItem] | None = None,
) -> AsyncIterator[tuple[str, dict]]:
    yield "stage", {"step": "preparing_context", "progress": 10, "message": "Loading profile and PDF"}

    profile = resolved_profile.profile
    pdf_text = resolved_profile.pdf_text
    pdf_path = resolved_profile.pdf_path

    if resolved_profile.needs_extraction and not (pdf_text and pdf_path is not None):
        raise ProfileValidationError(
            "Profile appears to be the example template. Add real data to "
            "data/profile/resume.json or provide data/profile/Profile.pdf for extraction."
        )

    if resolved_profile.needs_extraction:
        yield "stage", {
            "step": "extracting_profile_pdf",
            "progress": 25,
            "message": "Extracting profile data from PDF",
        }
        extract_task = asyncio.create_task(extract_profile_from_text(pdf_text, model=model))
        async for is_timeout, data in run_with_heartbeat(
            extract_task,
            heartbeat_seconds=streaming.HEARTBEAT_SECONDS,
            timeout_seconds=STREAM_LLM_TIMEOUT_SECONDS,
            tick=lambda elapsed: {
                "step": "extracting_profile_pdf",
                "progress": 25,
                "message": f"Extracting profile data from PDF... ({elapsed}s)",
            },
            on_timeout=lambda elapsed: {
                "message": f"Timed out while extracting Profile.pdf after {STREAM_LLM_TIMEOUT_SECONDS}s."
            },
        ):
            if is_timeout:
                raise TimeoutError(data["message"])
            yield "stage", data
        try:
            extracted_profile = extract_task.result()
        except Exception as e:
            raise ExtractionError(e) from e
        profile = finish_profile_from_extraction(extracted_profile)

    yield "stage", {
        "step": "preparing_context",
        "progress": 35,
        "message": "Loading projects and GitHub context",
    }
    md_entries = load_project_markdown_files(PROJECTS_DIR)
    repos: list[GitHubRepoInfo] = []
    if profile.githubUsername:
        repos, _gh_warn = await fetch_user_repos(profile.githubUsername)
    projects_unified = merge_github_with_markdown(md_entries, repos)

    pdf_block = ""
    if pdf_text and pdf_path is not None:
        pdf_block = format_profile_pdf_prompt_block(pdf_text, pdf_path.name)

    system = load_generate_system_prompt(PROMPTS_DIR)
    resolved_locale = resolve_locale(locale, job_description, profile.locale)
    user_msg = build_generation_user_msg(
        job_description=job_description,
        profile=profile,
        pdf_block=pdf_block,
        project_notes=projects_unified if md_entries else "",
        locale=resolved_locale,
        agreed_improvements=agreed_improvements,
    )

    yield "stage", {
        "step": "calling_ai",
        "progress": 60,
        "message": f"Generating tailored resume with {backend_label}",
    }
    llm_task = asyncio.create_task(llm_client.chat_json(system, user_msg, model=model))
    async for is_timeout, data in run_with_heartbeat(
        llm_task,
        heartbeat_seconds=streaming.HEARTBEAT_SECONDS,
        timeout_seconds=STREAM_LLM_TIMEOUT_SECONDS,
        tick=lambda elapsed: {
            "step": "calling_ai",
            "progress": 60,
            "message": f"Generating tailored resume with {backend_label}... ({elapsed}s)",
        },
        on_timeout=lambda elapsed: {
            "message": f"Timed out waiting for LLM response after {STREAM_LLM_TIMEOUT_SECONDS}s."
        },
    ):
        if is_timeout:
            raise TimeoutError(data["message"])
        yield "stage", data
    raw = llm_task.result()

    yield "stage", {"step": "validating_response", "progress": 85, "message": "Validating AI response"}
    resume = parse_resume_json(raw, profile, refine=False)
    resume = enrich_projects_from_sources(resume, md_entries, repos)
    issues = quality_issues(resume, job_description)
    if issues:
        yield "stage", {
            "step": "validating_response",
            "progress": 90,
            "message": "Applying automatic quality pass",
        }
        resume = await auto_improve_if_needed(
            resume=resume,
            profile=profile,
            job_description=job_description,
            model=model,
        )
        resume = enrich_projects_from_sources(resume, md_entries, repos)
    yield "stage", {"step": "finalizing", "progress": 95, "message": "Finalizing resume document"}
    yield "done", {"progress": 100, "resume": resume}
