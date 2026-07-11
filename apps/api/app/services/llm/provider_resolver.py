from __future__ import annotations

from app import config as config_module
from app.services.llm.provider_factory import build_provider
from app.services.llm.providers.base import LlmProvider, ProviderMode, ProviderName


def _normalize_mode(value: str | None) -> ProviderMode:
    raw = (value or "").strip().lower()
    if not raw:
        return "auto"
    if raw in ("auto", "claude", "gemini", "ollama"):
        return raw
    raise ValueError(
        f"Invalid AI_PROVIDER '{value}'. Expected one of: auto, claude, gemini, ollama."
    )


def resolve_provider_name(
    provider_mode: str | None,
    gemini_api_key: str | None,
    anthropic_api_key: str | None = None,
) -> ProviderName:
    mode = _normalize_mode(provider_mode)
    if mode == "auto":
        # Preference order for auto-detection: Claude, then Gemini, then Ollama (always available
        # locally). A local `ant auth login` sets no env var, so login-only users select Claude
        # explicitly with AI_PROVIDER=claude (or by picking a claude-* model in the UI).
        if (anthropic_api_key or "").strip():
            return "claude"
        if (gemini_api_key or "").strip():
            return "gemini"
        return "ollama"
    return mode


def resolve_provider_name_for_model(model: str | None) -> ProviderName | None:
    """Infer the provider from a model name so the UI model selector can switch backends
    per request (e.g. picking Claude Opus vs Sonnet vs a Gemini model). Returns None when the
    name is not recognizable, so the caller falls back to the configured AI_PROVIDER."""
    name = (model or "").strip().lower()
    if name.startswith("claude"):
        return "claude"
    if name.startswith("gemini"):
        return "gemini"
    return None


def resolve_active_provider() -> LlmProvider:
    runtime = config_module.get_runtime_config()
    provider_name = resolve_provider_name(
        runtime.ai_provider, runtime.gemini_api_key, runtime.anthropic_api_key
    )
    return build_provider(provider_name)
