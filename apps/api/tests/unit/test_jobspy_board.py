"""Unit tests for the JobSpy-backed Job Boards (v7 ticket 04):
``app/services/jobboards/jobspy_board.py`` and ``real_providers.py``.

No network and no ``jobspy``: every test replaces ``sys.modules["jobspy"]`` with a module whose
``scrape_jobs`` returns a DataFrame the test wrote, which is exactly the seam the adapter's lazy
``from jobspy import scrape_jobs`` goes through. pandas IS real here -- the whole point of the
mapping tests is the shapes pandas actually produces (an empty frame with no columns, ``NaT``,
``NaN`` in a column only one site filled), and a hand-rolled stand-in would test the stand-in.
"""

from __future__ import annotations

import logging
import sys
import types
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from app.domain.schemas import BoardQuery, RawPosting
from app.services.jobboards.jobspy_board import (
    MAX_QUERIES_PER_SEARCH,
    JobSpyBoard,
    country_for_location,
    glassdoor_board,
    google_board,
    indeed_board,
    linkedin_board,
)
from app.services.jobboards.provider_registry import BoardProviderRegistry
from app.services.jobboards.real_providers import jobspy_providers

# A complete row, in JobSpy's own column names and value types (``date_posted`` is a calendar
# ``date``, not a datetime -- that is what its model declares).
FULL_ROW = {
    "id": "li-1",
    "site": "linkedin",
    "job_url": "https://www.linkedin.com/jobs/view/1",
    "job_url_direct": "https://acme.example/careers/1",
    "title": "Senior Backend Engineer",
    "company": "Acme Tech",
    "location": "São Paulo, SP, Brazil",
    "date_posted": date(2026, 8, 20),
    "is_remote": True,
    "description": "## Sobre a vaga\nPython, FastAPI.",
}


class _FakeScrape:
    """Records every ``scrape_jobs`` call and answers from a scripted queue."""

    def __init__(self, *results: object) -> None:
        self.results = list(results)
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if not self.results:
            return pd.DataFrame()
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        if callable(result):
            return result()
        return result


def install_fake_jobspy(monkeypatch: pytest.MonkeyPatch, scrape: _FakeScrape) -> _FakeScrape:
    """Put a fake ``jobspy`` module in ``sys.modules`` for the duration of one test."""
    module = types.ModuleType("jobspy")
    module.scrape_jobs = scrape  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "jobspy", module)
    return scrape


def frame(*rows: dict[str, object]) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


class TestCountryForLocation:
    """``country_indeed`` derivation. JobSpy RAISES on a country string it does not know, so the
    rule is: recognize a closed vocabulary, otherwise say nothing and let the caller default."""

    @pytest.mark.parametrize(
        "location,expected",
        [
            ("Brasil", "brazil"),
            ("brazil", "brazil"),
            ("São Paulo, SP", "brazil"),
            ("Belo Horizonte, MG, Brasil", "brazil"),
            ("Rio de Janeiro", "brazil"),
            ("Lisboa, Portugal", "portugal"),
            ("Austin, TX, United States", "usa"),
            ("London, United Kingdom", "uk"),
            ("Berlin, Alemanha", "germany"),
        ],
    )
    def test_recognized_locations(self, location: str, expected: str) -> None:
        assert country_for_location(location) == expected

    @pytest.mark.parametrize("location", ["", None, "Latam", "Anywhere in EMEA", "Atlantis"])
    def test_unrecognized_locations_say_nothing(self, location: str | None) -> None:
        assert country_for_location(location) is None

    def test_accents_and_case_do_not_matter(self) -> None:
        assert country_for_location("SÃO PAULO") == "brazil"
        assert country_for_location("frança") == "france"


