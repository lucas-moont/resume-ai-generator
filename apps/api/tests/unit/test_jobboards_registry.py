"""Unit tests for the Job Board seam (v7 ticket 03):
``app/services/jobboards/provider_registry.py`` and ``tests.fakes.FakeJobBoard``.

No adapter exists yet, so what is under test is the catalog (which boards v7 knows, what they
are called, how often each may be called) and the wiring rules a Scan depends on. Nothing here
touches the network -- and the FakeJobBoard cases exist to make sure the double the whole v7
test suite will lean on actually fails loudly when a Scan calls a board it did not script.
"""

from __future__ import annotations

import dataclasses
import inspect
from typing import get_args

import pytest

from app.domain.schemas import BoardId, BoardQuery, BoardResult, RawPosting
from app.services.jobboards.provider_registry import (
    BOARD_SPECS,
    BoardProviderRegistry,
    BoardSpec,
    DuplicateBoardError,
    UnknownBoardError,
    board_spec,
    display_name,
    is_known_board,
    known_board_ids,
    min_interval_hours,
)
from tests.fakes import FakeJobBoard


class _StubBoard:
    """A minimally shaped provider -- lets the registry's rejection paths be tested with ids
    FakeJobBoard refuses to be constructed with."""

    def __init__(self, board_id: str, min_interval: int = 1) -> None:
        self.id = board_id
        self.display_name = "Stub"
        self.min_interval_hours = min_interval

    async def search(self, query: BoardQuery) -> BoardResult:
        return BoardResult()


