"""The ``BoardProviderRegistry`` production runs with (v7 ticket 07).

Tickets 04 and 05 each contributed a factory for their half of v7 -- ``jobspy_providers()`` for
LinkedIn/Indeed/Glassdoor/Google, ``feed_providers()`` for Remotive/We Work Remotely/Remote OK
-- and deliberately did NOT compose them: the registry is not a module-level mutable singleton
(ticket 03 decision 3), it is built by whoever runs a Scan. This module is that composition,
and the only place in the app where "all seven boards" is written down.

It exists as its own module rather than inside the Scan engine so a test of the engine can keep
importing nothing but ``FakeJobBoard``s, and so the ONE place that can touch the network is one
short function to read.
"""

from __future__ import annotations

import logging

from app.services.jobboards.base import JobBoardProvider
from app.services.jobboards.feed_providers import feed_providers
from app.services.jobboards.provider_registry import BoardProviderRegistry

logger = logging.getLogger(__name__)


def jobspy_providers_or_none(**kwargs: object) -> list[JobBoardProvider]:
    """The four JobSpy-backed boards, or an empty list if the package is not importable.

    ``python-jobspy`` is the one optional dependency of this app, and it genuinely does not
    install on every interpreter (ticket 04 documents why: the published pins demand
    ``numpy==1.26.3``, which has no wheel for CPython 3.14). ``JobSpyBoard`` already imports
    ``jobspy`` lazily so constructing it is safe -- but the ADAPTER MODULE itself pulls in the
    stack around it, and an ImportError there would otherwise cost the user the three boards
    that work perfectly. Degrading to feeds only, loudly, is the honest failure.
    """
    try:
        from app.services.jobboards.real_providers import jobspy_providers
    except ImportError as e:  # pragma: no cover - exercised by monkeypatching the import
        logger.warning(
            "job boards: the JobSpy-backed boards are unavailable (%s) — scanning the feed "
            "boards only. Install them with: pip install --no-deps -r requirements-jobspy.txt",
            e,
        )
        return []
    return list(jobspy_providers(**kwargs))


def build_default_registry(**kwargs: object) -> BoardProviderRegistry:
    """Every board this build can reach, in catalog order.

    ``kwargs`` reach the JobSpy boards only (``default_country``, ``max_queries``, ...): the
    feed adapters' knobs are network seams (``transport``, ``clock``) that production never
    passes and that a test injects by constructing ``feed_providers()`` itself.
    """
    providers: list[JobBoardProvider] = jobspy_providers_or_none(**kwargs)
    providers.extend(feed_providers())
    registry = BoardProviderRegistry(providers)
    logger.info("job boards registered: %s", ",".join(registry.ids()) or "-")
    return registry


__all__ = ["build_default_registry", "jobspy_providers_or_none"]
