"""Deterministic stand-in Job Boards for the OPT-IN live paths (v7 ticket 15).

CLAUDE.md and the v7 spec say the same thing twice: tests never reach a real Job Board. The
mocked Playwright suite honours that by never letting a request leave the browser, but the
``@real`` variant exists precisely to exercise the real FastAPI app and the real LLM -- and a
real ``POST /api/jobs/scans`` there would call LinkedIn, Indeed and Glassdoor for real.

So the ``@real`` path swaps the ADAPTERS and nothing else: with ``JOB_BOARDS_FAKE=1`` set on
the backend process, ``build_default_registry`` returns these instead of the network-reaching
ones. Everything downstream -- the Scan engine, dedup, the keyword pass, the LLM Fit pass, the
Listing Memory, One-click Resume -- is the production code path, running against three boards
whose answers are a constant.

This is NOT ``tests.fakes.FakeJobBoard``. That one is strict by design (an unscripted call is
an ``AssertionError``, which is right for a test and wrong for a server that stays up across
several Scans) and it lives in a test package the app must not import from. This is its
long-lived sibling: same Protocol, same three answers, no queue.

Off unless the env var says otherwise; production never constructs these.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.schemas import BoardQuery, BoardReportedStatus, BoardResult, RawPosting
from app.services.jobboards.base import JobBoardProvider
from app.services.jobboards.provider_registry import board_spec


class StaticJobBoard:
    """A ``JobBoardProvider`` that answers from a fixed list and never opens a socket.

    Satisfies the Protocol's whole contract, including the part that matters most here: trouble
    is REPORTED (``status="blocked"``), never raised, so a fake ``blocked`` board exercises the
    partial-Scan path and the BoardStatusBar flag exactly as a rate-limited LinkedIn would.

    ``queries`` is kept for the same reason ``FakeJobBoard`` keeps it -- so a test can assert
    the board was called once, not once per role.
    """

    def __init__(
        self,
        board_id: str,
        postings: list[RawPosting] | tuple[RawPosting, ...] = (),
        *,
        status: BoardReportedStatus = "ok",
        message: str | None = None,
    ) -> None:
        # Rejects an id the catalog does not know, so a typo fails here rather than as a
        # mysteriously absent board later.
        spec = board_spec(board_id)
        self.id = spec.id
        self.display_name = spec.display_name
        self.min_interval_hours = spec.min_interval_hours
        self._postings = list(postings)
        self._status: BoardReportedStatus = status
        self._message = message
        self.queries: list[BoardQuery] = []

    async def search(self, query: BoardQuery) -> BoardResult:
        self.queries.append(query)
        # A fresh copy per call: the Scan engine owns what it is handed, and two Scans in one
        # process must not share posting objects.
        return BoardResult(
            items=[posting.model_copy(deep=True) for posting in self._postings],
            status=self._status,
            message=self._message,
        )


def _hours_ago(hours: int) -> datetime:
    """Recent, and recomputed per call: a hard-coded date would age into the oldest recency
    bucket and make the Visibility ranking of these postings drift over time."""
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def _sample_postings() -> dict[str, list[RawPosting]]:
    """Three postings across three boards, long enough to be job descriptions.

    Every description clears ``looks_like_job_description`` (the One-click Resume's 422 gate) --
    generating a resume from the top-ranked listing is the point of the ``@real`` run, and a
    fixture that trips the "description too short" refusal would test the refusal instead.
    """
    return {
        "indeed": [
            RawPosting(
                title="Senior Backend Engineer",
                company="Acme Cloud",
                location="Remote",
                is_remote=True,
                url="https://example.invalid/jobs/acme-senior-backend-engineer",
                description=(
                    "Acme Cloud is hiring a Senior Backend Engineer to design and operate the "
                    "distributed services behind our platform. Requisitos: Python, FastAPI, "
                    "PostgreSQL, AWS, mensageria e observabilidade em produção. "
                    "Responsabilidades: ser dono dos serviços de ponta a ponta, participar do "
                    "on-call, mentorar pessoas engenheiras e conduzir o roadmap de APIs junto "
                    "com o time de produto. Diferenciais: Kubernetes, Terraform e experiência "
                    "prévia com sistemas de alta disponibilidade."
                ),
                date_posted=_hours_ago(2),
                applicant_band="<10",
            ),
            RawPosting(
                title="Engenheiro de Software Backend",
                company="Fintech BR",
                location="São Paulo, SP",
                is_remote=False,
                url="https://example.invalid/jobs/fintechbr-engenheiro-backend",
                description=(
                    "Vaga para pessoa engenheira de software backend no time de pagamentos. "
                    "Requisitos: Python, Django, PostgreSQL, filas e testes automatizados. "
                    "Responsabilidades: evoluir os serviços de pagamento, participar do on-call, "
                    "apoiar a evolução da arquitetura de dados e escrever documentação técnica "
                    "para os times parceiros. Oferecemos plano de saúde e trabalho híbrido."
                ),
                date_posted=_hours_ago(20),
            ),
        ],
        "remoteok": [
            RawPosting(
                title="Platform Engineer",
                company="Globex",
                location="Remote",
                is_remote=True,
                url="https://example.invalid/jobs/globex-platform-engineer",
                description=(
                    "Globex is looking for a Platform Engineer to own the internal developer "
                    "platform. Requirements: Python or Go, Kubernetes, CI/CD pipelines, "
                    "infrastructure as code and a strong bias for automation. "
                    "Responsibilities: run the build and deploy tooling every team depends on, "
                    "reduce lead time to production and keep the platform's reliability budget."
                ),
                date_posted=_hours_ago(8),
            ),
        ],
    }


def fake_providers() -> list[JobBoardProvider]:
    """The registry ``JOB_BOARDS_FAKE=1`` installs: two boards that answer and one that blocks.

    The blocked board is not decoration. "A Scan is partial, not failed" (CONTEXT.md: Scan) is
    the behaviour the Job Monitor's status bar exists for, so the live path should show it every
    run rather than only on the day LinkedIn happens to rate-limit us.
    """
    postings = _sample_postings()
    return [
        StaticJobBoard(
            "linkedin",
            status="blocked",
            message="LinkedIn recusou a busca (429). Boards falsos: JOB_BOARDS_FAKE=1.",
        ),
        StaticJobBoard("indeed", postings["indeed"]),
        StaticJobBoard("remoteok", postings["remoteok"]),
    ]


__all__ = ["StaticJobBoard", "fake_providers"]
