"""The three feed-backed Job Boards as one list (v7 ticket 05).

``provider_registry`` deliberately has no module-level list of live adapters (ticket 03
decision 3): whoever runs a Scan builds a ``BoardProviderRegistry`` explicitly. This function
is this ticket's contribution to that call -- the one place that knows Remotive, We Work
Remotely and Remote OK are constructed the same way and belong together:

    registry = BoardProviderRegistry(feed_providers())

Kept apart from ticket 04's JobSpy-backed providers because the two halves fail differently: a
feed adapter needs nothing but ``httpx``, so it can always be constructed, while a JobSpy one
depends on an optional third-party package. A single factory would make an import error in one
half silently cost the other three boards.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import httpx

from app.services.jobboards.base import JobBoardProvider
from app.services.jobboards.feed_support import DEFAULT_TIMEOUT_SECONDS, utc_now
from app.services.jobboards.remoteok_board import RemoteOkBoard
from app.services.jobboards.remotive_board import RemotiveBoard
from app.services.jobboards.weworkremotely_board import WeWorkRemotelyBoard


def feed_providers(
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    clock: Callable[[], datetime] = utc_now,
) -> tuple[JobBoardProvider, ...]:
    """Remotive, We Work Remotely and Remote OK, in catalog order.

    ``transport`` and ``clock`` exist for the same reason they exist on each adapter: an
    integration test wires one ``httpx.MockTransport`` for all three instead of reaching the
    real boards. Production passes neither.
    """
    return (
        RemotiveBoard(transport=transport, timeout=timeout, clock=clock),
        WeWorkRemotelyBoard(transport=transport, timeout=timeout, clock=clock),
        RemoteOkBoard(transport=transport, timeout=timeout, clock=clock),
    )
