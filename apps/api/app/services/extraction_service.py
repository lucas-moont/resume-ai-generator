"""Profile extraction from PDF text via the LLM -- extracted from app/main.py (B3).

Both /api/generate call sites (the plain endpoint and its streaming counterpart) reach this
when the canonical profile JSON looks like the shipped placeholder and a Profile.pdf is
available: the LLM is asked to read the extracted PDF text and produce a resume-shaped JSON,
which becomes the working profile for that request. Previously this system prompt and the
resulting parse step were duplicated inline at both call sites; this module is now the single
copy.
"""

from app.config import PROMPTS_DIR
from app.domain.schemas import ResumeDocument
from app.prompt_loader import load_extract_profile_system_prompt
from app.services import llm_client
from app.services.llm.resume_json_parser import parse_resume_json


async def extract_profile_from_text(text: str, *, model: str | None = None) -> ResumeDocument:
    system = load_extract_profile_system_prompt(PROMPTS_DIR)
    user = f"""Extract from this PDF text:
---
{text}
---
Return JSON only."""
    raw = await llm_client.chat_json(system, user, model=model)
    seed = ResumeDocument(fullName="", headline="", summary="", locale="pt-BR")
    return parse_resume_json(raw, seed, refine=False)
