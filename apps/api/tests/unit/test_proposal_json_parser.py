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

    # v4.1-02: the Analysis's JSON gained an optional `title` (the job title, for the chat
    # session's own title) -- tolerant by construction, mirroring `message`'s own fallback
    # philosophy but simpler (there is no deterministic fallback for a title -- absence just
    # means "leave the session's existing title alone", decided by the caller, not the parser).
    def test_title_present_is_parsed(self) -> None:
        raw = json.dumps({"message": "ok", "items": [_VALID_ITEM], "title": "Full Stack Engineer"})
        result = parse_proposal_json(raw)
        assert result is not None
        assert result.title == "Full Stack Engineer"

    def test_title_absent_is_none_and_does_not_affect_message_or_items(self) -> None:
        raw = json.dumps({"message": "ok", "items": [_VALID_ITEM]})
        result = parse_proposal_json(raw)
        assert result is not None
        assert result.title is None
        assert result.message == "ok"
        assert len(result.items) == 1

    def test_title_empty_string_is_none(self) -> None:
        raw = json.dumps({"message": "ok", "items": [_VALID_ITEM], "title": "   "})
        result = parse_proposal_json(raw)
        assert result is not None
        assert result.title is None

    def test_title_non_string_is_none_without_failing_the_parse(self) -> None:
        raw = json.dumps({"message": "ok", "items": [_VALID_ITEM], "title": 12345})
        result = parse_proposal_json(raw)
        assert result is not None
        assert result.title is None
        assert len(result.items) == 1

    def test_title_over_120_chars_is_truncated(self) -> None:
        long_title = "A" * 200
        raw = json.dumps({"message": "ok", "items": [_VALID_ITEM], "title": long_title})
        result = parse_proposal_json(raw)
        assert result is not None
        assert result.title == "A" * 120


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


class TestProposalOpAndTargets:
    """v6 (Relevance Filter): ``op``/``targets`` are parsed tolerantly, and the section limits
    on subtraction are enforced here rather than merely requested in the prompt."""

    def _raw(self, item: dict) -> str:
        return json.dumps({"message": "Análise do perfil.", "items": [item]})

    def _item(self, **overrides) -> dict:
        base = {
            "section": "skills",
            "current": "Google Analytics",
            "proposed": "Remover Google Analytics.",
            "rationale": "A vaga não menciona analytics.",
        }
        base.update(overrides)
        return base

    def test_a_valid_drop_keeps_its_op_and_targets(self) -> None:
        parsed = parse_proposal_json(
            self._raw(self._item(op="drop", targets=["Google Analytics", "Power BI"]))
        )
        assert parsed is not None
        assert parsed.items[0].op == "drop"
        assert parsed.items[0].targets == ["Google Analytics", "Power BI"]

    def test_a_missing_op_decodes_to_rewrite_with_no_targets(self) -> None:
        parsed = parse_proposal_json(self._raw(self._item()))
        assert parsed is not None
        assert parsed.items[0].op == "rewrite"
        assert parsed.items[0].targets == []

    def test_an_invented_op_collapses_to_rewrite_instead_of_losing_the_item(self) -> None:
        parsed = parse_proposal_json(self._raw(self._item(op="remove", targets=["Power BI"])))
        assert parsed is not None
        assert len(parsed.items) == 1
        assert parsed.items[0].op == "rewrite"

    def test_a_drop_on_experience_is_downgraded_to_compress(self) -> None:
        # Never let an approved plan carry "remove this employer": that is a timeline gap.
        parsed = parse_proposal_json(
            self._raw(self._item(section="experience", op="drop", targets=["Savvi"]))
        )
        assert parsed is not None
        assert parsed.items[0].op == "compress"

    def test_a_drop_on_education_is_downgraded_to_rewrite(self) -> None:
        parsed = parse_proposal_json(
            self._raw(self._item(section="education", op="drop", targets=["UFU"]))
        )
        assert parsed is not None
        assert parsed.items[0].op == "rewrite"

    def test_a_compress_outside_experience_is_downgraded_to_rewrite(self) -> None:
        parsed = parse_proposal_json(self._raw(self._item(section="skills", op="compress")))
        assert parsed is not None
        assert parsed.items[0].op == "rewrite"

    def test_garbage_targets_become_an_empty_list(self) -> None:
        parsed = parse_proposal_json(
            self._raw(self._item(op="drop", targets=["  ", 7, None, "Power BI"]))
        )
        assert parsed is not None
        assert parsed.items[0].targets == ["Power BI"]

    def test_a_single_string_target_is_accepted_as_a_one_item_list(self) -> None:
        parsed = parse_proposal_json(self._raw(self._item(op="drop", targets="Power BI")))
        assert parsed is not None
        assert parsed.items[0].targets == ["Power BI"]

    def test_the_proposal_turn_carries_ops_through_an_adjust(self) -> None:
        # An adjust returns the COMPLETE revised list; losing `op`/`targets` on the way through
        # would silently turn an agreed removal back into a no-op.
        raw = json.dumps(
            {
                "action": "adjust",
                "reply": "Mantive o Power BI e tirei só o resto.",
                "items": [self._item(op="drop", targets=["Google Analytics"])],
            }
        )
        parsed = parse_proposal_turn_json(raw)
        assert parsed is not None
        assert parsed.items is not None
        assert parsed.items[0].op == "drop"
        assert parsed.items[0].targets == ["Google Analytics"]
