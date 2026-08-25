"""Test doubles for the LLM boundary (``app.services.llm_client.chat_json``) and, as of v7,
for the Job Board boundary (``app.services.jobboards.base.JobBoardProvider``).

As of B3, every LLM call in the app (main.py's endpoints pre-B4, now generation_service.py /
refine_service.py / extraction_service.py) calls ``llm_client.chat_json(...)``
module-qualified rather than importing the bare name, so a single monkeypatch on
``app.services.llm_client.chat_json`` intercepts all of them (see
``tests.conftest.fake_llm``).
"""

from __future__ import annotations

from app.domain.schemas import BoardQuery, BoardResult, RawPosting
from app.services.jobboards.provider_registry import board_spec


class FakeLlm:
    """A scripted, queue-based replacement for ``chat_json``.

    Some endpoints (``/api/generate`` and its stream) can call the LLM more than once in a
    single request — a first pass to draft the resume, and a second "quality guard" pass
    when ``app.domain.quality.quality_issues`` finds something to fix. Queue one response per
    expected call, in order; queuing an exception instance makes that call raise instead of
    returning.
    """

    def __init__(self, responses: list[object] | None = None) -> None:
        self._responses: list[object] = list(responses or [])
        self.calls: list[dict[str, object]] = []

    def queue(self, *responses: object) -> "FakeLlm":
        self._responses.extend(responses)
        return self

    @property
    def call_count(self) -> int:
        return len(self.calls)

    async def __call__(self, system: str, user: str, model: str | None = None) -> str:
        self.calls.append({"system": system, "user": user, "model": model})
        if not self._responses:
            raise AssertionError(
                f"FakeLlm received unscripted call #{len(self.calls)} (model={model!r}) — "
                "queue another response before making this request."
            )
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return str(response)


def _as_posting(posting: object) -> RawPosting:
    return posting if isinstance(posting, RawPosting) else RawPosting(**dict(posting))  # type: ignore[arg-type]


class FakeJobBoard:
    """A scripted, queue-based ``JobBoardProvider`` -- the FakeLlm of the Job Board seam.

    Tests never reach a real board (CLAUDE.md; the v7 spec repeats it), and unlike the LLM
    boundary there is no single function to monkeypatch: the Scan engine is handed a
    ``BoardProviderRegistry``, so a test builds one of these per board and registers them.

    Same contract as ``FakeLlm`` on purpose, including the strict one: an UNSCRIPTED call is an
    ``AssertionError``, not an empty result. A Scan that silently called a board one extra time
    (a retry, a second pass) would otherwise pass its test while doubling the real traffic this
    board's ``min_interval_hours`` exists to limit.

    Queue whatever the call should produce, in order:

    * ``queue_ok(*postings)``  -- a ``RawPosting`` each, or a dict of its fields;
    * ``queue_blocked(msg)`` / ``queue_error(msg)`` -- the two non-``ok`` Board Statuses an
      adapter may report;
    * ``queue(BoardResult(...))`` -- anything more specific;
    * ``queue(RuntimeError("boom"))`` -- an exception INSTANCE is raised instead of returned,
      which is how the engine's "an adapter that raises still only fails its own board" path
      gets exercised.
    """

    def __init__(
        self,
        board_id: str = "linkedin",
        *,
        display_name: str | None = None,
        min_interval_hours: int | None = None,
        results: list[object] | None = None,
    ) -> None:
        # Rejects an id the catalog does not know, so a typo in a test fails here rather than
        # as a mysteriously absent board later.
        spec = board_spec(board_id)
        self.id = spec.id
        self.display_name = display_name or spec.display_name
        self.min_interval_hours = (
            spec.min_interval_hours if min_interval_hours is None else min_interval_hours
        )
        self._results: list[object] = list(results or [])
        self.queries: list[BoardQuery] = []

    def queue(self, *results: object) -> "FakeJobBoard":
        for result in results:
            if isinstance(result, (list, tuple)):
                self._results.append(
                    BoardResult(items=[_as_posting(p) for p in result], status="ok")
                )
            else:
                self._results.append(result)
        return self

    def queue_ok(self, *postings: object) -> "FakeJobBoard":
        self._results.append(
            BoardResult(items=[_as_posting(p) for p in postings], status="ok")
        )
        return self

    def queue_blocked(self, message: str = "rate limited") -> "FakeJobBoard":
        self._results.append(BoardResult(items=[], status="blocked", message=message))
        return self

    def queue_error(self, message: str = "board is broken") -> "FakeJobBoard":
        self._results.append(BoardResult(items=[], status="error", message=message))
        return self

    @property
    def call_count(self) -> int:
        return len(self.queries)

    async def search(self, query: BoardQuery) -> BoardResult:
        self.queries.append(query)
        if not self._results:
            raise AssertionError(
                f"FakeJobBoard({self.id!r}) received unscripted call #{len(self.queries)} — "
                "queue another result before running this scan."
            )
        result = self._results.pop(0)
        if isinstance(result, BaseException):
            raise result
        if isinstance(result, BoardResult):
            return result
        raise AssertionError(
            f"FakeJobBoard({self.id!r}) was queued a {type(result).__name__}; expected a "
            "BoardResult, a list of RawPosting, or an exception instance."
        )
