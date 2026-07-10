"""Unit tests for Markdown Source Document ingestion (v2 ticket 03).

Per docs/v2-living-profile.md item 2: Markdown has no fixed schema, so (unlike ingest_json)
this always goes through LLM extraction. The LLM boundary is the same module-qualified
``app.services.llm_client.chat_json`` every other LLM call in the app uses (see
tests/fakes.py's ``FakeLlm`` docstring) -- patched here directly rather than via the
conftest.py ``fake_llm`` fixture, since this module has no FastAPI request in play.
"""

from __future__ import annotations

import json

import pytest

from app.domain.schemas import ResumeDocument
from app.services import llm_client as llm_client_module
from app.services.ingestion.ingest_markdown import ingest_markdown
from tests.fakes import FakeLlm


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeLlm:
    fake = FakeLlm()
    monkeypatch.setattr(llm_client_module, "chat_json", fake)
    return fake


class TestIngestMarkdown:
    async def test_extracts_a_resume_document_via_the_llm(self, fake_llm: FakeLlm):
        fake_llm.queue(
            json.dumps({"fullName": "Bruno Reis", "headline": "Data Engineer", "summary": "Summary."})
        )
        raw = b"""---
name: Bruno Reis
title: Data Engineer
---
## Experience
Some markdown body.
"""

        result = await ingest_markdown(raw)

        assert isinstance(result, ResumeDocument)
        assert result.fullName == "Bruno Reis"
        assert fake_llm.call_count == 1

    async def test_frontmatter_metadata_and_body_both_reach_the_llm_prompt(self, fake_llm: FakeLlm):
        fake_llm.queue(json.dumps({"fullName": "Carla Dias", "headline": "PM", "summary": "S."}))
        raw = b"""---
name: Carla Dias
---
Body paragraph mentioning Product Management experience.
"""

        await ingest_markdown(raw)

        user_prompt = fake_llm.calls[0]["user"]
        assert "Carla Dias" in user_prompt
        assert "Product Management" in user_prompt

    async def test_markdown_without_frontmatter_still_extracts(self, fake_llm: FakeLlm):
        fake_llm.queue(json.dumps({"fullName": "No Frontmatter", "headline": "Engineer", "summary": "S."}))
        raw = b"# Just a plain markdown body, no frontmatter block."

        result = await ingest_markdown(raw)

        assert result.fullName == "No Frontmatter"

    async def test_model_override_is_forwarded_to_the_llm(self, fake_llm: FakeLlm):
        fake_llm.queue(json.dumps({"fullName": "X", "headline": "Y", "summary": "Z"}))

        await ingest_markdown(b"plain body", model="claude-sonnet-5")

        assert fake_llm.calls[0]["model"] == "claude-sonnet-5"
