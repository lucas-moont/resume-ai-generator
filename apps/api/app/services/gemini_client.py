import json

import httpx

from app.config import DEFAULT_GEMINI_MODEL, GEMINI_API_KEY


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


async def chat_json_gemini(system: str, user: str) -> str:
    key = (GEMINI_API_KEY or "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    model = (DEFAULT_GEMINI_MODEL or "gemini-2.5-flash").strip()
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{model}:generateContent?key={key}"
    )
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.35,
        },
    }
    async with httpx.AsyncClient(timeout=300.0) as client:
        r = await client.post(url, json=payload)
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
