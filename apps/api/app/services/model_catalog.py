"""Model listing for /api/models -- extracted from app/main.py (B4).

Static Claude/Gemini suggestions plus whatever Ollama tags are installed locally; dynamic
per-provider catalogs are a v3 concern (see docs/v1-chat-experience.md).
"""

from app import config as config_module
from app.services.llm_client import llm_backend_label
from app.services.ollama_client import list_installed_models

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


def default_model_for_active_backend() -> str:
    backend = llm_backend_label()
    runtime = config_module.get_runtime_config()
    if backend == "claude":
        return runtime.default_claude_model
    if backend == "gemini":
        return runtime.default_gemini_model
    return runtime.default_ollama_model or runtime.default_claude_model


def ollama_model_label(name: str) -> str:
    if ":cloud" in name:
        return f"{name} (Ollama Cloud)"
    return f"{name} (Ollama, local)"


async def list_models_catalog() -> dict:
    ollama_names = await list_installed_models()
    seen: set[str] = set()
    models: list[dict[str, str]] = []
    for item in (*CLAUDE_MODEL_SUGGESTIONS, *GEMINI_MODEL_SUGGESTIONS):
        value = item["value"]
        if value in seen:
            continue
        seen.add(value)
        models.append(item)
    for name in ollama_names:
        if name in seen:
            continue
        seen.add(name)
        models.append({"value": name, "label": ollama_model_label(name)})
    return {
        "default": default_model_for_active_backend(),
        "models": models,
    }
