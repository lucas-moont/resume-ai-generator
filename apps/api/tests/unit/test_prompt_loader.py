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
    def test_composes_base_craft_and_tailoring_blocks(self) -> None:
        text = load_generate_system_prompt(PROMPTS_DIR)
        # base system prompt
        assert "You output ONLY valid JSON" in text
        # resume-craft skill block (distilled ResumeSkills)
        assert "Resume writing craft" in text
        assert "Honest quantification" in text
        # tailoring workflow skill block
        assert "Tailored resume generator" in text
        # humanizer skill block (distilled blader/humanizer)
        assert "Human voice" in text
        # composed with the section separator
        assert "\n\n---\n\n" in text

    def test_missing_file_raises_file_not_found(self, tmp_path) -> None:
        import pytest

        with pytest.raises(FileNotFoundError):
            load_generate_system_prompt(tmp_path)


class TestLoadRefineSystemPrompt:
    def test_composes_refine_with_craft_block(self) -> None:
        text = load_refine_system_prompt(PROMPTS_DIR)
        # refine-specific base prompt
        assert "revise an existing resume" in text
        # shared resume-craft skill block
        assert "Resume writing craft" in text
        assert "surface, never estimate" in text
        # humanizer skill block
        assert "Human voice" in text
        assert "\n\n---\n\n" in text

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
