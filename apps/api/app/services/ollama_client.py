from app import config as config_module

import httpx


async def list_installed_models() -> list[str]:
    """Locally-installed Ollama model names for /api/models -- kept here (rather than folded
    into `app.services.llm.providers.ollama_provider`, v3 ticket 02) because it is not part of
    the `LlmProvider.chat_json` seam: `model_catalog.py` calls it directly, and it stays
    importable from this path until v3 ticket 03 moves catalog listing under model_catalog."""
    base = config_module.OLLAMA_BASE_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{base}/api/tags")
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError:
        return []
    models = data.get("models")
    if not isinstance(models, list):
        return []
    names: list[str] = []
    for entry in models:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            names.append(entry["name"].strip())
    return sorted(names, key=lambda name: (":cloud" in name, name.lower()))
