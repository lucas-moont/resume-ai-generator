"""Unified refine pipeline -- extracted from app/main.py (B4).

``refine_resume_events`` follows the same "one generator, two consumers" pattern as
``generation_service.generate_resume_events``: an async generator yielding ``(event, data)``
tuples, drained differently by /api/refine (discards "stage" events, returns the "done"
resume) and /api/refine/stream (forwards every event as an SSE frame). See
generation_service's module docstring for the note on why the sync path now shares the
heartbeat-wrapped LLM call (and its timeout message) with the stream path.
"""

import asyncio
from collections.abc import AsyncIterator

from app.config import LLM_TIMEOUT_SECONDS, PROMPTS_DIR
from app.domain.prompts_builder import build_refine_user_msg
from app.domain.schemas import ResumeDocument
from app.prompt_loader import load_prompt
from app.services import llm_client, streaming
from app.services.llm.resume_json_parser import parse_resume_json
from app.services.profile_pdf import format_profile_pdf_prompt_block, load_profile_pdf_excerpt
from app.services.profile_resolution import ProfileValidationError
from app.services.streaming import run_with_heartbeat

STREAM_LLM_TIMEOUT_SECONDS = LLM_TIMEOUT_SECONDS


async def refine_resume_events(
    *,
    resume: ResumeDocument,
    message: str,
    model: str | None,
    backend_label: str,
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

    system = load_prompt("system/refine.md", PROMPTS_DIR)
    user_msg = build_refine_user_msg(resume=resume, pdf_block=pdf_block, message=message)

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
    refined = parse_resume_json(raw, resume, refine=True)
    yield "done", {"progress": 100, "resume": refined}
