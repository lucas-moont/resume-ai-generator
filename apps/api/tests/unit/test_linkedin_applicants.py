"""Unit tests for the Applicant Band step (v7 ticket 04):
``app/services/jobboards/linkedin_applicants.py``.

Two halves, and only the first is interesting logic: the regex over a LinkedIn job page (the
three forms that page can use, plus everything it can say instead), and the enrichment loop,
whose entire specification is "never fails, never floods LinkedIn, never leaves a LinkedIn
posting at ``None``".

No network: every HTTP test drives an ``httpx`` transport the test wrote. The HTML fixtures are
inline constants rather than files under ``tests/fixtures/jobboards/`` -- that directory belongs
to the feed adapters of ticket 05, whose fixtures are recorded API payloads worth keeping
verbatim; these are three sentences of markup and read better beside the assertion.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.domain.schemas import RawPosting
from app.services.jobboards.linkedin_applicants import (
    DEFAULT_HEADERS,
    applicant_band_from_html,
    enrich_applicant_bands,
    fetch_applicant_band,
    is_linkedin_url,
)

# The three forms as LinkedIn renders them, markup included -- the caption really does arrive
# inside a span, which is why the parser strips tags before matching.
PAGE_EXACT = """
<html><body>
  <h1 class="top-card-layout__title">Senior Backend Engineer</h1>
  <figure class="num-applicants__figure">
    <figcaption class="num-applicants__caption">42 applicants</figcaption>
  </figure>
</body></html>
"""

PAGE_OVER_100 = """
<html><body>
  <span class="num-applicants__caption">Over 100 applicants</span>
</body></html>
"""

PAGE_FIRST_25 = """
<html><body>
  <figcaption class="num-applicants__caption">
    Be among the first 25 applicants
  </figcaption>
</body></html>
"""

PAGE_NO_APPLICANTS = """
<html><body>
  <h1>Senior Backend Engineer</h1>
  <p>Acme Tech &middot; São Paulo, SP &middot; 2 weeks ago</p>
</body></html>
"""

PAGE_LOGIN_WALL = """
<html><body>
  <h1>Sign in to see who Acme Tech has hired for this role</h1>
</body></html>
"""

PAGE_PT = """
<html><body>
  <span class="num-applicants__caption">Mais de 100 candidatos</span>
