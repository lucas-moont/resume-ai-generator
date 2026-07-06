from __future__ import annotations

from app.services.gemini_client import chat_json_gemini
from app.services.llm.providers.base import LlmProvider, ProviderName


class GeminiProvider(LlmProvider):
    name: ProviderName = "gemini"

    async def chat_json(
        self,
        system: str,
        user: str,
        model_override: str | None = None,
    ) -> str:
        return await chat_json_gemini(system, user, model=model_override)
