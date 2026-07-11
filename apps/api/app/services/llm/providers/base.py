from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

ProviderName = Literal["claude", "gemini", "ollama"]
ProviderMode = Literal["auto", "claude", "gemini", "ollama"]
# Consultable per-provider auth surface (v3 ticket 02): "none" is for a provider with no viable
# auth path at all (e.g. Gemini with no key and no local-session fallback) -- the ticket 03
# Settings API reports this alongside `available` so the UI can explain why a provider is greyed
# out instead of just failing on first use.
AuthMode = Literal["api_key", "cli", "local", "none"]


@dataclass(frozen=True)
class ProviderContext:
    """Runtime config injected into a provider adapter at construction time.

    Adapters read ONLY this -- never `app.config` module-qualified constants -- so they behave
    deterministically when constructed directly with a fake context in tests (v3 ticket 02's
    pre-agreed seam: no monkeypatch of a config module needed to test provider behavior).
    `app.services.llm.provider_resolver.provider_context_for` is the one place that reads
    `app.config` to assemble a context for production use.
    """

    mode: ProviderMode

    # repr=False: a stray `logger.info(f"{ctx}")` must not leak either key.
    anthropic_api_key: str | None = field(default=None, repr=False)
    default_claude_model: str = "claude-sonnet-5"
    claude_max_output_tokens: int = 8192
    claude_thinking: str = "off"

    gemini_api_key: str | None = field(default=None, repr=False)
    default_gemini_model: str = "gemini-2.5-flash"
    gemini_max_output_tokens: int = 8192

    ollama_base_url: str = "http://127.0.0.1:11434"
    default_ollama_model: str = "llama3.2"
    ollama_num_ctx: int = 8192
    ollama_num_predict: int = 4096

    llm_temperature: float = 0.4
    llm_timeout_seconds: int = 900


class LlmProvider(Protocol):
    name: ProviderName

    @property
    def auth_mode(self) -> AuthMode: ...

    @property
    def is_available(self) -> bool: ...

    async def chat_json(
        self,
        system: str,
        user: str,
        model_override: str | None = None,
    ) -> str: ...
