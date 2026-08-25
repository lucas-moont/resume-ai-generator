"""The catalog of Job Boards, and the lookup from a board id to its adapter (v7 ticket 03).

Two things live here, and they are deliberately separate:

* ``BOARD_SPECS`` -- static METADATA for every board of v7: its id, the name shown next to a
  Listing Source link (which is what Remotive's and Remote OK's terms require of us), and the
  board's own minimum interval. This is a constant, known before any adapter exists, and it is
  what ``GET /api/jobs/boards`` serves and what the Search Profile validates against.
* ``BoardProviderRegistry`` -- a mapping from board id to a live ``JobBoardProvider``, built
  explicitly by whoever runs a Scan. Not a module-level mutable singleton on purpose: adapters
  self-registering into global state would leak between tests (and would make "which boards
  exist" depend on which modules happened to be imported), whereas an instance handed to the
  Scan engine lets a test wire three ``FakeJobBoard``s and nothing else.

Mirrors ``services/llm/provider_factory.py`` in role -- the one place that turns a name into
an adapter -- but not in shape: an LLM provider is constructed per call from a
``ProviderContext``, while a board adapter is stateless and long-lived.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, get_args

from app.domain.schemas import BoardId
from app.services.jobboards.base import JobBoardProvider

# Every board may be called once an hour unless it says otherwise. The user's scan interval is
# the other half of the decision: the engine uses ``max(user interval, board minimum)``.
DEFAULT_MIN_INTERVAL_HOURS = 1


class UnknownBoardError(LookupError):
    """A board id that is not in ``BOARD_SPECS`` (or has no registered adapter)."""


class DuplicateBoardError(ValueError):
    """Two adapters claiming the same board id in one registry."""


@dataclass(frozen=True)
class BoardSpec:
    """What is true about a board regardless of whether its adapter is loaded."""

    id: BoardId
    # Shown verbatim beside every Listing Source link -- attribution, not decoration.
    display_name: str
    # The board's OWN floor, in hours. Never lowered by an adapter.
    min_interval_hours: int = DEFAULT_MIN_INTERVAL_HOURS


# Declaration order is presentation order: the four JobSpy-backed general boards first (the
# ones a Brazilian tech search actually lives on), then the three remote-only niche boards.
BOARD_SPECS: tuple[BoardSpec, ...] = (
    BoardSpec("linkedin", "LinkedIn"),
    BoardSpec("indeed", "Indeed"),
    BoardSpec("glassdoor", "Glassdoor"),
    BoardSpec("google", "Google Jobs"),
    # Remotive's terms allow at most four calls a day; 6h is that limit expressed as an
    # interval, and it is the reason ``skipped`` exists as a Board Status at all.
    BoardSpec("remotive", "Remotive", min_interval_hours=6),
    BoardSpec("weworkremotely", "We Work Remotely"),
    BoardSpec("remoteok", "Remote OK"),
)

_SPECS_BY_ID: dict[str, BoardSpec] = {spec.id: spec for spec in BOARD_SPECS}


def known_board_ids() -> tuple[BoardId, ...]:
    """Every board id v7 knows, in presentation order."""
    return tuple(spec.id for spec in BOARD_SPECS)


def is_known_board(board_id: object) -> bool:
    return isinstance(board_id, str) and board_id in _SPECS_BY_ID


def board_spec(board_id: object) -> BoardSpec:
    """The spec for ``board_id``; raises ``UnknownBoardError`` for anything else."""
    if not isinstance(board_id, str) or board_id not in _SPECS_BY_ID:
        raise UnknownBoardError(
            f"unknown job board {board_id!r} (known: {', '.join(known_board_ids())})"
        )
    return _SPECS_BY_ID[board_id]


def min_interval_hours(board_id: object) -> int:
    """The board's own minimum interval between Scans, in hours."""
    return board_spec(board_id).min_interval_hours


def display_name(board_id: object) -> str:
    return board_spec(board_id).display_name


class BoardProviderRegistry:
    """The adapters available for this Scan, keyed by board id."""

    def __init__(self, providers: Iterable[JobBoardProvider] = ()) -> None:
        self._providers: dict[str, JobBoardProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: JobBoardProvider) -> "BoardProviderRegistry":
        """Add one adapter. Returns self, so a registry can be built in one expression.

        Two rejections, both of which would otherwise surface as a silently missing board
        halfway through a Scan:

        * an id with no ``BoardSpec`` -- nothing could enable it and no Board Status could
          report it;
        * an adapter whose ``min_interval_hours`` is BELOW its spec's. The spec is the
          authority (Remotive's is a terms-of-service floor, not a tuning knob); an adapter
          declaring a *stricter* interval is fine and is honoured as-is.
        """
        spec = board_spec(getattr(provider, "id", None))
        if spec.id in self._providers:
            raise DuplicateBoardError(f"job board {spec.id!r} already registered")
        declared = getattr(provider, "min_interval_hours", spec.min_interval_hours)
        if declared < spec.min_interval_hours:
            raise ValueError(
                f"job board {spec.id!r} declares min_interval_hours={declared}, below its "
                f"catalog minimum of {spec.min_interval_hours}"
            )
        self._providers[spec.id] = provider
        return self

    def get(self, board_id: object) -> JobBoardProvider:
        """The adapter for ``board_id``; raises ``UnknownBoardError`` when none is registered
        (including for a perfectly valid id whose adapter simply was not wired)."""
        spec = board_spec(board_id)
        try:
            return self._providers[spec.id]
        except KeyError:
            raise UnknownBoardError(f"no adapter registered for job board {spec.id!r}") from None

    def has(self, board_id: object) -> bool:
        return isinstance(board_id, str) and board_id in self._providers

    def ids(self) -> tuple[BoardId, ...]:
        """Registered board ids, in catalog order (not registration order) -- so a Scan's
        board list and the BoardStatusBar read the same way every run."""
        return tuple(spec.id for spec in BOARD_SPECS if spec.id in self._providers)

    def providers_for(self, board_ids: Iterable[object]) -> list[JobBoardProvider]:
        """The adapters for the boards the Search Profile has enabled, in catalog order,
        skipping ids with no adapter. Silent skipping is deliberate: a Search Profile saved
        while a board existed must not break the whole Scan after that board is retired."""
        wanted = {b for b in board_ids if isinstance(b, str)}
        return [self._providers[spec.id] for spec in BOARD_SPECS
                if spec.id in wanted and spec.id in self._providers]

    def __len__(self) -> int:
        return len(self._providers)

    def __contains__(self, board_id: object) -> bool:
        return self.has(board_id)


def _assert_catalog_covers_contract() -> None:
    """The catalog and the frozen ``BoardId`` Literal must name exactly the same boards --
    checked at import so widening one and forgetting the other fails immediately, in every
    test run, instead of as a 422 on a Search Profile save."""
    literal_ids = set(get_args(BoardId))
    catalog_ids = set(_SPECS_BY_ID)
    if literal_ids != catalog_ids:
        raise RuntimeError(
            "BOARD_SPECS and the BoardId contract disagree: "
            f"only in BoardId={sorted(literal_ids - catalog_ids)}, "
            f"only in BOARD_SPECS={sorted(catalog_ids - literal_ids)}"
        )


_assert_catalog_covers_contract()
