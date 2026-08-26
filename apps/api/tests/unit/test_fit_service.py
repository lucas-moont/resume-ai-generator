"""Unit tests for the two-stage Fit Score (v7 ticket 08) -- ``services/jobs/fit_service.py``.

No database and no Session: the module takes the Listing Memory as plain ``RememberedFit``
values and hands back plain ``FitOutcome`` values, which is exactly what makes the whole policy
-- discard, reuse, cap, degrade -- testable here rather than only end to end. The Scan engine
wiring lives in ``tests/integration/test_scan_fit.py``.

Every LLM call in this file goes through a scripted ``FakeLlm``: an unscripted call is an
``AssertionError``, which is how the "only the top N are sent" tests prove a NEGATIVE.
"""

from __future__ import annotations

import asyncio

import pytest

from app import config as config_module
from app.domain.schemas import ProfileMaster
from app.services.jobs.fit_service import (
    FitCandidate,
    RememberedFit,
    build_fit_user_msg,
    compact_profile,
    description_hash,
    keyword_fit,
    keyword_fit_detail,
    profile_tokens,
    score_listings,
)
from tests.factories import make_profile
from tests.fakes import FakeLlm

PYTHON_POSTING = (
    "We are looking for a backend engineer. Requirements: Python, Python, FastAPI, "
    "PostgreSQL, Docker. Nice to have: Redis and Kubernetes experience."
)

FRONTEND_POSTING = (
    "Frontend developer wanted. Requirements: React, TypeScript, CSS, Tailwind, Vite, "
    "Storybook. You will build interfaces with React every day."
)


def profile(**overrides) -> ProfileMaster:
    return ProfileMaster.model_validate(make_profile(**overrides))


def fit(value: int) -> str:
    return '{"fit": %d}' % value


# --- Stage 1: the keyword pass ------------------------------------------------------------------


class TestProfileTokens:
    def test_the_global_skills_are_tokens(self):
        tokens = profile_tokens(profile(skills=["Python", "Node.js", "C++"]))
        assert {"python", "node.js", "c++"} <= tokens

    def test_key_technologies_count_as_claimed_too(self):
        # CONTEXT.md (Key Technologies): a per-role line naming what THAT role used. It is a
        # claim the candidate made, so the cheap pass may match on it.
        p = profile(
            skills=["Python"],
            experience=[
                {
                    "company": "Acme",
                    "title": "Engineer",
                    "start": "2020",
                    "keyTechnologies": ["Terraform", "Kubernetes"],
                }
            ],
        )
        assert {"python", "terraform", "kubernetes"} <= profile_tokens(p)

    def test_free_prose_is_not_a_claim(self):
        # A bullet reading "migrated away from Oracle" must not make Oracle a claimed skill.
        p = profile(
            skills=["Python"],
            summary="Migrated the platform away from Oracle and Cobol.",
            experience=[
                {
                    "company": "Acme",
                    "title": "Engineer",
                    "start": "2020",
                    "highlights": ["Decommissioned the last Oracle database"],
                }
            ],
        )
        tokens = profile_tokens(p)
        assert "oracle" not in tokens and "cobol" not in tokens

    def test_no_profile_has_no_tokens(self):
        assert profile_tokens(None) == frozenset()


