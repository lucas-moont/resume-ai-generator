"""Business logic behind /api/settings/providers and /api/settings/keys (v3 ticket 03).

Kept out of the router (app/routers/settings.py stays a thin HTTP-shape adapter) so the actual
decisions -- how a provider's `available`/`auth`/`models` are assembled, which app_settings key
a PUT writes to -- live in one deep, directly-testable module.
"""

from __future__ import annotations

from app import config as config_module
from app.config import RuntimeConfig
from app.domain.schemas import DEFAULT_TEMPLATE
from app.services import model_catalog
from app.services.llm.provider_factory import build_provider
from app.services.llm.provider_resolver import provider_context_for
from app.services.llm.providers.base import ProviderName
from app.services.secret_store import delete_secret, secret_source, store_secret

# The three keys PUT /api/settings/keys can manage (docs/v3-agnostic-settings.md Backend-2).
MANAGED_SECRET_NAMES: tuple[str, ...] = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GITHUB_TOKEN")

_PROVIDER_NAMES: tuple[ProviderName, ...] = ("claude", "gemini", "ollama")


async def _provider_entry(name: ProviderName, runtime: RuntimeConfig) -> dict:
    provider = build_provider(name, provider_context_for(name))
    if name == "claude":
        models = await model_catalog.claude_models(runtime.anthropic_api_key)
        default_model = runtime.default_claude_model
        available = provider.is_available
    elif name == "gemini":
        models = await model_catalog.gemini_models(runtime.gemini_api_key)
        default_model = runtime.default_gemini_model
        available = provider.is_available
    else:
        installed = await model_catalog.list_installed_models()
        models = [{"value": n, "label": model_catalog.ollama_model_label(n)} for n in installed]
        default_model = runtime.default_ollama_model
        # v3 ticket 03's own decision (flagged open by ticket 02): OllamaProvider.is_available
        # is a sync, no-I/O check that is always True -- a real reachability probe here gives
        # the UI a genuine "is the local server actually up" signal instead.
        available = await model_catalog.ollama_reachable()
    env_var = config_module.default_model_env_var(name)
    return {
        "name": name,
        "available": available,
        "auth": provider.auth_mode,
        "defaultModel": default_model,
        # v3 ticket 11 (additive): a PUT changing this provider's default is a silent no-op
        # while its env var is set (config.py's env-wins precedence) -- surfaced here instead
        # of the UI pretending the change took effect.
        "defaultModelLockedByEnv": config_module.is_env_locked(env_var),
        "defaultModelEnvVar": env_var,
        "models": models,
    }


async def get_providers_settings() -> dict:
    runtime = config_module.get_runtime_config()
    providers = [await _provider_entry(name, runtime) for name in _PROVIDER_NAMES]
    return {
        "active": runtime.ai_provider,
        # v3 ticket 11 (additive): same "env pins it, PUT is a no-op" signal as
        # defaultModelLockedByEnv above, for the active provider itself.
        "activeLockedByEnv": config_module.is_env_locked(config_module.AI_PROVIDER_ENV_VAR),
        "activeEnvVar": config_module.AI_PROVIDER_ENV_VAR,
        "providers": providers,
    }


def update_providers_settings(provider: str, default_model: str | None) -> None:
    """PUT /api/settings/providers. Always sets the active provider (`ai_provider`); an
    optional `defaultModel` updates that SPECIFIC provider's own default
    (`default_{provider}_model`, ticket 01's key names) so GET's per-provider `defaultModel`
    field reflects it -- except when switching to `auto`, where there is no single concrete
    provider to attach a default to, so it instead updates `ai_default_model`, the generic
    per-call override `llm_client.chat_json` falls back to when a request specifies no model
    (this is a v3 ticket 03 design decision: ticket 01 defined both keys but left how a
    settings write should target them up to this ticket).
    """
    config_module.set_app_setting("ai_provider", provider)
    trimmed = (default_model or "").strip()
    if not trimmed:
        return
    key = "ai_default_model" if provider == "auto" else f"default_{provider}_model"
    config_module.set_app_setting(key, trimmed)


# The app_settings key holding the globally-preferred resume Template.
RESUME_TEMPLATE_SETTING_KEY = "resume_template"


def get_resume_template() -> str:
    """The Template a server-rendered PDF should use (v7 ticket 10, One-click Resume).

    CONTEXT.md calls the Template "a global sticky user preference (like theme)", and until v7
    every render was started by the browser, which sent its own choice in the request body
    (``PdfExportRequest.template``). The One-click Resume has no browser in the loop: the
    server renders the PDF itself, so it needs the preference server-side. This reads it from
    the same ``app_settings`` table every other preference lives in, and falls back to
    ``DEFAULT_TEMPLATE`` while nothing has written it -- which is the honest state today, since
    the web still keeps its pick in ``localStorage``. Whatever is stored is still folded onto
    the manifest by ``pdf_export._safe_template``, so a stale/unknown id can never break a
    render.
    """
    return config_module.app_setting_str(RESUME_TEMPLATE_SETTING_KEY) or DEFAULT_TEMPLATE


def _key_record(name: str) -> dict:
    source = secret_source(name)
    return {"name": name, "configured": source is not None, "source": source}


def get_keys_settings() -> dict:
    return {"keys": [_key_record(name) for name in MANAGED_SECRET_NAMES]}


def upsert_key(name: str, value: str) -> dict:
    """PUT /api/settings/keys. Raises ValueError for an empty/whitespace value (mapped to 422
    by the router) -- store_secret never touches the keychain in that case. Invalidates the
    catalog cache so a newly-added key's real model list is available on the very next
    GET /api/settings/providers, not after up to CATALOG_CACHE_TTL_SECONDS."""
    store_secret(name, value)
    model_catalog.invalidate_catalog_cache()
    return _key_record(name)


def delete_key(name: str) -> None:
    delete_secret(name)
    model_catalog.invalidate_catalog_cache()