class TestQueryPlanning:
    async def test_one_call_per_role_and_location_with_the_budget_split(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scrape = install_fake_jobspy(monkeypatch, _FakeScrape())
        board = indeed_board()

        await board.search(
            BoardQuery(
                roles=["Backend Engineer", "Python Developer"],
                locations=["São Paulo, SP", "Rio de Janeiro"],
                hours_old=48,
                results_wanted=40,
            )
        )

        assert len(scrape.calls) == 4
        assert [c["search_term"] for c in scrape.calls] == [
            "Backend Engineer",
            "Backend Engineer",
            "Python Developer",
            "Python Developer",
        ]
        assert [c["location"] for c in scrape.calls] == [
            "São Paulo, SP",
            "Rio de Janeiro",
            "São Paulo, SP",
            "Rio de Janeiro",
        ]
        # 40 postings wanted from this board, split across the four calls it fans out into.
        assert {c["results_wanted"] for c in scrape.calls} == {10}
        assert {c["hours_old"] for c in scrape.calls} == {48}
        assert {c["country_indeed"] for c in scrape.calls} == {"brazil"}

    async def test_a_remote_location_becomes_a_remote_query_not_a_place(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scrape = install_fake_jobspy(monkeypatch, _FakeScrape())

        await indeed_board().search(
            BoardQuery(roles=["SRE"], locations=["Brasil", "Remoto"], remote="any")
        )

        assert [(c["location"], c["is_remote"]) for c in scrape.calls] == [
            ("Brasil", False),
            (None, True),
        ]

    async def test_remote_only_filters_every_query(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scrape = install_fake_jobspy(monkeypatch, _FakeScrape())

        await indeed_board().search(
            BoardQuery(roles=["SRE"], locations=["Brasil"], remote="remote_only")
        )

        assert [(c["location"], c["is_remote"]) for c in scrape.calls] == [("Brasil", True)]

    async def test_an_empty_query_still_runs_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scrape = install_fake_jobspy(monkeypatch, _FakeScrape())

        await indeed_board().search(BoardQuery())

        assert len(scrape.calls) == 1
        assert scrape.calls[0]["search_term"] is None
        assert scrape.calls[0]["location"] is None
        # No location named a country, so the instance default is what reaches JobSpy.
        assert scrape.calls[0]["country_indeed"] == "brazil"

    async def test_the_default_country_is_configurable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scrape = install_fake_jobspy(monkeypatch, _FakeScrape())

        await indeed_board(default_country="portugal").search(BoardQuery(roles=["QA"]))

        assert scrape.calls[0]["country_indeed"] == "portugal"

    async def test_a_location_that_names_a_country_beats_the_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scrape = install_fake_jobspy(monkeypatch, _FakeScrape())

        await indeed_board().search(
            BoardQuery(roles=["QA"], locations=["Porto, Portugal", "Madrid, Espanha"])
        )

        assert [c["country_indeed"] for c in scrape.calls] == ["portugal", "spain"]

    async def test_the_number_of_queries_is_capped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scrape = install_fake_jobspy(monkeypatch, _FakeScrape())

        await indeed_board().search(
            BoardQuery(
                roles=["a", "b", "c", "d"],
                locations=["São Paulo", "Rio de Janeiro", "Curitiba, PR"],
            )
        )

        assert len(scrape.calls) == MAX_QUERIES_PER_SEARCH

    async def test_the_cap_is_configurable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        scrape = install_fake_jobspy(monkeypatch, _FakeScrape())

        await indeed_board(max_queries=2).search(
            BoardQuery(roles=["a", "b", "c"], locations=["Brasil", "Portugal"])
        )

        assert len(scrape.calls) == 2

    async def test_hours_old_zero_is_no_filter_rather_than_zero_hours(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scrape = install_fake_jobspy(monkeypatch, _FakeScrape())

        await indeed_board().search(BoardQuery(roles=["QA"], hours_old=0))

        assert scrape.calls[0]["hours_old"] is None


class TestSiteWiring:
    @pytest.mark.parametrize(
        "factory,site",
        [
            (linkedin_board, "linkedin"),
            (indeed_board, "indeed"),
            (glassdoor_board, "glassdoor"),
            (google_board, "google"),
        ],
    )
    async def test_each_board_scrapes_exactly_its_own_site(
        self, monkeypatch: pytest.MonkeyPatch, factory: object, site: str
    ) -> None:
        scrape = install_fake_jobspy(monkeypatch, _FakeScrape())

        board = factory(fetch_applicant_bands=False)  # type: ignore[operator]
        await board.search(BoardQuery(roles=["QA"]))

        assert scrape.calls[0]["site_name"] == [site]
        assert scrape.calls[0]["description_format"] == "markdown"
        # ``linkedin_fetch_description`` costs one extra request per posting and only LinkedIn
        # has a description to fetch; asking the other three for it would be a no-op flag.
        assert scrape.calls[0]["linkedin_fetch_description"] is (site == "linkedin")

    def test_a_board_that_is_not_backed_by_jobspy_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not backed by JobSpy"):
            JobSpyBoard("remotive")

    def test_the_catalog_owns_the_display_name_and_minimum_interval(self) -> None:
        board = linkedin_board()
        assert board.id == "linkedin"
        assert board.display_name == "LinkedIn"
        assert board.min_interval_hours == 1


class TestFrameMapping:
    async def test_a_complete_row_becomes_a_raw_posting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install_fake_jobspy(monkeypatch, _FakeScrape(frame(FULL_ROW)))

        result = await indeed_board().search(BoardQuery(roles=["QA"]))

        assert result.status == "ok"
        assert len(result.items) == 1
        posting = result.items[0]
        assert posting.title == "Senior Backend Engineer"
        assert posting.company == "Acme Tech"
        assert posting.location == "São Paulo, SP, Brazil"
        assert posting.is_remote is True
        assert posting.url == "https://www.linkedin.com/jobs/view/1"
        assert posting.description == "## Sobre a vaga\nPython, FastAPI."
        # A calendar date resolves to 00:00 UTC of that day (frozen contract, decision 9).
        assert posting.date_posted == datetime(2026, 8, 20, tzinfo=timezone.utc)
        # Only the LinkedIn enrichment may produce a band; every other board leaves ``None``.
        assert posting.applicant_band is None

    async def test_an_empty_result_has_no_columns_at_all(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # This is literally what ``scrape_jobs`` returns when nothing matched.
        install_fake_jobspy(monkeypatch, _FakeScrape(pd.DataFrame()))

        result = await indeed_board().search(BoardQuery(roles=["QA"]))

        assert result.status == "ok"
        assert result.items == []

    async def test_missing_columns_fall_back_instead_of_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install_fake_jobspy(
            monkeypatch,
            _FakeScrape(
                frame({"title": "Dev", "job_url": "https://x.example/1", "company": "Acme"})
            ),
        )

        result = await indeed_board().search(BoardQuery(roles=["QA"]))

        posting = result.items[0]
        assert posting.location is None
        assert posting.is_remote is False
        assert posting.description == ""
        assert posting.date_posted is None

    async def test_nan_and_nat_cells_are_absences_not_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Concatenating per-site frames is how JobSpy fills a column only one site knows, so
        # NaN in an otherwise-present column is the normal case, and NaT is a datetime instance
        # that must not survive as a timestamp.
        install_fake_jobspy(
            monkeypatch,
            _FakeScrape(
                frame(
                    {
                        "title": "Dev",
                        "job_url": "https://x.example/1",
                        "company": "Acme",
                        "location": float("nan"),
                        "description": float("nan"),
                        "is_remote": float("nan"),
                        "date_posted": pd.NaT,
                    }
                )
            ),
        )

        posting = (await indeed_board().search(BoardQuery(roles=["QA"]))).items[0]

        assert posting.location is None
        assert posting.description == ""
        assert posting.is_remote is False
        assert posting.date_posted is None

    async def test_a_date_posted_string_is_read_as_utc(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install_fake_jobspy(
            monkeypatch,
            _FakeScrape(
                frame(
                    {"title": "Dev", "job_url": "https://x.example/1", "date_posted": "2026-08-19"},
                    {
                        "title": "Dev2",
                        "job_url": "https://x.example/2",
                        "date_posted": "2026-08-19T15:30:00Z",
                    },
                )
            ),
        )

        items = (await indeed_board().search(BoardQuery(roles=["QA"]))).items

        assert items[0].date_posted == datetime(2026, 8, 19, tzinfo=timezone.utc)
        assert items[1].date_posted == datetime(2026, 8, 19, 15, 30, tzinfo=timezone.utc)

    async def test_a_naive_datetime_is_assumed_utc(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install_fake_jobspy(
            monkeypatch,
            _FakeScrape(
                frame(
                    {
                        "title": "Dev",
                        "job_url": "https://x.example/1",
                        "date_posted": datetime(2026, 8, 19, 10, 0),
                    }
                )
            ),
        )

        posting = (await indeed_board().search(BoardQuery(roles=["QA"]))).items[0]

        assert posting.date_posted == datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc)

    async def test_rows_without_a_title_or_a_url_are_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install_fake_jobspy(
            monkeypatch,
            _FakeScrape(
                frame(
                    {"title": "", "job_url": "https://x.example/1", "company": "Acme"},
                    {"title": "Dev", "job_url": "", "company": "Acme"},
                    {"title": "Dev", "job_url": "https://x.example/3", "company": "Acme"},
                )
            ),
        )

        items = (await indeed_board().search(BoardQuery(roles=["QA"]))).items

        assert [p.url for p in items] == ["https://x.example/3"]

    async def test_a_missing_company_keeps_the_posting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install_fake_jobspy(
            monkeypatch,
            _FakeScrape(frame({"title": "Dev", "job_url": "https://x.example/1"})),
        )

        items = (await indeed_board().search(BoardQuery(roles=["QA"]))).items

        assert len(items) == 1
        assert items[0].company == ""

    async def test_job_url_direct_is_the_fallback_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install_fake_jobspy(
            monkeypatch,
            _FakeScrape(
                frame(
                    {
                        "title": "Dev",
                        "job_url": None,
                        "job_url_direct": "https://acme.example/careers/9",
                    }
                )
            ),
        )

        items = (await indeed_board().search(BoardQuery(roles=["QA"]))).items

        assert items[0].url == "https://acme.example/careers/9"

    async def test_the_same_posting_found_by_two_roles_is_reported_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        row = {"title": "Dev", "job_url": "https://x.example/1", "company": "Acme"}
        install_fake_jobspy(monkeypatch, _FakeScrape(frame(row), frame(row)))

        result = await indeed_board().search(BoardQuery(roles=["Backend", "Python"]))

        assert len(result.items) == 1


class TestBlockingAndErrors:
    async def test_a_429_exception_is_blocked_not_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install_fake_jobspy(
            monkeypatch,
            _FakeScrape(RuntimeError("429 Response - Blocked by Glassdoor for too many requests")),
        )

        result = await glassdoor_board().search(BoardQuery(roles=["QA"]))

        assert result.status == "blocked"
        assert "429" in (result.message or "")
        assert result.items == []

    async def test_a_plain_breakage_is_an_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install_fake_jobspy(monkeypatch, _FakeScrape(ValueError("unparseable payload")))

        result = await glassdoor_board().search(BoardQuery(roles=["QA"]))

        assert result.status == "error"
        assert result.message == "unparseable payload"

    async def test_a_logged_refusal_is_blocked_even_though_jobspy_swallowed_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # LinkedIn's scraper does NOT raise on a 429: it logs and returns an empty result. Left
        # to the exception path this board would report "ok, nothing found" on the day it was
        # rate-limited -- the exact confusion Board Status exists to prevent.
        def _blocked_like_linkedin() -> pd.DataFrame:
            logging.getLogger("JobSpy:LinkedIn").error(
                "429 Response - Blocked by LinkedIn for too many requests"
            )
            return pd.DataFrame()

        install_fake_jobspy(monkeypatch, _FakeScrape(_blocked_like_linkedin))

        result = await linkedin_board(fetch_applicant_bands=False).search(
            BoardQuery(roles=["QA"])
        )

        assert result.status == "blocked"
        assert "Blocked by LinkedIn" in (result.message or "")

    async def test_an_ordinary_log_line_is_not_a_refusal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _noisy() -> pd.DataFrame:
            logging.getLogger("JobSpy:LinkedIn").error("LinkedIn: read timed out")
            return frame(FULL_ROW)

        install_fake_jobspy(monkeypatch, _FakeScrape(_noisy))

        result = await linkedin_board(fetch_applicant_bands=False).search(
            BoardQuery(roles=["QA"])
        )

        assert result.status == "ok"

    async def test_the_log_handler_is_removed_after_the_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install_fake_jobspy(monkeypatch, _FakeScrape(frame(FULL_ROW)))
        log = logging.getLogger("JobSpy:LinkedIn")
        before = list(log.handlers)

        await linkedin_board(fetch_applicant_bands=False).search(BoardQuery(roles=["QA"]))

        assert list(log.handlers) == before

    async def test_blocked_wins_over_a_partial_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Two queries, one answers and one is refused. Reporting ``ok`` would present a
        # half-list as the whole truth; the postings still ride along with the ``blocked``.
        install_fake_jobspy(
            monkeypatch,
            _FakeScrape(frame(FULL_ROW), RuntimeError("429 Too Many Requests")),
        )

        result = await indeed_board().search(BoardQuery(roles=["a", "b"]))

        assert result.status == "blocked"
        assert len(result.items) == 1

    async def test_a_missing_jobspy_package_is_an_actionable_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "jobspy", None)

        result = await indeed_board().search(BoardQuery(roles=["QA"]))

        assert result.status == "error"
        assert "python-jobspy" in (result.message or "")

    async def test_a_message_never_leaks_a_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install_fake_jobspy(
            monkeypatch,
            _FakeScrape(
                # The fake credentials are the point: this is the string that must not reach a
                # Board Status message.
                RuntimeError(
                    "failed GET https://user:pw@indeed.example/api?k=abc"  # pragma: allowlist secret
                )
            ),
        )

        result = await indeed_board().search(BoardQuery(roles=["QA"]))

        assert "indeed.example" not in (result.message or "")
        assert "[url]" in (result.message or "")

    async def test_a_message_is_capped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        install_fake_jobspy(monkeypatch, _FakeScrape(RuntimeError("x" * 500)))

        result = await indeed_board().search(BoardQuery(roles=["QA"]))

        assert len(result.message or "") <= 200

    async def test_nothing_escapes_search(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Explosive:
            @property
            def to_dict(self) -> object:  # pragma: no cover - accessed by the adapter
                raise RuntimeError("boom")

            def __len__(self) -> int:
                return 1

        install_fake_jobspy(monkeypatch, _FakeScrape(_Explosive()))

        result = await indeed_board().search(BoardQuery(roles=["QA"]))

        assert result.status in {"ok", "error"}
        assert result.items == []


class TestApplicantBandStep:
    async def test_linkedin_postings_are_enriched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install_fake_jobspy(monkeypatch, _FakeScrape(frame(FULL_ROW)))
        seen: list[list[RawPosting]] = []

        async def _enrich(postings):  # type: ignore[no-untyped-def]
            seen.append(list(postings))
            return [p.model_copy(update={"applicant_band": "<25"}) for p in postings]

        result = await linkedin_board(enrich=_enrich).search(BoardQuery(roles=["QA"]))

        assert len(seen) == 1
        assert [p.applicant_band for p in result.items] == ["<25"]

    async def test_the_other_boards_never_call_the_linkedin_step(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install_fake_jobspy(monkeypatch, _FakeScrape(frame(FULL_ROW)))
        called = False

        async def _enrich(postings):  # type: ignore[no-untyped-def]
            nonlocal called
            called = True
            return postings

        result = await indeed_board(enrich=_enrich).search(BoardQuery(roles=["QA"]))

        assert called is False
        assert result.items[0].applicant_band is None

    async def test_a_failing_enrichment_never_costs_the_postings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install_fake_jobspy(monkeypatch, _FakeScrape(frame(FULL_ROW)))

        async def _enrich(postings):  # type: ignore[no-untyped-def]
            raise RuntimeError("linkedin page fetch exploded")

        result = await linkedin_board(enrich=_enrich).search(BoardQuery(roles=["QA"]))

        assert result.status == "ok"
        assert len(result.items) == 1


class TestRealProviders:
    def test_the_four_jobspy_boards_in_catalog_order(self) -> None:
        providers = jobspy_providers()
        assert [p.id for p in providers] == ["linkedin", "indeed", "glassdoor", "google"]

    def test_they_satisfy_the_registry(self) -> None:
        registry = BoardProviderRegistry(jobspy_providers())
        assert registry.ids() == ("linkedin", "indeed", "glassdoor", "google")

    def test_building_them_imports_nothing_and_reaches_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Constructed at startup in an environment where python-jobspy did not install, the
        # four boards must still exist -- they report ``error`` at search time instead.
        monkeypatch.setitem(sys.modules, "jobspy", None)
        assert len(jobspy_providers()) == 4

    def test_options_reach_every_board(self) -> None:
        providers = jobspy_providers(default_country="portugal", max_queries=2)
        assert {p.default_country for p in providers} == {"portugal"}
        assert {p.max_queries for p in providers} == {2}
