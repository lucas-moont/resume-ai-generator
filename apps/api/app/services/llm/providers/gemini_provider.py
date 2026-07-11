from __future__ import annotations

import json

import httpx

from app.services.llm.providers.base import AuthMode, ProviderContext, ProviderName


def _gemini_error_message(data: dict, status: int) -> str:
    err = data.get("error")
    if isinstance(err, dict):
        msg = (err.get("message") or err.get("status") or "").strip()
        if msg:
            return f"Gemini API HTTP {status}: {msg}"
    raw = json.dumps(data, ensure_ascii=False)[:800]
    return f"Gemini API HTTP {status}. Body: {raw or '(empty)'}"


def _extract_text(data: dict) -> str:
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        prompt_fb = data.get("promptFeedback")
        if isinstance(prompt_fb, dict):
            br = prompt_fb.get("blockReason")
            if br:
                return ""
        return ""
    first = candidates[0]
    if not isinstance(first, dict):
        return ""
    content = first.get("content")
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if not isinstance(parts, list):
        return ""
    texts: list[str] = []
    for p in parts:
        if isinstance(p, dict) and isinstance(p.get("text"), str):
            texts.append(p["text"])
    return "".join(texts).strip()


class GeminiProvider:
    name: ProviderName = "gemini"

    def __init__(self, ctx: ProviderContext) -> None:
        self._ctx = ctx

    @property
    def auth_mode(self) -> AuthMode:
        # Gemini has no local-session fallback like Claude's CLI path -- no key means there is
        # no viable auth path at all.
        return "api_key" if (self._ctx.gemini_api_key or "").strip() else "none"

    @property
    def is_available(self) -> bool:
        return self.auth_mode == "api_key"

    async def chat_json(
        self,
        system: str,
        user: str,
        model_override: str | None = None,
    ) -> str:
        key = (self._ctx.gemini_api_key or "").strip()
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set.")
        model_name = (model_override or self._ctx.default_gemini_model or "gemini-2.5-flash").strip()
        # Send the key in a header, never in the URL query string: URLs leak into logs, proxies,
        # and httpx exception/traceback text; the header does not.
        url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"models/{model_name}:generateContent"
        )
        headers = {"x-goog-api-key": key}
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": self._ctx.llm_temperature,
                "topP": 0.95,
                "maxOutputTokens": self._ctx.gemini_max_output_tokens,
            },
        }
        async with httpx.AsyncClient(timeout=float(self._ctx.llm_timeout_seconds)) as client:
            r = await client.post(url, json=payload, headers=headers)
            try:
                data = r.json()
            except json.JSONDecodeError:
                raise RuntimeError(
                    f"Gemini API returned non-JSON (HTTP {r.status_code}): {(r.text or '')[:500]}"
                ) from None
            if not r.is_success:
                raise RuntimeError(_gemini_error_message(data, r.status_code))
        text = _extract_text(data)
        if not text:
            raise RuntimeError(
                "Gemini returned an empty response (no candidate text). "
                "Check model name (GEMINI_MODEL), quota, and API key permissions."
            )
        return text