class TestKeywordFit:
    def test_a_matching_stack_scores_high(self):
        score = keyword_fit(
            profile(skills=["Python", "FastAPI", "PostgreSQL", "Docker", "Redis", "Kubernetes"]),
            PYTHON_POSTING,
        )
        assert score >= 80

    def test_a_different_discipline_scores_low(self):
        score = keyword_fit(profile(skills=["Python", "FastAPI", "PostgreSQL"]), FRONTEND_POSTING)
        assert score < 15

    def test_covering_everything_scores_100(self):
        detail = keyword_fit_detail(frozenset({"python", "fastapi"}), "Python and FastAPI.")
        assert detail.score == 100
        assert set(detail.matched) == set(detail.keywords)

    def test_covering_nothing_scores_0(self):
        assert keyword_fit_detail(frozenset({"cobol"}), "Python and FastAPI.").score == 0

    def test_a_repeated_requirement_weighs_more_than_a_mentioned_one(self):
        # The posting names Python three times and Kubernetes once, so the ranking that
        # ``extract_jd_keywords`` hands over puts Python first -- and the linear decay makes
        # covering it worth more.
        text = "Python. Python. Python. Kubernetes."
        python_only = keyword_fit_detail(frozenset({"python"}), text).score
        kubernetes_only = keyword_fit_detail(frozenset({"kubernetes"}), text).score
        assert python_only > kubernetes_only

    def test_matching_is_exact_never_substring(self):
        # "Java" must not match "JavaScript": handing a backend candidate a frontend posting is
        # precisely the mistake the cheap pass exists to avoid making cheaply.
        detail = keyword_fit_detail(frozenset({"java"}), "JavaScript, JavaScript, JavaScript.")
        assert detail.score == 0

    def test_punctuation_survives_the_token(self):
        # ``skill_token`` preserves ``.+#-`` so "C++" is not "C" and "Node.js" keeps its dot.
        assert keyword_fit_detail(frozenset({"node.js"}), "Node.js required.").score == 100
        assert keyword_fit_detail(frozenset({"c"}), "C++ required.").score == 0


class TestAbstention:
    """No evidence is not a bad score (module rule 2)."""

    def test_a_posting_with_no_keywords_has_no_evidence(self):
        detail = keyword_fit_detail(frozenset({"python"}), "join our talent pool")
        assert detail.has_evidence is False
        assert detail.score == 0

    def test_an_empty_description_has_no_evidence(self):
        assert keyword_fit_detail(frozenset({"python"}), "").has_evidence is False

    def test_a_profile_with_no_skills_has_no_evidence_either(self):
        assert keyword_fit_detail(frozenset(), PYTHON_POSTING).has_evidence is False

    async def test_an_abstaining_listing_is_never_discarded(self):
        # It ranks low, which is the conservative cost -- it does not vanish from the Monitor.
        llm = FakeLlm([fit(40)])
        outcomes = await score_listings(
            profile(),
            [FitCandidate(key="k", description="join our talent pool")],
            {},
            llm=llm,
        )
        assert outcomes["k"].discarded is False


# --- The floor -----------------------------------------------------------------------------------


class TestTheKeywordFloor:
    async def test_a_clear_miss_is_discarded_before_a_token_is_spent(self):
        llm = FakeLlm()  # nothing queued: any call is an AssertionError
        outcomes = await score_listings(
            profile(skills=["Python", "FastAPI", "PostgreSQL"]),
            [FitCandidate(key="frontend", description=FRONTEND_POSTING)],
            {},
            llm=llm,
        )
        assert outcomes["frontend"].discarded is True
        assert outcomes["frontend"].estimated is True
        assert llm.call_count == 0

    async def test_the_floor_comes_from_config(self, monkeypatch):
        # One skill out of six requirements is comfortably above the real floor of 15 and
        # comfortably below a floor of 99 -- the same listing, two verdicts, one constant.
        partial = profile(skills=["Python"])
        candidate = [FitCandidate(key="python", description=PYTHON_POSTING)]
        assert (await score_listings(partial, candidate, {}, llm=FakeLlm([fit(1)])))[
            "python"
        ].discarded is False

        monkeypatch.setattr(config_module, "FIT_KEYWORD_FLOOR", 99)
        llm = FakeLlm()
        outcomes = await score_listings(partial, candidate, {}, llm=llm)
        assert outcomes["python"].discarded is True
        assert llm.call_count == 0

    async def test_a_fit_already_paid_for_is_never_discarded_by_the_cheap_pass(self):
        # Rule 1: the model's number is better evidence than a thin keyword overlap.
        remembered = {
            "frontend": RememberedFit(
                fit_score=88, description_hash=description_hash(FRONTEND_POSTING)
            )
        }
        llm = FakeLlm()
        outcomes = await score_listings(
            profile(skills=["Python", "FastAPI", "PostgreSQL"]),
            [FitCandidate(key="frontend", description=FRONTEND_POSTING)],
            remembered,
            llm=llm,
        )
        assert outcomes["frontend"].discarded is False
        assert outcomes["frontend"].score == 88
        assert llm.call_count == 0


