"""Unit tests for the v4 prompt loaders added to app/prompt_loader.py (ticket B2)."""

from __future__ import annotations

from app.config import PROMPTS_DIR
from app.prompt_loader import (
    load_propose_improvements_system_prompt,
    load_proposal_turn_system_prompt,
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
