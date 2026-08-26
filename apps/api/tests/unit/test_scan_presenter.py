"""Unit tests for ``services/jobs/scan_presenter.py`` (v7 ticket 09).

No database and no HTTP: a ``JobScan`` is a plain SQLModel object, so the two conversions this
presenter owns -- the board-status map becoming an ordered list, and ``nextScanAt`` being
computed rather than stored -- are testable as pure functions of one row.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.db.tables import JobScan
from app.services.jobs.scan_presenter import board_statuses_out, next_scan_at, to_scan_out

STARTED = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)
FINISHED = datetime(2026, 8, 25, 9, 2, 31, tzinfo=timezone.utc)


def scan(**overrides) -> JobScan:
    values = {
        "id": 6,
        "started_at": STARTED,
        "finished_at": FINISHED,
        "trigger": "scheduled",
        "status": "done",
        "board_statuses": "{}",
        "listings_found": 20,
        "listings_scored": 14,
    }
    values.update(overrides)
    statuses = values["board_statuses"]
    if isinstance(statuses, dict):
        values["board_statuses"] = json.dumps(statuses)
    return JobScan(**values)


def status_entry(status: str = "ok", message: str | None = None, count: int = 0) -> dict:
    return {"status": status, "message": message, "count": count}


class TestBoardStatuses:
    def test_the_map_becomes_a_list_in_catalog_order(self):
        """The DB stores a map (order-free, keyed, idempotent per board); the wire needs a
        stable order so the BoardStatusBar does not reshuffle between polls."""
        row = scan(
            board_statuses={
                "remoteok": status_entry("ok", count=3),
                "linkedin": status_entry("blocked", "LinkedIn recusou a busca (429).", 0),
                "indeed": status_entry("ok", count=14),
            }
        )

        assert [b.board for b in board_statuses_out(row)] == ["linkedin", "indeed", "remoteok"]

    def test_every_field_of_one_board_survives(self):
        row = scan(board_statuses={"linkedin": status_entry("blocked", "recusou (429)", 2)})

        [board] = board_statuses_out(row)
        assert board.board == "linkedin"
        assert board.status == "blocked"
        assert board.message == "recusou (429)"
        assert board.count == 2

    def test_a_scan_that_called_nothing_reports_no_boards(self):
        assert board_statuses_out(scan(board_statuses="{}")) == []

    def test_a_board_the_catalog_no_longer_knows_is_dropped(self):
        """The column holds plain strings so an old Scan survives a board being retired.
        Validating it against ``BoardId`` here would turn that Scan's history into a 500."""
        row = scan(
            board_statuses={"myspace": status_entry("ok", count=9), "indeed": status_entry("ok")}
        )

        assert [b.board for b in board_statuses_out(row)] == ["indeed"]

    def test_a_status_outside_the_contract_is_reported_as_error_with_its_message(self):
        """Nothing this app writes can produce one -- but dropping the board would silently
        cost the user a flag they are owed, and raising would cost them the whole Scan."""
        row = scan(board_statuses={"indeed": status_entry("weird", "something happened", 1)})

        [board] = board_statuses_out(row)
        assert board.status == "error"
        assert board.message == "something happened"
        assert board.count == 1

    @pytest.mark.parametrize(
        "entry",
        [
            {"status": "ok"},
            {"status": "ok", "message": 42, "count": "many"},
            {"status": "ok", "count": True},
        ],
        ids=["missing fields", "wrong types", "a bool is not a count"],
    )
    def test_a_malformed_entry_degrades_field_by_field(self, entry):
        row = scan(board_statuses={"indeed": entry})

        [board] = board_statuses_out(row)
        assert board.status == "ok"
        assert board.message is None
        assert board.count == 0

    def test_an_entry_that_is_not_an_object_is_skipped(self):
        row = scan(board_statuses={"indeed": "ok", "linkedin": status_entry("ok", count=1)})

        assert [b.board for b in board_statuses_out(row)] == ["linkedin"]


class TestNextScanAt:
    def test_it_is_the_interval_after_this_scan_finished(self):
        assert next_scan_at(scan(), 3) == FINISHED + timedelta(hours=3)

    def test_scheduling_off_means_nobody_can_say_when(self):
        """``None`` is "off" in the Search Profile. Immediate Scans still work, but a "próxima
        varredura" label would be inventing a schedule the user switched off."""
        assert next_scan_at(scan(), None) is None

    def test_a_running_scan_has_no_next_one_yet(self):
        assert next_scan_at(scan(status="running", finished_at=None), 6) is None

    def test_a_finished_scan_with_no_timestamp_yields_nothing(self):
        """A row a crashed process left behind: ``done`` but never stamped."""
        assert next_scan_at(scan(finished_at=None), 6) is None

    def test_a_naive_timestamp_out_of_sqlite_is_read_as_utc(self):
        """SQLite hands datetimes back without a tzinfo; ``domain.recency.as_utc`` is what keeps
        the arithmetic from producing a naive result the wire cannot compare."""
        row = scan(finished_at=FINISHED.replace(tzinfo=None))

        result = next_scan_at(row, 1)
        assert result == FINISHED + timedelta(hours=1)
        assert result.tzinfo is not None


class TestToScanOut:
    def test_every_field_of_a_finished_scan(self):
        row = scan(board_statuses={"indeed": status_entry("ok", count=14)})

        out = to_scan_out(row, interval_hours=6)

        assert out.id == 6
        assert out.startedAt == STARTED
        assert out.finishedAt == FINISHED
        assert out.trigger == "scheduled"
        assert out.status == "done"
        assert out.listingsFound == 20
        assert out.listingsScored == 14
        assert [b.board for b in out.boards] == ["indeed"]
        assert out.nextScanAt == FINISHED + timedelta(hours=6)

    def test_a_running_scan_reports_no_finish_and_no_next(self):
        row = scan(
            status="running",
            trigger="immediate",
            finished_at=None,
            listings_found=0,
            listings_scored=0,
            board_statuses={"indeed": status_entry("ok", count=9)},
        )

        out = to_scan_out(row, interval_hours=6)

        assert out.status == "running"
        assert out.trigger == "immediate"
        assert out.finishedAt is None
        assert out.nextScanAt is None
        # ``boards`` fills in as each board answers -- that is what makes polling worth doing.
        assert [b.board for b in out.boards] == ["indeed"]

    def test_the_interval_defaults_to_off(self):
        """Callers that have no Search Profile to read must not have to pass anything for the
        answer to be honest."""
        assert to_scan_out(scan()).nextScanAt is None
