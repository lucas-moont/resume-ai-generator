from __future__ import annotations

from app.services.ollama_client import chat_json as chat_json_ollama
from app.services.llm.providers.base import LlmProvider, ProviderName


class OllamaProvider(LlmProvider):
    name: ProviderName = "ollama"

    async def chat_json(
        self,
        system: str,
        user: str,
        model_override: str | None = None,
    ) -> str:
        return await chat_json_ollama(system, user, model=model_override)
