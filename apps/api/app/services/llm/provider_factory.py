from __future__ import annotations

from app.services.llm.providers.base import LlmProvider, ProviderContext, ProviderName
from app.services.llm.providers.claude_provider import ClaudeProvider
from app.services.llm.providers.gemini_provider import GeminiProvider
from app.services.llm.providers.ollama_provider import OllamaProvider


def build_provider(name: ProviderName, ctx: ProviderContext) -> LlmProvider:
    """Construct the adapter for ``name`` with ``ctx`` injected -- the adapter itself never
    imports `app.config` (v3 ticket 02). Callers assemble ``ctx`` via
    `app.services.llm.provider_resolver.provider_context_for`."""
    if name == "claude":
        return ClaudeProvider(ctx)
    if name == "gemini":
        return GeminiProvider(ctx)
    return OllamaProvider(ctx)