# --- Stage 2: the LLM -----------------------------------------------------------------------------


class TestTheLlmStage:
    async def test_the_models_number_replaces_the_estimate(self):
        llm = FakeLlm([fit(91)])
        outcomes = await score_listings(
            profile(), [FitCandidate(key="k", description=PYTHON_POSTING)], {}, llm=llm
        )
        assert outcomes["k"].score == 91
        assert outcomes["k"].estimated is False
        assert outcomes["k"].source == "llm"
        assert outcomes["k"].should_remember is True

    async def test_one_call_per_listing(self):
        llm = FakeLlm([fit(70), fit(60), fit(50)])
        candidates = [
            FitCandidate(key=f"k{i}", description=PYTHON_POSTING) for i in range(3)
        ]
        await score_listings(profile(), candidates, {}, llm=llm)
        assert llm.call_count == 3

    async def test_the_prompt_carries_the_profile_and_the_posting(self):
        llm = FakeLlm([fit(70)])
        await score_listings(
            profile(), [FitCandidate(key="k", description=PYTHON_POSTING)], {}, llm=llm
        )
        user = llm.calls[0]["user"]
        assert "Senior Backend Engineer" in user  # the headline
        assert "FastAPI" in user  # a skill
        assert "Nice to have: Redis" in user  # the posting itself
        assert "only valid JSON" not in user  # the rules live in the system prompt

    async def test_the_system_prompt_is_the_job_fit_skill(self):
        llm = FakeLlm([fit(70)])
        await score_listings(
            profile(), [FitCandidate(key="k", description=PYTHON_POSTING)], {}, llm=llm
        )
        assert '{"fit": <integer 0-100>}' in llm.calls[0]["system"]

    async def test_the_model_override_is_passed_through(self):
        llm = FakeLlm([fit(70)])
        await score_listings(
            profile(),
            [FitCandidate(key="k", description=PYTHON_POSTING)],
            {},
            llm=llm,
            model="claude-sonnet-5",
        )
        assert llm.calls[0]["model"] == "claude-sonnet-5"


class TestTheTopNCap:
    def _candidates(self, count: int) -> list[FitCandidate]:
        # Each posting names Python one time fewer, so stage 1 ranks them in a known order.
        return [
            FitCandidate(
                key=f"k{index:02d}",
                description="Python. " * (count - index) + "Kubernetes. " * index,
            )
            for index in range(count)
        ]

    async def test_only_the_top_n_reach_the_model(self, monkeypatch):
        monkeypatch.setattr(config_module, "FIT_LLM_TOP_N", 2)
        llm = FakeLlm([fit(90), fit(80)])  # exactly two: a third call would raise
        outcomes = await score_listings(
            profile(skills=["Python"]), self._candidates(5), {}, llm=llm
        )
        assert llm.call_count == 2
        assert sum(1 for o in outcomes.values() if o.source == "llm") == 2

    async def test_the_ones_left_out_keep_the_keyword_estimate(self, monkeypatch):
        monkeypatch.setattr(config_module, "FIT_LLM_TOP_N", 1)
        llm = FakeLlm([fit(90)])
        outcomes = await score_listings(
            profile(skills=["Python"]), self._candidates(3), {}, llm=llm
        )
        estimated = [o for o in outcomes.values() if o.estimated]
        assert len(estimated) == 2
        assert all(o.source == "keyword" for o in estimated)
        assert all(o.should_remember is False for o in estimated)

    async def test_the_highest_keyword_fit_is_the_one_chosen(self, monkeypatch):
        monkeypatch.setattr(config_module, "FIT_LLM_TOP_N", 1)
        llm = FakeLlm([fit(90)])
        outcomes = await score_listings(
            profile(skills=["Python"]), self._candidates(3), {}, llm=llm
        )
        # k00 names Python most often, so it wins stage 1 and takes the one slot.
        assert outcomes["k00"].source == "llm"

    async def test_the_default_cap_is_25(self):
        assert config_module.FIT_LLM_TOP_N == 25

    async def test_a_memory_hit_does_not_consume_a_slot(self, monkeypatch):
        # The cap counts CALLS, not listings: a Fit served from memory costs nothing.
        monkeypatch.setattr(config_module, "FIT_LLM_TOP_N", 1)
        candidates = self._candidates(2)
        remembered = {
            candidates[0].key: RememberedFit(
                fit_score=95, description_hash=description_hash(candidates[0].description)
            )
        }
        llm = FakeLlm([fit(30)])
        outcomes = await score_listings(
            profile(skills=["Python"]), candidates, remembered, llm=llm
        )
        assert outcomes[candidates[0].key].source == "memory"
        assert outcomes[candidates[1].key].source == "llm"
        assert llm.call_count == 1


