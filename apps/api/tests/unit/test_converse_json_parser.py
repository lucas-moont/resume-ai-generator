"""Unit tests for app/services/llm/converse_json_parser.py.

The conversation turn's LLM returns ``{"reply": "<markdown>"}``. Like the proposal-turn parser,
this one is tolerant by construction: it NEVER raises, and any shape it cannot use collapses to
``None`` so the caller falls back to a canned, locale-aware reply -- never a crash, never an
error frame.
"""

from __future__ import annotations

from app.services.llm.converse_json_parser import parse_converse_json


class TestParseConverseJson:
    def test_a_valid_reply_is_returned(self) -> None:
        assert parse_converse_json('{"reply": "Aqui está a resposta."}') == "Aqui está a resposta."

    def test_a_code_fenced_reply_is_unwrapped(self) -> None:
        raw = '```json\n{"reply": "Resposta em bloco."}\n```'
        assert parse_converse_json(raw) == "Resposta em bloco."

    def test_a_reply_is_stripped(self) -> None:
        assert parse_converse_json('{"reply": "  espaços  "}') == "espaços"

    def test_a_blank_reply_is_none(self) -> None:
        assert parse_converse_json('{"reply": "   "}') is None

    def test_a_missing_reply_is_none(self) -> None:
        assert parse_converse_json('{"something_else": "x"}') is None

    def test_a_non_string_reply_is_none(self) -> None:
        assert parse_converse_json('{"reply": 42}') is None

    def test_invalid_json_is_none(self) -> None:
        assert parse_converse_json("not json at all") is None

    def test_a_non_object_top_level_is_none(self) -> None:
        assert parse_converse_json('["reply"]') is None
