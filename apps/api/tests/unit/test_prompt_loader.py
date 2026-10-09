"""Unit tests for the v4 prompt loaders added to app/prompt_loader.py (ticket B2)."""

from __future__ import annotations

from app.config import PROMPTS_DIR
from app.prompt_loader import (
    load_converse_system_prompt,
    load_generate_system_prompt,
    load_linkedin_analysis_system_prompt,
    load_propose_improvements_system_prompt,
    load_proposal_turn_system_prompt,
    load_refine_system_prompt,
)


class TestLoadProposeImprovementsSystemPrompt:
    def test_loads_the_analysis_prompt_file(self) -> None:
        text = load_propose_improvements_system_prompt(PROMPTS_DIR)
        assert "message" in text
        assert "items" in text

    def test_missing_file_raises_file_not_found(self, tmp_path) -> None:
        import pytest

        with pytest.raises(FileNotFoundError):
            load_propose_improvements_system_prompt(tmp_path)


class TestLoadProposalTurnSystemPrompt:
    def test_loads_the_proposal_turn_prompt_file(self) -> None:
        text = load_proposal_turn_system_prompt(PROMPTS_DIR)
        assert "action" in text
        assert "reply" in text

    def test_missing_file_raises_file_not_found(self, tmp_path) -> None:
        import pytest

        with pytest.raises(FileNotFoundError):
            load_proposal_turn_system_prompt(tmp_path)


class TestLoadGenerateSystemPrompt:
    def test_loads_the_generate_contract_without_vendor_skill_blocks(self) -> None:
        text = load_generate_system_prompt(PROMPTS_DIR)
        assert "You output ONLY valid JSON" in text
        assert "NEVER invent" in text
        assert "Human voice" in text
        # Distilled skill files stay on disk as reference; composing them doubled the
        # generate system prompt (~6k tokens) with rules generate.md already states.
        assert "Resume writing craft" not in text
        assert "Tailored resume generator" not in text
        assert "\n\n---\n\n" not in text

    def test_missing_file_raises_file_not_found(self, tmp_path) -> None:
        import pytest

        with pytest.raises(FileNotFoundError):
            load_generate_system_prompt(tmp_path)


class TestLoadRefineSystemPrompt:
    def test_loads_refine_without_repeating_generate_craft_blocks(self) -> None:
        text = load_refine_system_prompt(PROMPTS_DIR)
        assert "revise an existing resume" in text
        assert "Resume writing craft" not in text
        assert "\n\n---\n\n" not in text

    def test_missing_file_raises_file_not_found(self, tmp_path) -> None:
        import pytest

        with pytest.raises(FileNotFoundError):
            load_refine_system_prompt(tmp_path)


class TestLoadConverseSystemPrompt:
    def test_composes_the_converse_prompt_with_the_humanizer_block(self) -> None:
        text = load_converse_system_prompt(PROMPTS_DIR)
        # the read-only contract and its single output field
        assert '"reply"' in text
        assert "never" in text.lower()  # it must state it never edits the resume
        # the ask-instead-of-guessing valve for an edit-shaped request
        assert "aplique" in text.lower()
        # humanizer skill block, composed on (conversational prose)
        assert "Human voice" in text
        assert "\n\n---\n\n" in text

    def test_missing_file_raises_file_not_found(self, tmp_path) -> None:
        import pytest

        with pytest.raises(FileNotFoundError):
            load_converse_system_prompt(tmp_path)


class TestLoadLinkedinAnalysisSystemPrompt:
    def test_loads_the_analysis_prompt_file(self) -> None:
        text = load_linkedin_analysis_system_prompt(PROMPTS_DIR)
        assert "LinkedIn profile advisor" in text
        # the two output shapes and the ask-instead-of-guessing valve
        assert '"type": "analysis"' in text
        assert '"type": "question"' in text
        # humanizer skill block, composed onto the analysis prompt
        assert "Human voice" in text
        assert "\n\n---\n\n" in text

    def test_missing_file_raises_file_not_found(self, tmp_path) -> None:
        import pytest

        with pytest.raises(FileNotFoundError):
            load_linkedin_analysis_system_prompt(tmp_path)