class TestCatalog:
    def test_the_seven_boards_of_v7_in_presentation_order(self) -> None:
        assert known_board_ids() == (
            "linkedin",
            "indeed",
            "glassdoor",
            "google",
            "remotive",
            "weworkremotely",
            "remoteok",
        )

    def test_catalog_and_the_frozen_contract_name_the_same_boards(self) -> None:
        # provider_registry asserts this at import too; here it is as a readable failure.
        assert set(known_board_ids()) == set(get_args(BoardId))

    def test_every_board_has_a_display_name_for_attribution(self) -> None:
        # Remotive's and Remote OK's terms require naming the board next to its link.
        assert all(spec.display_name.strip() for spec in BOARD_SPECS)
        assert display_name("google") == "Google Jobs"
        assert display_name("weworkremotely") == "We Work Remotely"

    def test_remotive_is_the_only_board_with_a_longer_minimum(self) -> None:
        # Its terms cap us at four calls a day.
        assert min_interval_hours("remotive") == 6
        assert [s.id for s in BOARD_SPECS if s.min_interval_hours != 1] == ["remotive"]

    def test_unknown_board_is_a_lookup_error_naming_the_known_ones(self) -> None:
        with pytest.raises(UnknownBoardError) as exc:
            board_spec("wellfound")
        assert "linkedin" in str(exc.value)

    @pytest.mark.parametrize("value", [None, 1, "", "LinkedIn"])
    def test_non_ids_are_rejected_not_coerced(self, value: object) -> None:
        assert is_known_board(value) is False
        with pytest.raises(UnknownBoardError):
            board_spec(value)

    def test_specs_are_immutable(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            BOARD_SPECS[0].min_interval_hours = 99  # type: ignore[misc]

    def test_default_minimum_is_one_hour(self) -> None:
        assert BoardSpec("indeed", "Indeed").min_interval_hours == 1


class TestBoardProviderRegistry:
    def test_registers_and_resolves(self) -> None:
        board = FakeJobBoard("indeed")
        registry = BoardProviderRegistry([board])
        assert registry.get("indeed") is board
        assert "indeed" in registry
        assert len(registry) == 1

    def test_ids_follow_catalog_order_not_registration_order(self) -> None:
        registry = BoardProviderRegistry([FakeJobBoard("remoteok"), FakeJobBoard("linkedin")])
        assert registry.ids() == ("linkedin", "remoteok")

    def test_providers_for_filters_and_orders_the_enabled_boards(self) -> None:
        linkedin, indeed = FakeJobBoard("linkedin"), FakeJobBoard("indeed")
        registry = BoardProviderRegistry([indeed, linkedin])
        assert registry.providers_for(["indeed", "linkedin"]) == [linkedin, indeed]
        assert registry.providers_for(["indeed"]) == [indeed]

    def test_providers_for_skips_a_board_with_no_adapter(self) -> None:
        # A Search Profile saved while a board existed must not break the whole Scan.
        registry = BoardProviderRegistry([FakeJobBoard("indeed")])
        assert registry.providers_for(["indeed", "glassdoor"]) == [registry.get("indeed")]

    def test_get_on_a_valid_but_unwired_board_raises(self) -> None:
        registry = BoardProviderRegistry()
        assert registry.has("glassdoor") is False
        with pytest.raises(UnknownBoardError):
            registry.get("glassdoor")

    def test_rejects_an_adapter_claiming_an_unknown_board(self) -> None:
        with pytest.raises(UnknownBoardError):
            BoardProviderRegistry([_StubBoard("wellfound")])

    def test_rejects_two_adapters_for_one_board(self) -> None:
        registry = BoardProviderRegistry([FakeJobBoard("indeed")])
        with pytest.raises(DuplicateBoardError):
            registry.register(FakeJobBoard("indeed"))

    def test_rejects_an_adapter_that_undercuts_its_boards_minimum(self) -> None:
        # Remotive's 6h is a terms-of-service floor, not a tuning knob.
        with pytest.raises(ValueError, match="below its catalog minimum"):
            BoardProviderRegistry([_StubBoard("remotive", min_interval=1)])

    def test_accepts_an_adapter_that_is_stricter_than_its_board(self) -> None:
        board = FakeJobBoard("indeed", min_interval_hours=3)
        assert BoardProviderRegistry([board]).get("indeed") is board


class TestFakeJobBoard:
    def test_has_the_shape_of_a_job_board_provider(self) -> None:
        board = FakeJobBoard("remotive")
        assert board.id == "remotive"
        assert board.display_name == "Remotive"
        # The double inherits the catalog's minimum, so a scheduling test reads the real number.
        assert board.min_interval_hours == 6
        assert inspect.iscoroutinefunction(board.search)

    def test_construction_rejects_an_unknown_board_id(self) -> None:
        with pytest.raises(UnknownBoardError):
            FakeJobBoard("wellfound")

    async def test_queue_ok_returns_the_scripted_postings(self) -> None:
        board = FakeJobBoard("indeed").queue_ok(
            {"title": "Backend Engineer", "company": "Acme", "url": "https://x/1"},
            RawPosting(title="Data Engineer", company="Globex", url="https://x/2"),
        )
        result = await board.search(BoardQuery(roles=["backend"]))
        assert result.status == "ok"
        assert [p.company for p in result.items] == ["Acme", "Globex"]

    async def test_records_the_query_it_was_asked(self) -> None:
        board = FakeJobBoard("indeed").queue_ok()
        await board.search(BoardQuery(roles=["dev"], hours_old=12))
        assert board.call_count == 1
        assert board.queries[0].roles == ["dev"]
        assert board.queries[0].hours_old == 12

    async def test_queue_blocked_and_queue_error_report_instead_of_raising(self) -> None:
        board = FakeJobBoard("linkedin").queue_blocked("429 from LinkedIn").queue_error("timeout")
        blocked = await board.search(BoardQuery())
        errored = await board.search(BoardQuery())
        assert (blocked.status, blocked.message) == ("blocked", "429 from LinkedIn")
        assert (errored.status, errored.message) == ("error", "timeout")
        assert blocked.items == []

    async def test_a_queued_exception_is_raised(self) -> None:
        # The Scan engine's "an adapter that raises still only fails its own board" path.
        board = FakeJobBoard("indeed").queue(RuntimeError("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            await board.search(BoardQuery())

    async def test_a_queued_list_of_postings_becomes_an_ok_result(self) -> None:
        board = FakeJobBoard("indeed").queue([RawPosting(title="Dev", company="Acme", url="u")])
        result = await board.search(BoardQuery())
        assert result.status == "ok" and len(result.items) == 1

    async def test_an_unscripted_call_fails_loudly(self) -> None:
        # An empty result would let a Scan that calls a board twice pass its test while
        # doubling the real traffic min_interval_hours exists to limit.
        board = FakeJobBoard("indeed").queue_ok()
        await board.search(BoardQuery())
        with pytest.raises(AssertionError, match="unscripted call #2"):
            await board.search(BoardQuery())

    async def test_results_are_consumed_in_order(self) -> None:
        board = FakeJobBoard("indeed").queue_ok(
            RawPosting(title="First", company="Acme", url="u1")
        ).queue_blocked()
        first = await board.search(BoardQuery())
        second = await board.search(BoardQuery())
        assert first.items[0].title == "First"
        assert second.status == "blocked"


class TestFakeBoardFixture:
    def test_factory_builds_independent_boards(self, make_fake_board) -> None:
        a = make_fake_board("linkedin")
        b = make_fake_board("indeed", min_interval_hours=2)
        assert (a.id, b.id) == ("linkedin", "indeed")
        assert b.min_interval_hours == 2
        assert a is not b
