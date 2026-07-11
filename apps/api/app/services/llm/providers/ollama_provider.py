from __future__ import annotations

import json

import httpx

from app.services.llm.providers.base import AuthMode, ProviderContext, ProviderName


def _ollama_options(ctx: ProviderContext) -> dict:
    return {
        "temperature": ctx.llm_temperature,
        "top_p": 0.9,
        "num_ctx": ctx.ollama_num_ctx,
        "num_predict": ctx.ollama_num_predict,
    }


def _ollama_json_payload(model: str, system: str, user: str, ctx: ProviderContext) -> dict:
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
        "options": _ollama_options(ctx),
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


class OllamaProvider:
    name: ProviderName = "ollama"

    def __init__(self, ctx: ProviderContext) -> None:
        self._ctx = ctx

    @property
    def auth_mode(self) -> AuthMode:
        # A local server has no API key concept -- it's reachable or it isn't.
        return "local"

    @property
    def is_available(self) -> bool:
        # No cheap synchronous availability check exists for a local HTTP server; treat it as
        # always potentially available (chat_json surfaces a clear error if it isn't reachable).
        return True

    async def chat_json(
        self,
        system: str,
        user: str,
        model_override: str | None = None,
    ) -> str:
        model = (model_override or self._ctx.default_ollama_model or "llama3.2").strip()
        base = self._ctx.ollama_base_url.rstrip("/")
        chat_url = f"{base}/api/chat"
        gen_url = f"{base}/api/generate"

        async def _request_once(client: httpx.AsyncClient) -> str:
            r = await client.post(chat_url, json=_ollama_json_payload(model, system, user, self._ctx))
            if not r.is_success:
                r = await client.post(
                    gen_url,
                    json={
                        "model": model,
                        "prompt": _generate_prompt(system, user),
                        "stream": False,
                        "format": "json",
                        "think": False,
                        "options": _ollama_options(self._ctx),
                    },
                )
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise RuntimeError(_ollama_http_error_message(r, base, model)) from e
            return _extract_content(r.json())

        async with httpx.AsyncClient(timeout=float(self._ctx.llm_timeout_seconds)) as client:
            content = await _request_once(client)
            if not content:
                # Local models occasionally return an empty completion; a single retry usually
                # recovers before surfacing a confusing "invalid JSON" error downstream.
                content = await _request_once(client)

        if not content:
            raise RuntimeError(
                f"Ollama model '{model}' returned an empty response. Local models can do this "
                "intermittently under load or with a short output budget -- try again, increase "
                "OLLAMA_NUM_PREDICT in .env, or switch OLLAMA_MODEL to a stronger model."
            )
        return content
