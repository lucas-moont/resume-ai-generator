"""The Job Board adapter seam (v7 ticket 03) -- mirrors ``services/llm/providers/base.py``.

One Protocol, no implementation. Every board of v7 (LinkedIn, Indeed, Glassdoor and Google
Jobs through JobSpy; Remotive, We Work Remotely and Remote OK through their own adapters)
answers the same three questions -- who am I, how often may I be called, what did this query
find -- so the Scan engine never learns a board's name and tests never reach a real one
(``tests.fakes.FakeJobBoard`` satisfies this Protocol and nothing else does, by default).

The request and response types are NOT defined here: ``BoardQuery``, ``RawPosting`` and
``BoardResult`` are the frozen contract of ticket 01 and live in ``app/domain/schemas.py``
with the rest of it. This module only names the operation.
"""

from __future__ import annotations

from typing import Protocol

from app.domain.schemas import BoardId, BoardQuery, BoardResult


class JobBoardProvider(Protocol):
    """One external source of postings.

    ``id`` is a ``BoardId`` rather than a bare ``str`` (the spec's sketch wrote ``str``): the
    same closed Literal is persisted in ``search_profile.boards`` and ``listing_sources.board``
    and is the key of ``provider_registry.BOARD_SPECS``, so an adapter that could name
    something else would be a board no Search Profile can enable and no Board Status can
    report.

    ``min_interval_hours`` is the board's OWN floor -- Remotive's terms cap us at four calls a
    day, hence 6 -- distinct from the user's scan interval. The Scan engine sleeps on
    ``max(user interval, this)`` and marks the board ``skipped`` in between; the authority for
    the value is ``provider_registry``, and an adapter may only raise it (see
    ``BoardProviderRegistry.register``).
    """

    id: BoardId
    display_name: str
    min_interval_hours: int

    async def search(self, query: BoardQuery) -> BoardResult:
        """Run one query against this board.

        Contract, and the reason a Scan is *partial* rather than failed when a board misbehaves
        (CONTEXT.md: Scan): an adapter REPORTS trouble instead of raising it. A refusal (429, a
        challenge page, a login wall) returns ``status="blocked"``; a breakage (timeout,
        unparseable payload) returns ``status="error"``; both carry a ``message`` the
        BoardStatusBar shows verbatim, so it must never be a raw exception repr or a URL with
        credentials. An exception that escapes anyway is caught by the engine and recorded as
        ``error`` for this board alone -- the other boards' results still stand.
        """
        ...
