"""The real (network-reaching) Job Board adapters, as a list (v7 ticket 04).

A mounting point, not a registry: ``BoardProviderRegistry`` is built explicitly by whoever runs
a Scan (ticket 03's decision -- no module-level mutable singleton), and this module only says
which adapters exist for the JobSpy-backed half of v7.

Kept separate from ``provider_registry`` for the reason that module states about metadata: the
CATALOG must be importable without any adapter, since ``GET /api/jobs/boards`` and the Search
Profile's validation need it before a scrape is possible. Kept separate from the adapter module
too, so that "which boards are wired for production" is one short list to read rather than a
constructor call buried in a service.

The feed-backed boards (Remotive, We Work Remotely, Remote OK) get their own equivalent in
ticket 05; ticket 07 composes both into the registry a Scan receives. Nothing here is imported
by tests of the Scan engine -- those wire ``FakeJobBoard``s.
"""

from __future__ import annotations

from app.services.jobboards.base import JobBoardProvider
from app.services.jobboards.jobspy_board import (
    glassdoor_board,
    google_board,
    indeed_board,
    linkedin_board,
)


def jobspy_providers(**kwargs: object) -> list[JobBoardProvider]:
    """The four JobSpy-backed boards, in catalog order.

    Constructing them is free and reaches nothing: ``JobSpyBoard`` imports ``jobspy`` lazily, at
    the first ``search``. So this may be called at startup even in an environment where
    ``python-jobspy`` did not install -- those boards then report Board Status ``error`` with an
    actionable message and the rest of the Scan is unaffected.

    ``kwargs`` are passed to every board (``default_country``, ``max_queries``, ...), which is
    how a caller changes the default ``country_indeed`` for the whole set at once.
    """
    return [
        linkedin_board(**kwargs),
        indeed_board(**kwargs),
        glassdoor_board(**kwargs),
        google_board(**kwargs),
    ]


__all__ = ["jobspy_providers"]
