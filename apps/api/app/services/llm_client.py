from app import config as config_module
from app.services.llm.provider_factory import build_provider
from app.services.llm.provider_resolver import (
    provider_context_for,
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
    model_override = (model or "").strip() or config_module.get_runtime_config().ai_default_model
    # If the requested model names a specific backend (e.g. a claude-* or gemini-* model picked in
    # the UI selector), route to that provider. Otherwise use the configured AI_PROVIDER.
    inferred = resolve_provider_name_for_model(model_override)
    provider = (
        build_provider(inferred, provider_context_for(inferred))
        if inferred
        else resolve_active_provider()
    )
    return await provider.chat_json(system, user, model_override=model_override)
