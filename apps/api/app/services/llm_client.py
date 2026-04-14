from app.config import GEMINI_API_KEY
from app.services.gemini_client import chat_json_gemini
from app.services.ollama_client import chat_json as chat_json_ollama


def use_gemini() -> bool:
    return bool((GEMINI_API_KEY or "").strip())


def llm_backend_label() -> str:
    return "Gemini" if use_gemini() else "Ollama"


async def chat_json(
    system: str,
    user: str,
    model: str | None = None,
) -> str:
    if use_gemini():
        return await chat_json_gemini(system, user)
    return await chat_json_ollama(system, user, model=model)
