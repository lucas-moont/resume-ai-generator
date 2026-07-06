from __future__ import annotations

from app.config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MAX_OUTPUT_TOKENS,
    CLAUDE_THINKING,
    DEFAULT_CLAUDE_MODEL,
    LLM_TIMEOUT_SECONDS,
)

# NOTE: temperature / top_p are intentionally NOT sent. Claude Sonnet 5, Opus 4.8 and 4.7 reject
# sampling parameters (HTTP 400), so the shared LLM_TEMPERATURE does not apply to this provider.


def _thinking_config() -> dict:
    # "adaptive" lets Claude reason before answering; "off" (disabled) gives the full max_tokens
    # budget to the JSON output, which is what a resume-generation task wants by default.
    if CLAUDE_THINKING == "adaptive":
        return {"type": "adaptive"}
    return {"type": "disabled"}


def _extract_text(message) -> str:
    parts: list[str] = []
    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", "") or ""
            if text:
                parts.append(text)
    return "".join(parts).strip()


def _error_message(exc: Exception, model: str) -> str:
    status = getattr(exc, "status_code", None)
    detail = str(getattr(exc, "message", "") or exc).strip()
    hint = (
        "Authenticate with `ant auth login` (local Claude session) or set ANTHROPIC_API_KEY in .env, "
        f"and confirm your account can access the model (CLAUDE_MODEL='{model}')."
    )
    if status:
        return f"Claude API HTTP {status}: {detail or '(no message)'} {hint}"
    return f"Claude request failed: {detail or exc.__class__.__name__}. {hint}"


async def chat_json_claude(system: str, user: str, model: str | None = None) -> str:
    try:
        from anthropic import AsyncAnthropic
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "The 'anthropic' package is not installed. Run "
            "`pip install -r apps/api/requirements.txt` inside your virtualenv."
        ) from e

    model_name = (model or DEFAULT_CLAUDE_MODEL or "claude-sonnet-5").strip()
    # If we resolved a key (from env OR the OS keychain, via config), pass it explicitly so a
    # keychain-stored key works. With no key, a bare client lets the SDK use a local
    # `ant auth login` OAuth profile — no key stored in this project at all.
    if ANTHROPIC_API_KEY:
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY, timeout=float(LLM_TIMEOUT_SECONDS))
    else:
        client = AsyncAnthropic(timeout=float(LLM_TIMEOUT_SECONDS))
    try:
        message = await client.messages.create(
            model=model_name,
            max_tokens=CLAUDE_MAX_OUTPUT_TOKENS,
            system=system,
            thinking=_thinking_config(),
            messages=[{"role": "user", "content": user}],
        )
    except Exception as e:  # anthropic.APIError subclasses + connection/auth errors
        raise RuntimeError(_error_message(e, model_name)) from e
    finally:
        await client.close()

    if getattr(message, "stop_reason", None) == "refusal":
        raise RuntimeError(
            "Claude declined to answer this request (stop_reason=refusal). "
            "Adjust the profile or job description text and try again."
        )

    text = _extract_text(message)
    if not text:
        raise RuntimeError(
            f"Claude ('{model_name}') returned an empty response. If the output was cut off, "
            "raise CLAUDE_MAX_OUTPUT_TOKENS in .env; otherwise verify authentication "
            "(`ant auth login` or ANTHROPIC_API_KEY) and that your account can use this model."
        )
    return text
