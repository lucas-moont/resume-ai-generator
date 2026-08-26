"""Unit tests for ``app/services/llm/fit_json_parser.py`` (v7 ticket 08).

The contract in one line: a usable number, or ``None`` -- never an exception. ``None`` is not a
failure the user sees; it means the listing keeps the keyword pass's estimate, which is why the
parser can afford to reject an out-of-range answer instead of clamping it.
"""

from __future__ import annotations

import pytest

from app.services.llm.fit_json_parser import parse_fit_json


class TestTheHappyShape:
    def test_the_shape_the_prompt_asks_for(self):
        assert parse_fit_json('{"fit": 82}') == 82

    def test_the_boundaries_are_inside_the_range(self):
        assert parse_fit_json('{"fit": 0}') == 0
        assert parse_fit_json('{"fit": 100}') == 100

    def test_whitespace_and_newlines_around_the_json(self):
        assert parse_fit_json('\n\n  {"fit": 47}  \n') == 47


class TestTolerance:
    def test_a_code_fence_is_stripped(self):
        assert parse_fit_json('```json\n{"fit": 63}\n```') == 63

    def test_an_unlabelled_fence_too(self):
        assert parse_fit_json('```\n{"fit": 63}\n```') == 63

    def test_a_number_sent_as_a_string(self):
        assert parse_fit_json('{"fit": "82"}') == 82

    def test_a_percent_sign_the_model_could_not_resist(self):
        assert parse_fit_json('{"fit": "82%"}') == 82

    def test_a_float_is_rounded(self):
        assert parse_fit_json('{"fit": 82.4}') == 82
        assert parse_fit_json('{"fit": 82.6}') == 83

    def test_a_bare_number_as_the_whole_answer(self):
        # A model that read "output only the number" more literally than intended still gave a
        # usable answer.
        assert parse_fit_json("82") == 82

    @pytest.mark.parametrize("key", ["fit", "fit_score", "fitScore", "score"])
    def test_the_paraphrases_of_the_key_are_accepted(self, key):
        assert parse_fit_json('{"%s": 71}' % key) == 71

    def test_extra_keys_do_not_spoil_a_good_answer(self):
        # The prompt forbids a justification; a model that sends one anyway still answered.
        assert parse_fit_json('{"fit": 71, "reason": "strong Python overlap"}') == 71


class TestGarbageBecomesNone:
    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "I'd say this is a pretty good match for you!",
            "{",
            "[]",
            '{"other": 40}',
            '{"fit": null}',
            '{"fit": "not a number"}',
            '{"fit": ""}',
            '{"fit": [80]}',
            '{"fit": {"value": 80}}',
        ],
    )
    def test_unusable_output_is_none_never_an_exception(self, raw):
        assert parse_fit_json(raw) is None

    def test_a_non_string_input_is_none(self):
        assert parse_fit_json(None) is None  # type: ignore[arg-type]

    def test_a_boolean_is_not_a_number(self):
        # ``True`` is an ``int`` in Python; a Fit Score of 1 from ``{"fit": true}`` would be a
        # silent absurdity in the ranking.
        assert parse_fit_json('{"fit": true}') is None
        assert parse_fit_json('{"fit": false}') is None


class TestOutOfRangeIsGarbageNotClamped:
    @pytest.mark.parametrize("raw", ['{"fit": 850}', '{"fit": 101}', '{"fit": -5}'])
    def test_a_value_outside_0_100_is_rejected(self, raw):
        # Clamping 850 to 100 would promote a misunderstanding to the top of the user's ranked
        # list. ``None`` keeps the honest keyword estimate instead.
        assert parse_fit_json(raw) is None

    def test_a_float_that_rounds_back_into_range_is_accepted(self):
        assert parse_fit_json('{"fit": 100.4}') == 100

    def test_a_float_that_rounds_out_of_range_is_rejected(self):
        assert parse_fit_json('{"fit": 100.6}') is None
