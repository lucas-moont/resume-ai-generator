"""Unit tests for the ``JOB_BOARDS_FAKE`` registry seam (v7 ticket 15).

The flag exists so the opt-in ``@real`` Playwright variant can run a REAL Scan -- real router,
real engine, real LLM Fit pass -- without a single request leaving for LinkedIn. That makes
these tests the guard on an invariant CLAUDE.md states twice, so they check both directions:
the fakes appear when the flag is set, and nothing changes when it is not.
"""

from __future__ import annotations

import pytest

from app.domain.chat_intent import looks_like_job_description
from app.domain.schemas import BoardQuery, RawPosting
from app.services.jobboards.default_registry import build_default_registry
from app.services.jobboards.fake_providers import StaticJobBoard, fake_providers
from app.services.jobboards.provider_registry import BOARD_SPECS

FAKE_BOARDS = ("linkedin", "indeed", "remoteok")


class TestTheFlag:
    def test_unset_it_builds_the_real_seven_board_registry(self):
        # The autouse `_no_fake_job_boards` fixture guarantees the var is absent here.
        assert build_default_registry().ids() == tuple(spec.id for spec in BOARD_SPECS)

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_set_it_builds_only_the_fakes(self, monkeypatch: pytest.MonkeyPatch, value: str):
        monkeypatch.setenv("JOB_BOARDS_FAKE", value)
        assert build_default_registry().ids() == FAKE_BOARDS

    @pytest.mark.parametrize("value", ["0", "false", "off", "no", "", "  "])
    def test_anything_falsy_leaves_the_real_registry_alone(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ):
        # A half-set flag must fail SAFE in the direction of the documented default, not
        # silently swap the boards out from under a real install.
        monkeypatch.setenv("JOB_BOARDS_FAKE", value)
        assert len(build_default_registry()) == 7

    def test_kwargs_meant_for_the_jobspy_boards_are_tolerated(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # `scheduler.start` and the router both call this the same way regardless of the flag.
        monkeypatch.setenv("JOB_BOARDS_FAKE", "1")
        assert build_default_registry(default_country="brazil").ids() == FAKE_BOARDS


class TestStaticJobBoard:
    async def test_it_answers_from_its_fixed_list_and_records_the_query(self):
        posting = RawPosting(title="Backend Engineer", company="Acme", url="https://a.invalid/1")
        board = StaticJobBoard("indeed", [posting])

        result = await board.search(BoardQuery(roles=["Backend Engineer"]))

        assert result.status == "ok"
        assert [item.title for item in result.items] == ["Backend Engineer"]
        assert [q.roles for q in board.queries] == [["Backend Engineer"]]

    async def test_a_second_call_gets_its_own_posting_objects(self):
        board = StaticJobBoard("indeed", [RawPosting(title="A", company="B", url="https://c.invalid")])

        first = await board.search(BoardQuery())
        second = await board.search(BoardQuery())

        assert first.items[0] is not second.items[0]

    async def test_a_blocked_board_reports_instead_of_raising(self):
        board = StaticJobBoard("linkedin", status="blocked", message="rate limited")

        result = await board.search(BoardQuery())

        assert (result.status, result.message, result.items) == ("blocked", "rate limited", [])

    def test_an_unknown_board_id_fails_at_construction(self):
        with pytest.raises(LookupError):
            StaticJobBoard("monster")


class TestTheSamplePostings:
    def test_one_board_blocks_so_the_partial_scan_path_runs_every_time(self):
        blocked = [board for board in fake_providers() if board.id == "linkedin"]
        assert len(blocked) == 1

    async def test_every_posting_is_long_enough_for_a_one_click_resume(self):
        # The whole point of the `@real` run is generating a resume from the top listing; a
        # fixture that trips the 422 `description_too_short` gate would test the refusal.
        for board in fake_providers():
            for posting in (await board.search(BoardQuery())).items:
                assert looks_like_job_description(posting.description), posting.title

    async def test_no_posting_url_points_at_a_resolvable_host(self):
        # `.invalid` is reserved (RFC 2606): a stray click from a live-QA session cannot land
        # on somebody's real job ad.
        for board in fake_providers():
            for posting in (await board.search(BoardQuery())).items:
                assert "example.invalid" in posting.url
