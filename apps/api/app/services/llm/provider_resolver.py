from __future__ import annotations

from app import config as config_module
from app.services.llm.provider_factory import build_provider
from app.services.llm.providers.base import LlmProvider, ProviderContext, ProviderMode, ProviderName


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


def provider_context_for(mode: ProviderName) -> ProviderContext:
    """Assemble the ``ProviderContext`` a provider adapter is constructed with -- the one place
    that reads `app.config` module-qualified (call-time, per v3 ticket 01) so the adapters
    themselves never need to (v3 ticket 02)."""
    runtime = config_module.get_runtime_config()
    return ProviderContext(
        mode=mode,
        anthropic_api_key=runtime.anthropic_api_key,
        default_claude_model=runtime.default_claude_model,
        claude_max_output_tokens=config_module.CLAUDE_MAX_OUTPUT_TOKENS,
        claude_thinking=config_module.CLAUDE_THINKING,
        gemini_api_key=runtime.gemini_api_key,
        default_gemini_model=runtime.default_gemini_model,
        gemini_max_output_tokens=config_module.GEMINI_MAX_OUTPUT_TOKENS,
        ollama_base_url=config_module.OLLAMA_BASE_URL,
        default_ollama_model=runtime.default_ollama_model,
        ollama_num_ctx=config_module.OLLAMA_NUM_CTX,
        ollama_num_predict=config_module.OLLAMA_NUM_PREDICT,
        llm_temperature=config_module.LLM_TEMPERATURE,
        llm_timeout_seconds=config_module.LLM_TIMEOUT_SECONDS,
    )


def resolve_active_provider() -> LlmProvider:
    runtime = config_module.get_runtime_config()
    provider_name = resolve_provider_name(
        runtime.ai_provider, runtime.gemini_api_key, runtime.anthropic_api_key
    )
    return build_provider(provider_name, provider_context_for(provider_name))
