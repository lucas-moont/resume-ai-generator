from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

ProviderName = Literal["claude", "gemini", "ollama"]
ProviderMode = Literal["auto", "claude", "gemini", "ollama"]


@dataclass(frozen=True)
class ProviderContext:
    gemini_api_key: str | None
    mode: ProviderMode
    anthropic_api_key: str | None = None


class LlmProvider(Protocol):
    name: ProviderName

    async def chat_json(
        self,
        system: str,
        user: str,
        model_override: str | None = None,
    ) -> str: ...
