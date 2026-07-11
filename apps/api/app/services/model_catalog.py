"""Model listing for /api/models and /api/settings/providers (v3 ticket 03).

Static Claude/Gemini suggestions are the fallback used offline or without an API key. When a
key is configured, the real catalog is fetched dynamically: Anthropic ``GET /v1/models``,
Gemini ``models.list``, Ollama ``/api/tags`` (the latter always attempted -- it needs no key).
Results are cached for ``CATALOG_CACHE_TTL_SECONDS`` (module-qualified ``_clock``/``_transport``
are the test seams -- see tests/unit/test_model_catalog.py): a fake clock drives TTL expiry
(never ``time.sleep``), and an ``httpx.MockTransport`` replaces the network (never a real call
in tests).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

from app import config as config_module
from app.services.llm_client import llm_backend_label

CLAUDE_MODEL_SUGGESTIONS: list[dict[str, str]] = [
    {"value": "claude-opus-4-8", "label": "Claude Opus 4.8"},
    {"value": "claude-sonnet-5", "label": "Claude Sonnet 5"},
    {"value": "claude-haiku-4-5", "label": "Claude Haiku 4.5"},
]

GEMINI_MODEL_SUGGESTIONS: list[dict[str, str]] = [
    {"value": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
    {"value": "gemini-2.5-flash-lite", "label": "Gemini 2.5 Flash-Lite"},
    {"value": "gemini-3-flash-preview", "label": "Gemini 3 Flash Preview"},
]

ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"
ANTHROPIC_API_VERSION = "2023-06-01"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"

CATALOG_CACHE_TTL_SECONDS = 300.0

# Test seams (module-qualified, same pattern as app.config.set_settings_engine): production
# never touches either -- _transport=None means "real network", _clock=time.monotonic means
# "real time". Tests monkeypatch both so no test ever makes a real HTTP call or sleeps for the
# cache TTL.
_transport: httpx.AsyncBaseTransport | None = None
_clock: Callable[[], float] = time.monotonic

T = TypeVar("T")
_cache: dict[str, tuple[float, object]] = {}


def invalidate_catalog_cache() -> None:
    """Call after a provider/key settings write (v3 ticket 03's routers/settings.py) so the
    very next catalog read is fresh instead of serving up to CATALOG_CACHE_TTL_SECONDS of
    stale data -- e.g. a key just added via PUT /api/settings/keys should unlock that
    provider's real catalog immediately, not after up to 5 minutes."""
    _cache.clear()


def _client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, transport=_transport)


async def _cached(key: str, fetch: Callable[[], Awaitable[T]]) -> T:
    entry = _cache.get(key)
    if entry is not None and _clock() < entry[0]:
        return entry[1]  # type: ignore[return-value]
    value = await fetch()
    _cache[key] = (_clock() + CATALOG_CACHE_TTL_SECONDS, value)
    return value


def ollama_model_label(name: str) -> str:
    if ":cloud" in name:
        return f"{name} (Ollama Cloud)"
    return f"{name} (Ollama, local)"


async def _fetch_ollama_tags() -> tuple[bool, list[str]]:
    """The one Ollama HTTP call the catalog needs: ``(reachable, installed model names)``.
    ``reachable`` distinguishes "the server responded" from a network/HTTP error -- used both
    to build the installed-model list and (v3 ticket 03's own decision, flagged as open by
    ticket 02) as a real availability signal for GET /api/settings/providers, since
    ``OllamaProvider.is_available`` is a sync, no-I/O check that is always ``True``.
    """
    base = config_module.OLLAMA_BASE_URL.rstrip("/")
    try:
        async with _client(10.0) as client:
            r = await client.get(f"{base}/api/tags")
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, ValueError):
        return False, []
    models = data.get("models")
    if not isinstance(models, list):
        return True, []
    names = [
        entry["name"].strip()
        for entry in models
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    ]
    return True, sorted(names, key=lambda name: (":cloud" in name, name.lower()))


