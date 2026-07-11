"""Unit tests for app/services/ingestion/merge_service.py (v2 ticket 04 -- "Merge incremental").

Exercises the full pipeline (Deterministic Diff -> Adjudication -> Containment -> Patch
Validator) against a scripted ``FakeLlm`` (tests/fakes.py, wired via the ``fake_llm`` fixture in
tests/conftest.py) -- never a real LLM. DB-touching pieces (``resolve_profile_for_merge``) use
the in-memory ``test_db_engine`` fixture directly, without going through the HTTP client.
"""

from __future__ import annotations

import json

import pytest
from sqlmodel import Session

from app.domain.schemas import ProfileMaster, ResumeDocument
from app.repositories import profile_repo
from app.services.ingestion.merge_service import propose_merge, resolve_profile_for_merge


def _profile(**overrides) -> ProfileMaster:
    base = dict(
        fullName="Lucas Monteiro",
        headline="Full Stack Developer",
        summary="Base summary.",
        skills=["React", "TypeScript"],
        experience=[
            {
                "company": "SmartHow",
                "title": "Front-End Developer",
                "start": "2025-01",
                "end": None,
                "highlights": ["Shipped the v1 chat experience"],
            }
        ],
        projects=[{"name": "Resume Agent", "description": "This very app."}],
        links=[{"label": "GitHub", "url": "https://github.com/lucas"}],
        education=[{"institution": "USP", "degree": "Bacharelado", "end": "2022"}],
    )
    base.update(overrides)
    return ProfileMaster.model_validate(base)


def _doc(**overrides) -> ResumeDocument:
    base = dict(
        fullName="Lucas Monteiro",
        headline="Full Stack Developer",
        summary="Base summary.",
        skills=["React", "TypeScript"],
        experience=[
            {
                "company": "SmartHow",
                "title": "Front-End Developer",
                "start": "2025-01",
                "end": None,
                "highlights": ["Shipped the v1 chat experience"],
            }
        ],
        projects=[{"name": "Resume Agent", "description": "This very app."}],
        links=[{"label": "GitHub", "url": "https://github.com/lucas"}],
        education=[{"institution": "USP", "degree": "Bacharelado", "end": "2022"}],
    )
    base.update(overrides)
    return ResumeDocument.model_validate(base)


class TestEmptyDiffSkipsAdjudication:
    async def test_identical_document_never_calls_the_llm(self, fake_llm) -> None:
        profile = _profile()
        proposal = await propose_merge(profile, _doc())

        assert proposal.ops == []
        assert proposal.diff_summary == []
        assert fake_llm.call_count == 0


class TestAdjudicationBuildsValidatedOps:
    async def test_new_skill_becomes_an_applied_patch_op(self, fake_llm) -> None:
        profile = _profile(skills=["React"])
        extracted = _doc(skills=["React", "Rust"])
        fake_llm.queue(
            json.dumps(
                [
                    {
                        "op": "add",
                        "path": "/skills/-",
                        "value": "Rust",
                        "reason": "New skill found in the uploaded document.",
                        "confidence": 0.9,
                        "sourceExcerpt": "Proficient in Rust.",
                    }
                ]
            )
        )

        proposal = await propose_merge(profile, extracted)

        assert fake_llm.call_count == 1
        assert len(proposal.ops) == 1
        assert proposal.ops[0].path == "/skills/-"
        assert proposal.ops[0].value == "Rust"
        assert any("rust" in line.lower() for line in proposal.diff_summary)

    async def test_ops_wrapped_in_code_fence_are_parsed(self, fake_llm) -> None:
        profile = _profile(skills=["React"])
        extracted = _doc(skills=["React", "Rust"])
        fake_llm.queue(
            "```json\n"
            + json.dumps(
                [
                    {
                        "op": "add",
                        "path": "/skills/-",
                        "value": "Rust",
                        "reason": "new skill",
                        "confidence": 0.9,
                        "sourceExcerpt": "Rust",
                    }
                ]
            )
            + "\n```"
        )

        proposal = await propose_merge(profile, extracted)
        assert len(proposal.ops) == 1

    async def test_ops_wrapped_in_a_top_level_ops_object_are_parsed(self, fake_llm) -> None:
        # _parse_patch_ops tolerates {"ops": [...]} as well as a bare JSON array -- some models
        # wrap the array in an object even when told "JSON array only" (same defensive
        # unwrapping style as resume_json_parser's _unwrap_resume_dict).
        profile = _profile(skills=["React"])
        extracted = _doc(skills=["React", "Rust"])
        fake_llm.queue(
            json.dumps(
                {
                    "ops": [
                        {
                            "op": "add",
                            "path": "/skills/-",
                            "value": "Rust",
                            "reason": "new skill",
                            "confidence": 0.9,
                            "sourceExcerpt": "Rust",
                        }
                    ]
                }
            )
        )

        proposal = await propose_merge(profile, extracted)

        assert len(proposal.ops) == 1
        assert proposal.ops[0].value == "Rust"


