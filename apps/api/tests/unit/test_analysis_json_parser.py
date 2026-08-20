"""Unit tests for app/services/llm/analysis_json_parser.py (v5 ticket b2).

The parser is pure and MUST NEVER raise on garbage input (mirrors proposal_json_parser's
tolerance philosophy): every malformed case returns ``None`` rather than propagating a
JSON/validation error, so an Analysis Turn never blows up on a bad LLM response.
"""

from __future__ import annotations

import json

from app.services.llm.analysis_json_parser import (
    ParsedAnalysisQuestion,
    ParsedAnalysisResult,
    parse_analysis_json,
)

_VALID_ITEM = {
    "section": "headline",
    "current": "Dev Backend",
    "suggestion": "Backend Engineer | Python & APIs escaláveis | Sistemas de alta disponibilidade",
    "rationale": "Front-load os termos que recruiters buscam; ≤220 chars.",
    "priority": "alta",
}
_VALID_ITEM_2 = {
    "section": "about",
    "current": None,
    "suggestion": "Abra com um hook de uma linha sobre o impacto que você gera.",
    "rationale": "Os primeiros ~300 chars aparecem antes do 'ver mais'.",
    "priority": "média",
}


class TestParseAnalysis:
    def test_clean_analysis_parses_items_and_summary(self) -> None:
        raw = json.dumps({"type": "analysis", "items": [_VALID_ITEM, _VALID_ITEM_2], "summary": "Foco no headline."})
        result = parse_analysis_json(raw)
        assert isinstance(result, ParsedAnalysisResult)
        assert len(result.items) == 2
        assert result.items[0].section == "headline"
        assert result.summary == "Foco no headline."

    def test_current_optional_null_is_fine(self) -> None:
        result = parse_analysis_json(json.dumps({"type": "analysis", "items": [_VALID_ITEM_2]}))
        assert isinstance(result, ParsedAnalysisResult)
        assert result.items[0].current is None

    def test_code_fence_is_stripped(self) -> None:
        raw = "```json\n" + json.dumps({"type": "analysis", "items": [_VALID_ITEM]}) + "\n```"
        assert isinstance(parse_analysis_json(raw), ParsedAnalysisResult)

    def test_missing_summary_falls_back_to_deterministic_prose(self) -> None:
        result = parse_analysis_json(json.dumps({"type": "analysis", "items": [_VALID_ITEM]}))
        assert isinstance(result, ParsedAnalysisResult)
        assert result.summary  # non-blank
        assert "headline" in result.summary

    def test_item_with_section_outside_whitelist_is_dropped(self) -> None:
        bad = {**_VALID_ITEM, "section": "salary"}
        result = parse_analysis_json(json.dumps({"type": "analysis", "items": [bad, _VALID_ITEM_2]}))
        assert isinstance(result, ParsedAnalysisResult)
        assert len(result.items) == 1
        assert result.items[0].section == "about"

    def test_item_with_invalid_priority_is_dropped(self) -> None:
        bad = {**_VALID_ITEM, "priority": "urgent"}
        result = parse_analysis_json(json.dumps({"type": "analysis", "items": [bad]}))
        assert result is None

    def test_analysis_with_zero_valid_items_is_none(self) -> None:
        assert parse_analysis_json(json.dumps({"type": "analysis", "items": [{"nope": 1}]})) is None

    def test_type_analysis_wins_even_when_reply_present_but_no_items(self) -> None:
        raw = json.dumps({"type": "analysis", "items": [], "reply": "uma pergunta"})
        assert parse_analysis_json(raw) is None


class TestParseQuestion:
    def test_clean_question_parses_reply(self) -> None:
        result = parse_analysis_json(json.dumps({"type": "question", "reply": "Qual é a sua área?"}))
        assert isinstance(result, ParsedAnalysisQuestion)
        assert result.reply == "Qual é a sua área?"

    def test_question_with_blank_reply_is_none(self) -> None:
        assert parse_analysis_json(json.dumps({"type": "question", "reply": "   "})) is None


class TestTypeInference:
    def test_missing_type_with_items_infers_analysis(self) -> None:
        assert isinstance(parse_analysis_json(json.dumps({"items": [_VALID_ITEM]})), ParsedAnalysisResult)

    def test_missing_type_with_reply_infers_question(self) -> None:
        assert isinstance(parse_analysis_json(json.dumps({"reply": "Qual o cargo-alvo?"})), ParsedAnalysisQuestion)

    def test_unknown_type_prefers_items_over_reply(self) -> None:
        raw = json.dumps({"type": "weird", "items": [_VALID_ITEM], "reply": "x"})
        assert isinstance(parse_analysis_json(raw), ParsedAnalysisResult)

    def test_missing_type_with_neither_is_none(self) -> None:
        assert parse_analysis_json(json.dumps({"foo": "bar"})) is None


class TestNeverRaises:
    def test_not_json_is_none(self) -> None:
        assert parse_analysis_json("not json at all") is None

    def test_json_list_is_none(self) -> None:
        assert parse_analysis_json(json.dumps(["analysis"])) is None

    def test_empty_string_is_none(self) -> None:
        assert parse_analysis_json("") is None