async def list_installed_models() -> list[str]:
    """Locally-installed Ollama model names for /api/models. Moved here from the retired
    ``app.services.ollama_client`` (v3 ticket 03) -- same signature/behavior, now sharing
    ``_fetch_ollama_tags`` with the reachability probe below."""
    _, names = await _fetch_ollama_tags()
    return names


async def ollama_reachable() -> bool:
    """Real reachability signal for GET /api/settings/providers, cached like the rest of the
    catalog. See ``_fetch_ollama_tags`` for why this exists alongside
    ``OllamaProvider.is_available``."""
    reachable, _ = await _cached("ollama", _fetch_ollama_tags)
    return reachable


async def _fetch_anthropic_models(api_key: str) -> list[dict[str, str]] | None:
    """``None`` signals a failed fetch (network/HTTP/shape error) -- distinct from an empty
    list (a legitimately empty catalog) -- so the caller only falls back to the static
    suggestions on failure."""
    try:
        async with _client(10.0) as client:
            r = await client.get(
                ANTHROPIC_MODELS_URL,
                headers={"x-api-key": api_key, "anthropic-version": ANTHROPIC_API_VERSION},
            )
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    items = data.get("data")
    if not isinstance(items, list):
        return None
    models: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        display_name = item.get("display_name")
        label = display_name if isinstance(display_name, str) and display_name else item["id"]
        models.append({"value": item["id"], "label": label})
    return models


async def _fetch_gemini_models(api_key: str) -> list[dict[str, str]] | None:
    try:
        async with _client(10.0) as client:
            r = await client.get(GEMINI_MODELS_URL, headers={"x-goog-api-key": api_key})
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    items = data.get("models")
    if not isinstance(items, list):
        return None
    models: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        # Gemini's resource name is "models/gemini-2.5-flash"; the rest of this app (model
        # pickers, provider routing by name prefix) works with the bare id.
        value = item["name"].rsplit("/", 1)[-1]
        display_name = item.get("displayName")
        label = display_name if isinstance(display_name, str) and display_name else value
        models.append({"value": value, "label": label})
    return models


async def claude_models(api_key: str | None) -> list[dict[str, str]]:
    key = (api_key or "").strip()
    if not key:
        return CLAUDE_MODEL_SUGGESTIONS
    fetched = await _cached("claude", lambda: _fetch_anthropic_models(key))
    return fetched if fetched is not None else CLAUDE_MODEL_SUGGESTIONS


async def gemini_models(api_key: str | None) -> list[dict[str, str]]:
    key = (api_key or "").strip()
    if not key:
        return GEMINI_MODEL_SUGGESTIONS
    fetched = await _cached("gemini", lambda: _fetch_gemini_models(key))
    return fetched if fetched is not None else GEMINI_MODEL_SUGGESTIONS


def default_model_for_active_backend() -> str:
    backend = llm_backend_label()
    runtime = config_module.get_runtime_config()
    if backend == "claude":
        return runtime.default_claude_model
    if backend == "gemini":
        return runtime.default_gemini_model
    return runtime.default_ollama_model or runtime.default_claude_model


async def list_models_catalog() -> dict:
    runtime = config_module.get_runtime_config()
    claude_items = await claude_models(runtime.anthropic_api_key)
    gemini_items = await gemini_models(runtime.gemini_api_key)
    ollama_names = await list_installed_models()

    seen: set[str] = set()
    models: list[dict[str, str]] = []
    for item in claude_items:
        if item["value"] in seen:
            continue
        seen.add(item["value"])
        models.append({**item, "provider": "claude"})
    for item in gemini_items:
        if item["value"] in seen:
            continue
        seen.add(item["value"])
        models.append({**item, "provider": "gemini"})
    for name in ollama_names:
        if name in seen:
            continue
        seen.add(name)
        models.append({"value": name, "label": ollama_model_label(name), "provider": "ollama"})
    return {
        "default": default_model_for_active_backend(),
        "models": models,
    }
