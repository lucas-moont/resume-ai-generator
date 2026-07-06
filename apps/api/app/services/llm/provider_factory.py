from __future__ import annotations

from app.services.llm.providers.base import LlmProvider, ProviderName
from app.services.llm.providers.claude_provider import ClaudeProvider
from app.services.llm.providers.gemini_provider import GeminiProvider
from app.services.llm.providers.ollama_provider import OllamaProvider


def build_provider(name: ProviderName) -> LlmProvider:
    if name == "claude":
        return ClaudeProvider()
    if name == "gemini":
        return GeminiProvider()
    return OllamaProvider()
