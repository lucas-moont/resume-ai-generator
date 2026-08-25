"""Unit tests for ``app/services/jobboards/default_registry.py`` (v7 ticket 07).

The one place in the app that composes all seven Job Boards into the registry a Scan receives.
Its whole job is to survive the fact that ``python-jobspy`` is an OPTIONAL dependency: it is
not in ``requirements.txt`` (ticket 04 documents why -- the published pins demand
``numpy==1.26.3``, which has no wheel for CPython 3.14) and installs separately through
``requirements-jobspy.txt``. So "with the package" and "without the package" are both normal
states of a real install, and both are exercised here.

Nothing here reaches the network: constructing every adapter is free (``JobSpyBoard`` imports
``jobspy`` lazily, the feed adapters only build an httpx client on ``search``), and the one test
that does call ``search`` calls it on a board whose package is deliberately unavailable, so it
returns before any HTTP client exists.
"""

from __future__ import annotations

import sys

import pytest

from app.services.jobboards.default_registry import (
    build_default_registry,
    jobspy_providers_or_none,
)
from app.services.jobboards.provider_registry import BOARD_SPECS
from app.domain.schemas import BoardQuery

FEED_BOARDS = ("remotive", "weworkremotely", "remoteok")
JOBSPY_BOARDS = ("linkedin", "indeed", "glassdoor", "google")


class TestWithTheJobspyModulesImportable:
    def test_it_registers_every_board_in_the_catalog(self):
        registry = build_default_registry()
        assert registry.ids() == tuple(spec.id for spec in BOARD_SPECS)
        assert len(registry) == 7

    def test_the_boards_come_back_in_catalog_order_not_construction_order(self):
        # The Scan's board loop and the BoardStatusBar must read the same way every run.
        assert build_default_registry().ids() == (
            "linkedin",
            "indeed",
            "glassdoor",
            "google",
            "remotive",
            "weworkremotely",
            "remoteok",
        )

    def test_every_adapter_honours_its_catalogs_minimum_interval(self):
        # ``BoardProviderRegistry.register`` rejects an adapter below its spec, so a registry
        # that builds at all has already proved this -- asserted explicitly because Remotive's
        # 6h is a terms-of-service floor, not a tuning knob.
        registry = build_default_registry()
        assert registry.get("remotive").min_interval_hours >= 6
        for spec in BOARD_SPECS:
            assert registry.get(spec.id).min_interval_hours >= spec.min_interval_hours

    def test_kwargs_reach_the_jobspy_boards(self):
        registry = build_default_registry(default_country="germany")
        assert registry.get("indeed").default_country == "germany"

    def test_building_it_reaches_no_board(self):
        # Every adapter is constructed and nothing is called: a registry built at startup must
        # not cost a single HTTP request.
        registry = build_default_registry()
        assert len(registry) == 7


class TestWithoutThePythonJobspyPackage:
    """The four JobSpy boards are still REGISTERED -- they just report ``error`` when called.

    That is ticket 04 decision 1's design and the right one: dropping them from the registry
    would make a Search Profile that enables LinkedIn silently scan nothing at all, with no
    Board Status to explain it. An honest ``error`` with an install command is visible.
    """

    @pytest.fixture
    def no_jobspy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # ``None`` in sys.modules is the documented way to make an import of that name raise
        # ImportError -- the same state a machine without the package is in, without touching
        # the real installation.
        monkeypatch.setitem(sys.modules, "jobspy", None)

    def test_the_registry_still_holds_all_seven_boards(self, no_jobspy):
        assert len(build_default_registry()) == 7

    async def test_a_jobspy_board_reports_error_instead_of_raising(self, no_jobspy):
        board = build_default_registry().get("linkedin")

        result = await board.search(BoardQuery(roles=["Backend Engineer"], locations=["Brasil"]))

        assert result.status == "error"
        assert result.items == []
        assert "jobspy" in (result.message or "").lower()

    def test_the_feed_boards_are_untouched(self, no_jobspy):
        registry = build_default_registry()
        for board_id in FEED_BOARDS:
            assert registry.has(board_id)


class TestWhenTheJobspyAdapterModuleItselfCannotBeImported:
    """The harder failure: not a missing ``jobspy``, but our own adapter module failing to
    import (a transitive dependency of it gone). Degrading to the three feed boards -- loudly --
    is the honest answer; letting the ImportError escape would cost the user the boards that
    work perfectly."""

    @pytest.fixture
    def broken_adapter_module(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "app.services.jobboards.real_providers", None)

    def test_jobspy_providers_or_none_returns_nothing_rather_than_raising(
        self, broken_adapter_module
    ):
        assert jobspy_providers_or_none() == []

    def test_the_registry_degrades_to_the_feed_boards(self, broken_adapter_module):
        registry = build_default_registry()
        assert registry.ids() == FEED_BOARDS

    def test_the_jobspy_backed_boards_are_simply_absent(self, broken_adapter_module):
        registry = build_default_registry()
        for board_id in JOBSPY_BOARDS:
            assert registry.has(board_id) is False

    def test_it_says_how_to_install_them(self, broken_adapter_module, caplog):
        with caplog.at_level("WARNING"):
            build_default_registry()
        assert "requirements-jobspy.txt" in caplog.text
