"""Unit tests for app/services/llm/proposal_json_parser.py (v4 ticket B2).

Both parsers are pure and MUST NEVER raise on garbage input (mirrors
``merge_service.parse_patch_ops_from_llm_response``'s tolerance philosophy) -- every malformed
case returns ``None`` rather than propagating a JSON/validation error, so a chat turn never
blows up on a bad LLM response.
"""

from __future__ import annotations

import json

from app.services.llm.proposal_json_parser import (
    ParsedProposal,
    ParsedProposalTurn,
    parse_proposal_json,
    parse_proposal_turn_json,
)

_VALID_ITEM = {
    "id": 1,
    "section": "headline",
    "current": "Dev Backend",
    "proposed": "Backend Engineer especializado em Python",
    "rationale": "A vaga pede Python e APIs escaláveis.",
}
_VALID_ITEM_2 = {
    "id": 2,
    "section": "summary",
    "current": None,
    "proposed": "Backend engineer focado em sistemas distribuídos.",
    "rationale": "A vaga menciona sistemas distribuídos.",
}


class TestParseProposalJson:
    def test_clean_response_parses_message_and_items(self) -> None:
        raw = json.dumps({"message": "Aqui estão as melhorias.", "items": [_VALID_ITEM, _VALID_ITEM_2]})
        result = parse_proposal_json(raw)
        assert isinstance(result, ParsedProposal)
        assert result.message == "Aqui estão as melhorias."
        assert len(result.items) == 2
        assert result.items[0].section == "headline"
        assert result.items[0].proposed == "Backend Engineer especializado em Python"
        assert result.items[1].current is None

    def test_strips_json_code_fences(self) -> None:
        raw = "```json\n" + json.dumps({"message": "ok", "items": [_VALID_ITEM]}) + "\n```"
        result = parse_proposal_json(raw)
        assert result is not None
        assert result.message == "ok"
        assert len(result.items) == 1

    def test_extra_fields_are_ignored(self) -> None:
        payload = {
            "message": "ok",
            "items": [_VALID_ITEM],
            "unexpectedTopLevelField": "junk",
        }
        item_with_extra = {**_VALID_ITEM, "confidence": 0.9, "extra": {"nested": True}}
        payload["items"] = [item_with_extra]
        result = parse_proposal_json(json.dumps(payload))
        assert result is not None
        assert len(result.items) == 1
        assert result.items[0].proposed == _VALID_ITEM["proposed"]

    def test_item_with_section_outside_whitelist_is_discarded_rest_survives(self) -> None:
        bad_item = {**_VALID_ITEM, "id": 99, "section": "hobbies"}
        raw = json.dumps({"message": "ok", "items": [bad_item, _VALID_ITEM_2]})
        result = parse_proposal_json(raw)
        assert result is not None
        assert len(result.items) == 1
        assert result.items[0].section == "summary"

    def test_zero_valid_items_returns_none(self) -> None:
        bad_item = {**_VALID_ITEM, "section": "hobbies"}
        raw = json.dumps({"message": "ok", "items": [bad_item]})
        assert parse_proposal_json(raw) is None

    def test_no_items_key_returns_none(self) -> None:
        assert parse_proposal_json(json.dumps({"message": "ok"})) is None

    def test_broken_json_returns_none(self) -> None:
        assert parse_proposal_json("{not valid json at all") is None

    def test_non_object_json_returns_none(self) -> None:
        assert parse_proposal_json(json.dumps([1, 2, 3])) is None

    def test_empty_message_with_valid_items_falls_back_to_deterministic_prose(self) -> None:
        raw = json.dumps({"message": "", "items": [_VALID_ITEM, _VALID_ITEM_2]})
        result = parse_proposal_json(raw)
        assert result is not None
        assert result.message.strip() != ""
        # The deterministic fallback is built FROM the items -- it must reference their content,
        # never be a generic "something went wrong" placeholder.
        assert "Backend Engineer especializado em Python" in result.message
        assert "Backend engineer focado em sistemas distribuídos." in result.message

    def test_missing_message_key_also_falls_back(self) -> None:
        raw = json.dumps({"items": [_VALID_ITEM]})
        result = parse_proposal_json(raw)
        assert result is not None
        assert result.message.strip() != ""

    def test_reassigns_ids_sequentially_1_based_after_dropping_invalid_items(self) -> None:
        bad_item = {**_VALID_ITEM, "id": 5, "section": "hobbies"}
        surviving_item = {**_VALID_ITEM_2, "id": 42}
        raw = json.dumps({"message": "ok", "items": [bad_item, surviving_item]})
        result = parse_proposal_json(raw)
        assert result is not None
        assert result.items[0].id == 1


class TestParseProposalTurnJson:
    def test_clean_approve_response(self) -> None:
        raw = json.dumps({"action": "approve", "reply": "Beleza, vou gerar."})
        result = parse_proposal_turn_json(raw)
        assert isinstance(result, ParsedProposalTurn)
        assert result.action == "approve"
        assert result.reply == "Beleza, vou gerar."
        assert result.items is None

    def test_adjust_with_items_parses_full_item_list(self) -> None:
        raw = json.dumps(
            {"action": "adjust", "reply": "Ajustei o headline.", "items": [_VALID_ITEM, _VALID_ITEM_2]}
        )
        result = parse_proposal_turn_json(raw)
        assert result is not None
        assert result.action == "adjust"
        assert result.items is not None
        assert len(result.items) == 2

    def test_question_response_without_items(self) -> None:
        raw = json.dumps({"action": "question", "reply": "Você quer que eu inclua projetos também?"})
        result = parse_proposal_turn_json(raw)
        assert result is not None
        assert result.action == "question"
        assert result.items is None

    def test_new_jd_response(self) -> None:
        raw = json.dumps({"action": "new_jd", "reply": "Nova vaga detectada, refazendo a análise."})
        result = parse_proposal_turn_json(raw)
        assert result is not None
        assert result.action == "new_jd"

    def test_action_outside_whitelist_returns_none(self) -> None:
        raw = json.dumps({"action": "delete_everything", "reply": "..."})
        assert parse_proposal_turn_json(raw) is None

    def test_missing_action_returns_none(self) -> None:
        assert parse_proposal_turn_json(json.dumps({"reply": "..."})) is None

    def test_non_string_action_returns_none(self) -> None:
        raw = json.dumps({"action": ["approve"], "reply": "..."})
        assert parse_proposal_turn_json(raw) is None

    def test_adjust_without_items_returns_none(self) -> None:
        raw = json.dumps({"action": "adjust", "reply": "Ajustei."})
        assert parse_proposal_turn_json(raw) is None

    def test_adjust_with_empty_items_list_returns_none(self) -> None:
        raw = json.dumps({"action": "adjust", "reply": "Ajustei.", "items": []})
        assert parse_proposal_turn_json(raw) is None

    def test_adjust_with_all_items_invalid_returns_none(self) -> None:
        bad_item = {**_VALID_ITEM, "section": "hobbies"}
        raw = json.dumps({"action": "adjust", "reply": "Ajustei.", "items": [bad_item]})
        assert parse_proposal_turn_json(raw) is None

    def test_broken_json_returns_none(self) -> None:
        assert parse_proposal_turn_json("not json") is None

    def test_non_object_json_returns_none(self) -> None:
        assert parse_proposal_turn_json(json.dumps(["approve"])) is None

    def test_strips_json_code_fences(self) -> None:
        raw = "```json\n" + json.dumps({"action": "approve", "reply": "ok"}) + "\n```"
        result = parse_proposal_turn_json(raw)
        assert result is not None
        assert result.action == "approve"
