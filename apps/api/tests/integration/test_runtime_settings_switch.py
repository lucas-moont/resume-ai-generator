"""v3 ticket 01 acceptance criterion: "provider X ativo -> escrita de settings -> proxima
chamada usa provider Y, sem restart e sem reload de modulo."

Exercises the real seam a caller goes through (provider_resolver.resolve_active_provider(),
which llm_client.chat_json/llm_backend_label route through) rather than just
config.get_runtime_config() directly, proving the whole chain -- app_settings write ->
config cache invalidation -> provider resolution -- works end to end in one process, one
import, no monkeypatching of the resolver itself.
"""

from __future__ import annotations

import pytest

from app import config
from app.services.llm.provider_resolver import resolve_active_provider
from app.services.llm_client import llm_backend_label


@pytest.fixture(autouse=True)
def _no_provider_keys_or_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    # Auto-detection (see resolve_provider_name) prefers Claude, then Gemini, then Ollama --
    # clear the keys too so the "no explicit provider" baseline is deterministically ollama.
    for name in ("AI_PROVIDER", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_provider_switches_on_the_very_next_call_after_a_settings_write() -> None:
    assert resolve_active_provider().name == "ollama"  # provider X: the default, no config at all

    config.set_app_setting("ai_provider", "claude")

    assert resolve_active_provider().name == "claude"  # provider Y, same process, no reimport


def test_llm_backend_label_reflects_the_same_switch() -> None:
    """llm_backend_label() is the small public seam tests/conftest.py's fake_llm and
    test_llm_client.py already patch around -- confirming it observes the same switch as
    resolve_active_provider() closes the loop for the actual chat_json() caller."""
    assert llm_backend_label() == "ollama"

    config.set_app_setting("ai_provider", "gemini")

    assert llm_backend_label() == "gemini"


def test_switch_back_to_auto_by_deleting_the_setting() -> None:
    config.set_app_setting("ai_provider", "claude")
    assert resolve_active_provider().name == "claude"

    config.delete_app_setting("ai_provider")

    assert resolve_active_provider().name == "ollama"
