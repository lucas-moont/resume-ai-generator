from app.config import AI_DEFAULT_MODEL
from app.services.llm.provider_factory import build_provider
from app.services.llm.provider_resolver import (
    resolve_active_provider,
    resolve_provider_name_for_model,
)


def llm_backend_label() -> str:
    return resolve_active_provider().name


async def chat_json(
    system: str,
    user: str,
    model: str | None = None,
) -> str:
    model_override = (model or "").strip() or AI_DEFAULT_MODEL
    # If the requested model names a specific backend (e.g. a claude-* or gemini-* model picked in
    # the UI selector), route to that provider. Otherwise use the configured AI_PROVIDER.
    inferred = resolve_provider_name_for_model(model_override)
    provider = build_provider(inferred) if inferred else resolve_active_provider()
    return await provider.chat_json(system, user, model_override=model_override)
