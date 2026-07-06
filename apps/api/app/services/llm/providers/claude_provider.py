from __future__ import annotations

from app.services.claude_client import chat_json_claude
from app.services.llm.providers.base import LlmProvider, ProviderName


class ClaudeProvider(LlmProvider):
    name: ProviderName = "claude"

    async def chat_json(
        self,
        system: str,
        user: str,
        model_override: str | None = None,
    ) -> str:
        return await chat_json_claude(system, user, model=model_override)