class TestTheListingMemory:
    async def test_the_same_description_is_never_re_scored(self):
        remembered = {"k": RememberedFit(80, description_hash(PYTHON_POSTING))}
        llm = FakeLlm()
        outcomes = await score_listings(
            profile(), [FitCandidate(key="k", description=PYTHON_POSTING)], remembered, llm=llm
        )
        assert outcomes["k"] == outcomes["k"].__class__(
            score=80,
            estimated=False,
            source="memory",
            description_hash=description_hash(PYTHON_POSTING),
        )
        assert llm.call_count == 0

    async def test_a_rewritten_description_goes_back_to_the_model(self):
        remembered = {"k": RememberedFit(80, description_hash("an older version of the text"))}
        llm = FakeLlm([fit(44)])
        outcomes = await score_listings(
            profile(), [FitCandidate(key="k", description=PYTHON_POSTING)], remembered, llm=llm
        )
        assert llm.call_count == 1
        assert outcomes["k"].score == 44
        assert outcomes["k"].description_hash == description_hash(PYTHON_POSTING)

    async def test_a_memory_with_a_hash_but_no_score_is_not_reusable(self):
        remembered = {"k": RememberedFit(None, description_hash(PYTHON_POSTING))}
        llm = FakeLlm([fit(44)])
        outcomes = await score_listings(
            profile(), [FitCandidate(key="k", description=PYTHON_POSTING)], remembered, llm=llm
        )
        assert llm.call_count == 1 and outcomes["k"].score == 44

    async def test_a_score_with_no_hash_is_not_reusable_either(self):
        # Nothing but stage 2 writes a hash, so a score without one cannot be vouched for.
        remembered = {"k": RememberedFit(80, None)}
        llm = FakeLlm([fit(44)])
        outcomes = await score_listings(
            profile(), [FitCandidate(key="k", description=PYTHON_POSTING)], remembered, llm=llm
        )
        assert llm.call_count == 1 and outcomes["k"].score == 44

    async def test_only_the_models_number_is_worth_remembering(self):
        llm = FakeLlm([fit(44)])
        outcomes = await score_listings(
            profile(skills=["Python"]),
            [
                # The stronger keyword fit takes the single slot.
                FitCandidate(key="scored", description="Python. Python. Python."),
                FitCandidate(key="estimated", description="Python. Kubernetes. Terraform."),
            ],
            {},
            llm=llm,
            top_n=1,
        )
        assert outcomes["scored"].should_remember is True
        assert outcomes["estimated"].should_remember is False


