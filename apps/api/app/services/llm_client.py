from app import config as config_module
from app.services.llm.provider_factory import build_provider
from app.services.llm.provider_resolver import (
    provider_context_for,
    resolve_active_provider,
    resolve_active_provider_name,
    resolve_provider_name_for_model,
)

_DEFAULT_MODEL_RESOLVERS = {
    "claude": config_module.resolve_default_claude_model,
    "gemini": config_module.resolve_default_gemini_model,
    "ollama": config_module.resolve_default_ollama_model,
}


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


def effective_model_id(model: str | None) -> str | None:
    """The model id a call made with ``model`` actually runs on, for the record.

    A request with no model used to be stored as NULL, so nothing could tell which model wrote a
    resume once the default changed. This resolves it the same way ``chat_json`` does: the
    requested model, else the configured ``AI_DEFAULT_MODEL``, else the active provider's
    default. It is only used when persisting; the call itself keeps receiving ``model``
    unchanged."""
    requested = (model or "").strip() or config_module.get_runtime_config().ai_default_model
    if requested:
        return requested
    resolver = _DEFAULT_MODEL_RESOLVERS.get(resolve_active_provider_name())
    return resolver() if resolver else None