</body></html>
"""


def posting(url: str, **kwargs: object) -> RawPosting:
    return RawPosting(title="Dev", company="Acme", url=url, **kwargs)  # type: ignore[arg-type]


class TestApplicantBandFromHtml:
    def test_the_exact_form(self) -> None:
        assert applicant_band_from_html(PAGE_EXACT) == "<50"

    def test_the_over_one_hundred_form(self) -> None:
        assert applicant_band_from_html(PAGE_OVER_100) == "100+"

    def test_the_be_among_the_first_form(self) -> None:
        assert applicant_band_from_html(PAGE_FIRST_25) == "<25"

    def test_a_page_that_says_nothing_about_applicants(self) -> None:
        assert applicant_band_from_html(PAGE_NO_APPLICANTS) is None

    def test_a_login_wall_says_nothing(self) -> None:
        assert applicant_band_from_html(PAGE_LOGIN_WALL) is None

    @pytest.mark.parametrize("page_html", ["", None])
    def test_no_page_at_all(self, page_html: str | None) -> None:
        assert applicant_band_from_html(page_html) is None

    @pytest.mark.parametrize(
        "count,expected",
        [
            (1, "<10"),
            (9, "<10"),
            # A band is a strict upper bound, so the boundary belongs to the next bucket:
            # exactly 10 applicants is not "fewer than 10".
            (10, "<25"),
            (24, "<25"),
            (25, "<50"),
            (49, "<50"),
            (50, "<100"),
            (99, "<100"),
            (100, "100+"),
            (1500, "100+"),
        ],
    )
    def test_every_boundary_of_the_exact_form(self, count: int, expected: str) -> None:
        assert applicant_band_from_html(f"<span>{count} applicants</span>") == expected

    def test_the_singular_is_read_too(self) -> None:
        assert applicant_band_from_html("<span>1 applicant</span>") == "<10"

    def test_a_thousands_separator_is_not_a_decimal_point(self) -> None:
        assert applicant_band_from_html("<span>1,234 applicants</span>") == "100+"
        assert applicant_band_from_html("<span>1.234 candidatos</span>") == "100+"

    def test_over_is_read_before_the_bare_number(self) -> None:
        # "Over 100 applicants" also matches "<number> applicants"; read in the wrong order it
        # would report "<100" for the most crowded postings there are.
        assert applicant_band_from_html("Over 100 applicants") == "100+"
        assert applicant_band_from_html("Be among the first 25 applicants") == "<25"

    def test_entities_and_whitespace_do_not_hide_the_caption(self) -> None:
        assert applicant_band_from_html("<span>Over&nbsp;100\n  applicants</span>") == "100+"

    def test_the_portuguese_wording_is_a_fallback(self) -> None:
        # The request pins Accept-Language to English, but a geo-routed page may answer in
        # Portuguese anyway, and "unknown" there would be a band we could have had.
        assert applicant_band_from_html(PAGE_PT) == "100+"
        assert applicant_band_from_html("<span>7 candidatos</span>") == "<10"
        assert (
            applicant_band_from_html("<span>Seja um dos 25 primeiros candidatos</span>")
            == "<25"
        )


class TestIsLinkedinUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.linkedin.com/jobs/view/123",
            "https://br.linkedin.com/jobs/view/123",
            "https://linkedin.com/jobs/view/123",
        ],
    )
    def test_linkedin_urls(self, url: str) -> None:
        assert is_linkedin_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "",
            None,
            "https://remotive.com/jobs/1",
            # The suffix check must be on a dot boundary, or this would pass.
            "https://notlinkedin.com/jobs/1",
            "https://evil.example/linkedin.com/jobs/1",
        ],
    )
    def test_everything_else(self, url: str | None) -> None:
        assert is_linkedin_url(url) is False


def _client(handler) -> httpx.AsyncClient:  # type: ignore[no-untyped-def]
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestFetchApplicantBand:
    async def test_a_page_with_a_caption(self) -> None:
        async with _client(lambda r: httpx.Response(200, text=PAGE_EXACT)) as client:
            band = await fetch_applicant_band(
                "https://www.linkedin.com/jobs/view/1", client=client
            )
        assert band == "<50"

    async def test_a_refusal_is_unknown_not_an_exception(self) -> None:
        async with _client(lambda r: httpx.Response(429, text="slow down")) as client:
            band = await fetch_applicant_band(
                "https://www.linkedin.com/jobs/view/1", client=client
            )
        assert band == "unknown"

    async def test_linkedins_own_999_is_unknown(self) -> None:
        async with _client(lambda r: httpx.Response(999, text="")) as client:
            band = await fetch_applicant_band(
                "https://www.linkedin.com/jobs/view/1", client=client
            )
        assert band == "unknown"

    async def test_a_timeout_is_unknown(self) -> None:
        def _boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow", request=request)

        async with _client(_boom) as client:
            band = await fetch_applicant_band(
                "https://www.linkedin.com/jobs/view/1", client=client
            )
        assert band == "unknown"

    async def test_a_page_without_a_caption_is_unknown(self) -> None:
        async with _client(lambda r: httpx.Response(200, text=PAGE_NO_APPLICANTS)) as client:
            band = await fetch_applicant_band(
                "https://www.linkedin.com/jobs/view/1", client=client
            )
        assert band == "unknown"

    async def test_the_user_agent_is_explicit(self) -> None:
        seen: list[httpx.Request] = []

        def _record(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, text=PAGE_OVER_100)

        async with _client(_record) as client:
            await fetch_applicant_band("https://www.linkedin.com/jobs/view/1", client=client)

        assert seen[0].headers["user-agent"] == DEFAULT_HEADERS["User-Agent"]
        assert seen[0].headers["accept-language"].startswith("en-US")


class TestEnrichApplicantBands:
    async def test_every_linkedin_posting_gets_a_band(self) -> None:
        pages = {
            "1": PAGE_EXACT,
            "2": PAGE_OVER_100,
            "3": PAGE_NO_APPLICANTS,
        }

        def _serve(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=pages[request.url.path.rsplit("/", 1)[-1]])

        postings = [posting(f"https://www.linkedin.com/jobs/view/{n}") for n in "123"]
        async with _client(_serve) as client:
            enriched = await enrich_applicant_bands(postings, client=client)

        assert [p.applicant_band for p in enriched] == ["<50", "100+", "unknown"]

    async def test_non_linkedin_postings_are_left_alone(self) -> None:
        calls: list[httpx.Request] = []

        def _record(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, text=PAGE_OVER_100)

        postings = [
            posting("https://remotive.com/jobs/1"),
            posting("https://www.linkedin.com/jobs/view/2"),
        ]
        async with _client(_record) as client:
            enriched = await enrich_applicant_bands(postings, client=client)

        # ``None`` means "this board has no such concept" and must not become "unknown".
        assert enriched[0].applicant_band is None
        assert enriched[1].applicant_band == "100+"
        assert len(calls) == 1

    async def test_nothing_to_enrich_makes_no_request(self) -> None:
        called = False

        def _record(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, text=PAGE_OVER_100)

        async with _client(_record) as client:
            enriched = await enrich_applicant_bands(
                [posting("https://remotive.com/jobs/1")], client=client
            )

        assert called is False
        assert enriched[0].applicant_band is None

    async def test_an_empty_list_is_returned_as_is(self) -> None:
        assert await enrich_applicant_bands([]) == []

    async def test_one_failure_does_not_cost_the_others_their_band(self) -> None:
        def _serve(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/2"):
                raise httpx.ConnectError("refused", request=request)
            return httpx.Response(200, text=PAGE_OVER_100)

        postings = [posting(f"https://www.linkedin.com/jobs/view/{n}") for n in "123"]
        async with _client(_serve) as client:
            enriched = await enrich_applicant_bands(postings, client=client)

        assert [p.applicant_band for p in enriched] == ["100+", "unknown", "100+"]

    async def test_the_step_never_raises_even_when_the_client_is_broken(self) -> None:
        class _BrokenClient:
            async def get(self, *args: object, **kwargs: object) -> object:
                raise RuntimeError("client is a lie")

        postings = [posting("https://www.linkedin.com/jobs/view/1")]
        enriched = await enrich_applicant_bands(postings, client=_BrokenClient())  # type: ignore[arg-type]

        assert [p.applicant_band for p in enriched] == ["unknown"]

    async def test_requests_are_capped_by_the_semaphore(self) -> None:
        # The reason the semaphore exists: fifty parallel page loads right after a search is
        # the fastest way to get the SEARCH blocked, which is the part that matters.
        in_flight = 0
        peak = 0

        class _SlowTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                nonlocal in_flight, peak
                in_flight += 1
                peak = max(peak, in_flight)
                try:
                    for _ in range(5):
                        await asyncio.sleep(0)
                finally:
                    in_flight -= 1
                return httpx.Response(200, text=PAGE_OVER_100)

        postings = [posting(f"https://www.linkedin.com/jobs/view/{n}") for n in range(12)]
        async with httpx.AsyncClient(transport=_SlowTransport()) as client:
            enriched = await enrich_applicant_bands(postings, client=client, concurrency=3)

        assert peak <= 3
        assert all(p.applicant_band == "100+" for p in enriched)

    async def test_it_opens_its_own_client_when_none_is_given(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Guards the "no client passed" branch without reaching the network: the constructor is
        # replaced with one wired to a mock transport.
        real = httpx.AsyncClient

        def _fake(*args: object, **kwargs: object) -> httpx.AsyncClient:
            return real(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=PAGE_FIRST_25)))

        monkeypatch.setattr(httpx, "AsyncClient", _fake)

        enriched = await enrich_applicant_bands(
            [posting("https://www.linkedin.com/jobs/view/1")]
        )

        assert enriched[0].applicant_band == "<25"