class TestDegradation:
    async def test_a_provider_error_on_one_listing_keeps_its_estimate(self):
        llm = FakeLlm([RuntimeError("provider exploded"), fit(70)])
        outcomes = await score_listings(
            profile(skills=["Python"]),
            [
                FitCandidate(key="a", description="Python. Python. Python."),
                FitCandidate(key="b", description="Python. Kubernetes."),
            ],
            {},
            llm=llm,
        )
        assert outcomes["a"].estimated is True and outcomes["a"].source == "keyword"
        assert outcomes["b"].estimated is False and outcomes["b"].score == 70

    async def test_garbage_from_the_model_keeps_the_estimate(self):
        llm = FakeLlm(["I think it's a great match!"])
        outcomes = await score_listings(
            profile(skills=["Python"]),
            [FitCandidate(key="a", description="Python. Python.")],
            {},
            llm=llm,
        )
        assert outcomes["a"].estimated is True
        assert outcomes["a"].score == keyword_fit(profile(skills=["Python"]), "Python. Python.")

    async def test_an_out_of_range_answer_keeps_the_estimate(self):
        llm = FakeLlm(['{"fit": 850}'])
        outcomes = await score_listings(
            profile(skills=["Python"]),
            [FitCandidate(key="a", description="Python. Python.")],
            {},
            llm=llm,
        )
        assert outcomes["a"].estimated is True and outcomes["a"].should_remember is False

    async def test_a_timeout_keeps_the_estimate_and_does_not_hang_the_scan(self):
        async def never_answers(system, user, model=None):
            await asyncio.sleep(30)
            return fit(90)

        outcomes = await score_listings(
            profile(skills=["Python"]),
            [FitCandidate(key="a", description="Python. Python.")],
            {},
            llm=never_answers,
            timeout_seconds=0,
        )
        assert outcomes["a"].estimated is True

    async def test_cancellation_is_not_swallowed(self):
        async def cancelled(system, user, model=None):
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await score_listings(
                profile(skills=["Python"]),
                [FitCandidate(key="a", description="Python. Python.")],
                {},
                llm=cancelled,
            )


class TestNoProfile:
    async def test_nothing_is_scored_and_nothing_is_discarded(self):
        llm = FakeLlm()
        outcomes = await score_listings(
            None, [FitCandidate(key="k", description=FRONTEND_POSTING)], {}, llm=llm
        )
        assert llm.call_count == 0
        assert outcomes["k"].discarded is False
        assert outcomes["k"].score == 0

    async def test_a_remembered_fit_still_comes_back(self):
        remembered = {"k": RememberedFit(77, description_hash(PYTHON_POSTING))}
        outcomes = await score_listings(
            None, [FitCandidate(key="k", description=PYTHON_POSTING)], remembered, llm=FakeLlm()
        )
        assert outcomes["k"].score == 77 and outcomes["k"].source == "memory"


class TestEdges:
    async def test_no_candidates_is_an_empty_map(self):
        assert await score_listings(profile(), [], {}, llm=FakeLlm()) == {}

    async def test_a_cap_of_zero_sends_nothing(self):
        llm = FakeLlm()
        outcomes = await score_listings(
            profile(), [FitCandidate(key="k", description=PYTHON_POSTING)], {}, llm=llm, top_n=0
        )
        assert llm.call_count == 0 and outcomes["k"].estimated is True

    async def test_memory_may_be_omitted_entirely(self):
        llm = FakeLlm([fit(50)])
        outcomes = await score_listings(
            profile(), [FitCandidate(key="k", description=PYTHON_POSTING)], llm=llm
        )
        assert outcomes["k"].score == 50


class TestThePromptPayload:
    def test_the_compact_profile_leaves_out_contact_details(self):
        text = compact_profile(profile())
        assert "ana.costa@example.com" not in text
        assert "linkedin.com/in/anacosta" not in text

    def test_it_leaves_out_the_bullets(self):
        text = compact_profile(profile())
        assert "Mentored three engineers" not in text

    def test_it_keeps_what_a_first_pass_reads(self):
        text = compact_profile(profile())
        assert "Senior Backend Engineer" in text
        assert "PostgreSQL" in text
        assert "Acme Corp" in text

    def test_key_technologies_travel_with_their_role(self):
        p = profile(
            experience=[
                {
                    "company": "Acme",
                    "title": "Engineer",
                    "start": "2020",
                    "keyTechnologies": ["Terraform"],
                }
            ]
        )
        assert "Key technologies: Terraform" in compact_profile(p)

    def test_a_very_long_posting_is_truncated(self):
        message = build_fit_user_msg(profile(), "word " * 20000)
        assert "[...]" in message
        assert len(message) < 20000

    def test_an_empty_posting_says_so_rather_than_sending_nothing(self):
        assert "no description" in build_fit_user_msg(profile(), "")
