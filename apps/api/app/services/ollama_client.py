import json

import httpx

from app.config import (
    DEFAULT_OLLAMA_MODEL,
    LLM_TEMPERATURE,
    LLM_TIMEOUT_SECONDS,
    OLLAMA_BASE_URL,
    OLLAMA_NUM_CTX,
    OLLAMA_NUM_PREDICT,
)


def _ollama_options() -> dict:
    return {
        "temperature": LLM_TEMPERATURE,
        "top_p": 0.9,
        "num_ctx": OLLAMA_NUM_CTX,
        "num_predict": OLLAMA_NUM_PREDICT,
    }


def _ollama_json_payload(model: str, system: str, user: str) -> dict:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": "json",
        # Disable chain-of-thought: reasoning-capable models (e.g. gemma4) otherwise spend the
        # num_predict budget on the "thinking" field and return empty JSON content. Ignored by
        # models without thinking support.
        "think": False,
        "options": _ollama_options(),
    }


def _generate_prompt(system: str, user: str) -> str:
    return (
        "You are a helpful assistant. Follow the system instructions exactly, "
        "then answer the user. Output only valid JSON when asked.\n\n"
        f"### System\n{system}\n\n### User\n{user}"
    )


def _ollama_http_error_message(r: httpx.Response, base: str, model: str) -> str:
    raw = (r.text or "")[:800]
    api_err = ""
    try:
        body = r.json()
        if isinstance(body.get("error"), str):
            api_err = body["error"].strip()
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    if api_err and "not found" in api_err.lower():
        return (
            f"{api_err} Run `ollama pull {model}` to install it, or set OLLAMA_MODEL in .env "
            f"to an exact name from `ollama list` (Ollama returns HTTP {r.status_code} for missing models)."
        )
    hint = (
        f"Ollama HTTP {r.status_code} at {r.request.url!s}. "
        f"Check OLLAMA_BASE_URL ({base}, no /v1 path), `ollama serve`, and that the model exists (`ollama list`)."
    )
    if api_err:
        return f"{api_err} {hint}"
    return f"{hint} Body: {raw or '(empty)'}"


def _extract_content(data: dict) -> str:
    if isinstance(data.get("message"), dict):
        return ((data.get("message") or {}).get("content") or "").strip()
    if "response" in data:
        return (data.get("response") or "").strip()
    return ""


async def list_installed_models() -> list[str]:
    base = OLLAMA_BASE_URL.rstrip("/")
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


async def chat_json(
    system: str,
    user: str,
    model: str | None = None,
) -> str:
    model = model or DEFAULT_OLLAMA_MODEL
    base = OLLAMA_BASE_URL.rstrip("/")
    chat_url = f"{base}/api/chat"
    gen_url = f"{base}/api/generate"

    async def _request_once(client: httpx.AsyncClient) -> str:
        r = await client.post(chat_url, json=_ollama_json_payload(model, system, user))
        if not r.is_success:
            r = await client.post(
                gen_url,
                json={
                    "model": model,
                    "prompt": _generate_prompt(system, user),
                    "stream": False,
                    "format": "json",
                    "think": False,
                    "options": _ollama_options(),
                },
            )
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(_ollama_http_error_message(r, base, model)) from e
        return _extract_content(r.json())

    async with httpx.AsyncClient(timeout=float(LLM_TIMEOUT_SECONDS)) as client:
        content = await _request_once(client)
        if not content:
            # Local models occasionally return an empty completion; a single retry usually
            # recovers before surfacing a confusing "invalid JSON" error downstream.
            content = await _request_once(client)

    if not content:
        raise RuntimeError(
            f"Ollama model '{model}' returned an empty response. Local models can do this "
            "intermittently under load or with a short output budget — try again, increase "
            "OLLAMA_NUM_PREDICT in .env, or switch OLLAMA_MODEL to a stronger model."
        )
    return content