class TestAdjudicationContainmentEndToEnd:
    """CONTEXT.md: Adjudication -- "the LLM never touches what the Deterministic Diff didn't
    flag". A FakeLlm scripted to misbehave must never get its hallucinated/forbidden ops into
    ``proposal.ops`` -- and the underlying profile is never touched at this stage regardless
    (propose_merge only ever dry-runs the Patch Validator)."""

    async def test_op_outside_the_diff_scope_is_dropped(self, fake_llm) -> None:
        profile = _profile()
        # Only the skill is new/divergent -- experience[0] was never flagged.
        extracted = _doc(skills=["React", "TypeScript", "Rust"])
        fake_llm.queue(
            json.dumps(
                [
                    {
                        "op": "add",
                        "path": "/skills/-",
                        "value": "Rust",
                        "reason": "legit",
                        "confidence": 0.9,
                        "sourceExcerpt": "Rust",
                    },
                    {
                        "op": "replace",
                        "path": "/experience/0/title",
                        "value": "Hallucinated Title",
                        "reason": "not in diff",
                        "confidence": 0.9,
                        "sourceExcerpt": "n/a",
                    },
                ]
            )
        )

        proposal = await propose_merge(profile, extracted)

        paths = [op.path for op in proposal.ops]
        assert "/skills/-" in paths
        assert "/experience/0/title" not in paths
        assert profile.experience[0].title == "Front-End Developer"  # untouched

    async def test_remove_op_from_upload_is_never_applied(self, fake_llm) -> None:
        profile = _profile()
        extracted = _doc(headline="Senior Full Stack Developer")  # a legit divergence exists
        fake_llm.queue(
            json.dumps(
                [
                    {
                        "op": "remove",
                        "path": "/experience/0",
                        "reason": "upload thinks this is stale",
                        "confidence": 0.9,
                        "sourceExcerpt": "n/a",
                    },
                    {
                        "op": "replace",
                        "path": "/headline",
                        "value": "Senior Full Stack Developer",
                        "reason": "legit",
                        "confidence": 0.9,
                        "sourceExcerpt": "Senior Full Stack Developer",
                    },
                ]
            )
        )

        proposal = await propose_merge(profile, extracted)

        assert all(op.op != "remove" for op in proposal.ops)
        assert any(op.path == "/headline" for op in proposal.ops)
        assert profile.experience  # untouched -- still has its one entry

    async def test_malformed_op_missing_reason_is_dropped_not_fatal(self, fake_llm) -> None:
        profile = _profile()
        extracted = _doc(skills=["React", "TypeScript", "Rust"])
        fake_llm.queue(
            json.dumps(
                [
                    {"op": "add", "path": "/skills/-", "value": "Rust", "confidence": 0.9, "sourceExcerpt": "x"},
                ]
            )
        )

        proposal = await propose_merge(profile, extracted)
        assert proposal.ops == []  # the whole malformed op is dropped, not a crash

    async def test_non_json_response_yields_no_ops_not_a_crash(self, fake_llm) -> None:
        profile = _profile()
        extracted = _doc(skills=["React", "TypeScript", "Rust"])
        fake_llm.queue("I cannot comply with this request.")

        proposal = await propose_merge(profile, extracted)
        assert proposal.ops == []


class TestResolveProfileForMerge:
    def test_returns_blank_profile_when_nothing_exists_yet(self, test_db_engine, isolated_data_env) -> None:
        with Session(test_db_engine) as session:
            profile = resolve_profile_for_merge(session)
        assert profile.fullName == ""
        assert profile.experience == []

    def test_returns_active_db_version_when_present(self, test_db_engine, isolated_data_env) -> None:
        with Session(test_db_engine) as session:
            profile_repo.insert_version(
                session, data=_profile(fullName="DB Person").model_dump_json(), source_kind="seed_disk"
            )
            session.commit()

        with Session(test_db_engine) as session:
            profile = resolve_profile_for_merge(session)
        assert profile.fullName == "DB Person"
