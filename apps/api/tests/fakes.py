"""Test doubles for the LLM boundary (``app.services.llm_client.chat_json``).

``app/main.py`` imports ``chat_json`` directly (``from app.services.llm_client import
chat_json``), so the name is bound in ``app.main``'s own module namespace and is looked up
there at call time. Patching ``app.services.llm_client.chat_json`` would therefore NOT affect
the endpoints — tests must monkeypatch ``app.main.chat_json`` instead (see
``tests.conftest.fake_llm``).
"""

from __future__ import annotations


class FakeLlm:
    """A scripted, queue-based replacement for ``chat_json``.

    Some endpoints (``/api/generate`` and its stream) can call the LLM more than once in a
    single request — a first pass to draft the resume, and a second "quality guard" pass
    when ``_quality_issues`` finds something to fix. Queue one response per expected call,
    in order; queuing an exception instance makes that call raise instead of returning.
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
