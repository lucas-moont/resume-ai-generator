"""Unified refine pipeline -- extracted from app/main.py (B4).

``refine_resume_events`` follows the same "one generator, two consumers" pattern as
``generation_service.generate_resume_events``: an async generator yielding ``(event, data)``
tuples, drained differently by /api/refine (discards "stage" events, returns the "done"
resume) and /api/refine/stream (forwards every event as an SSE frame). See
generation_service's module docstring for the note on why the sync path now shares the
heartbeat-wrapped LLM call (and its timeout message) with the stream path.
"""

import asyncio
import re
from collections.abc import AsyncIterator

from app.config import LLM_TIMEOUT_SECONDS, PROJECTS_DIR, PROMPTS_DIR
from app.domain.locale import mentions_language_change, normalize_locale
from app.domain.prompts_builder import build_refine_user_msg
from app.domain.schemas import GitHubRepoInfo, ProfileMaster, ResumeDocument
from app.prompt_loader import load_refine_system_prompt
from app.services import llm_client, streaming
from app.services.github_client import fetch_user_repos
from app.services.llm.resume_json_parser import parse_resume_json, try_parse_refine_question
from app.services.merge_projects import merge_github_with_markdown
from app.services.profile_pdf import format_profile_pdf_prompt_block, load_profile_pdf_excerpt
from app.services.profile_resolution import ProfileValidationError
from app.services.projects_loader import load_project_markdown_files
from app.services.streaming import run_with_heartbeat

STREAM_LLM_TIMEOUT_SECONDS = LLM_TIMEOUT_SECONDS

# "repo" is a deliberate whole-word match (not a prefix wildcard): \b on both sides admits it
# as a stand-alone abbreviation and as the start of "repositório"/"repositórios" via the
# explicit alternative below, without letting an unrelated word like "reportagem" match just
# because it happens to start with the same four letters.
_GITHUB_MENTION_RE = re.compile(r"\b(github|repos?|reposit[óo]rios?)\b", re.IGNORECASE)


def _build_project_sources_block(md_entries: list[dict], repos: list[GitHubRepoInfo]) -> str:
    merged = merge_github_with_markdown(md_entries, repos)
    return f"Project notes:\n{merged}"


async def refine_resume_events(
    *,
    resume: ResumeDocument,
    message: str,
    model: str | None,
    backend_label: str,
    profile: ProfileMaster,
) -> AsyncIterator[tuple[str, dict]]:
    yield "stage", {
        "step": "preparing_context",
        "progress": 20,
        "message": "Preparing refinement context",
    }
    pdf_text, pdf_path, pdf_err = load_profile_pdf_excerpt()
    if pdf_err and pdf_path is not None:
        raise ProfileValidationError(
            f"Profile PDF found at {pdf_path} but text extraction failed: {pdf_err}"
        )
    pdf_block = ""
    if pdf_text and pdf_path is not None:
        pdf_block = format_profile_pdf_prompt_block(pdf_text, pdf_path.name)

    md_entries = load_project_markdown_files(PROJECTS_DIR)
    mentions_github = bool(_GITHUB_MENTION_RE.search(message))
    if mentions_github and profile.githubUsername:
        repos, _gh_warn = await fetch_user_repos(profile.githubUsername)
        project_sources_block = _build_project_sources_block(md_entries, repos)
    elif mentions_github:
        parts = []
        if md_entries:
            parts.append(_build_project_sources_block(md_entries, []))
        parts.append("(GitHub username not configured in profile — cannot fetch live repos)")
        project_sources_block = "\n\n".join(parts)
    elif md_entries:
        project_sources_block = _build_project_sources_block(md_entries, [])
    else:
        project_sources_block = ""

    # v6: a refine changes the document's language ONLY when the instruction was about
    # language. Otherwise the current language is pinned, both in the prompt (so the model is
    # told) and in the parse below (so it holds even if the model ignores being told).
    language_requested = mentions_language_change(message)
    pinned_locale = None if language_requested else (normalize_locale(resume.locale) or resume.locale)

    system = load_refine_system_prompt(PROMPTS_DIR)
    user_msg = build_refine_user_msg(
        resume=resume,
        pdf_block=pdf_block,
        message=message,
        project_sources_block=project_sources_block,
        pinned_locale=pinned_locale,
    )

    yield "stage", {
        "step": "calling_ai",
        "progress": 60,
        "message": f"Applying refinement with {backend_label}",
    }
    llm_task = asyncio.create_task(llm_client.chat_json(system, user_msg, model=model))
    async for is_timeout, data in run_with_heartbeat(
        llm_task,
        heartbeat_seconds=streaming.HEARTBEAT_SECONDS,
        timeout_seconds=STREAM_LLM_TIMEOUT_SECONDS,
        tick=lambda elapsed: {
            "step": "calling_ai",
            "progress": 60,
            "message": f"Applying refinement with {backend_label}... ({elapsed}s)",
        },
        on_timeout=lambda elapsed: {
            "message": f"Timed out waiting for LLM response after {STREAM_LLM_TIMEOUT_SECONDS}s."
        },
    ):
        if is_timeout:
            raise TimeoutError(data["message"])
        yield "stage", data
    raw = llm_task.result()

    yield "stage", {"step": "validating_response", "progress": 85, "message": "Validating refinement"}
    question = try_parse_refine_question(raw)
    if question:
        yield "done", {"progress": 100, "resume": None, "question": question}
        return
    refined = parse_resume_json(raw, resume, refine=True, expected_locale=pinned_locale)
    yield "done", {"progress": 100, "resume": refined, "question": None}
