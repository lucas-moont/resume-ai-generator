"""Unit tests for app/domain/profile_patch.py (v2 ticket 02).

PatchOp (restricted JSON-Patch subset) and the Patch Validator -- the only gate a proposed
change crosses before becoming a new Profile Version (CONTEXT.md: Patch Op, Patch Validator,
Upload-never-removes). Pure module: no I/O, no DB, no LLM; every case applies ops onto an
in-memory ProfileMaster.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.profile_patch import (
    PatchOp,
    PatchValidationFailed,
    apply_patch,
)
from app.domain.schemas import ProfileMaster


def _profile(**overrides) -> ProfileMaster:
    base = dict(
        fullName="Lucas Monteiro",
        headline="Full Stack Developer",
        summary="Base summary.",
        location="São Paulo, BR",
        email="lucas@example.com",
        phone="+55 11 90000-0000",
        locale="pt-BR",
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
        education=[{"institution": "Cruzeiro do Sul", "degree": "ADS", "end": "2022"}],
        projects=[{"name": "Resume Agent", "description": "This very app."}],
        links=[{"label": "GitHub", "url": "https://github.com/lucas"}],
    )
    base.update(overrides)
    return ProfileMaster.model_validate(base)


def _op(**overrides) -> PatchOp:
    base = dict(
        op="replace",
        path="/summary",
        value="Updated summary.",
        reason="user requested update",
        confidence=0.9,
        sourceExcerpt="chat: 'update my summary'",
    )
    base.update(overrides)
    return PatchOp.model_validate(base)


class TestPatchOpConstruction:
    def test_valid_op_constructs(self) -> None:
        op = _op()
        assert op.op == "replace"
        assert op.path == "/summary"

    @pytest.mark.parametrize(
        "bad_path",
        [
            "/notAField",
            "/githubUsername",
            "/experience",  # missing index
            "/experience/-1/title",
            "/experience/0/__proto__",
            "../../../etc/passwd",
            "summary",  # missing leading slash
            "",
            "/experience/0/highlights/-/../0",
        ],
    )
    def test_rejects_paths_outside_whitelist(self, bad_path: str) -> None:
        with pytest.raises(ValidationError):
            _op(path=bad_path)

    def test_accepts_all_documented_path_shapes(self) -> None:
        for path in (
            "/fullName",
            "/headline",
            "/location",
            "/email",
            "/phone",
            "/summary",
            "/locale",
            "/skills/-",
            "/skills/0",
            "/experience/-",
            "/experience/0",
            "/experience/0/title",
            "/experience/0/highlights/-",
            "/experience/0/highlights/0",
            "/education/-",
            "/education/0",
            "/education/0/degree",
            "/projects/-",
            "/projects/0",
            "/projects/0/description",
            "/links/-",
            "/links/0",
            "/links/0/url",
        ):
            _op(path=path, op="add" if path.endswith("-") else "replace")  # must not raise

    def test_confidence_out_of_bounds_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _op(confidence=1.5)
        with pytest.raises(ValidationError):
            _op(confidence=-0.1)

    def test_blank_reason_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _op(reason="   ")

    def test_blank_source_excerpt_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _op(sourceExcerpt="")

    def test_add_or_replace_requires_a_value(self) -> None:
        with pytest.raises(ValidationError):
            _op(op="replace", value=None)
        with pytest.raises(ValidationError):
            _op(op="add", path="/skills/-", value=None)

    def test_remove_does_not_require_a_value(self) -> None:
        op = _op(op="remove", path="/skills/0", value=None)
        assert op.value is None


class TestApplyPatchScalars:
    def test_replace_scalar_field(self) -> None:
        profile = _profile()
        result = apply_patch(profile, [_op(path="/headline", value="Senior Engineer")], source_kind="chat")
        assert result.profile.headline == "Senior Engineer"
        assert len(result.applied) == 1
        assert result.skipped == []
        # original untouched (applied on a copy)
        assert profile.headline == "Full Stack Developer"

    def test_add_scalar_field_is_an_upsert(self) -> None:
        profile = _profile(phone=None)
        result = apply_patch(
            profile,
            [_op(op="add", path="/phone", value="+55 11 98888-0000")],
            source_kind="manual",
        )
        assert result.profile.phone == "+55 11 98888-0000"

    def test_remove_scalar_field_clears_it(self) -> None:
        profile = _profile()
        result = apply_patch(profile, [_op(op="remove", path="/phone", value=None)], source_kind="manual")
        assert result.profile.phone is None


class TestApplyPatchEntityLists:
    def test_append_new_experience(self) -> None:
        profile = _profile()
        new_role = {
            "company": "Acme",
            "title": "Engineer",
            "start": "2020-01",
            "end": "2024-12",
            "highlights": ["Did things"],
        }
        result = apply_patch(
            profile,
            [_op(op="add", path="/experience/-", value=new_role, reason="new role from upload")],
            source_kind="upload",
        )
        assert len(result.profile.experience) == 2
        assert result.profile.experience[1].company == "Acme"

    def test_replace_experience_subfield(self) -> None:
        profile = _profile()
        result = apply_patch(
            profile,
            [_op(path="/experience/0/title", value="Staff Engineer")],
            source_kind="chat",
        )
        assert result.profile.experience[0].title == "Staff Engineer"
        # sibling fields untouched
        assert result.profile.experience[0].company == "SmartHow"

    def test_append_highlight_to_existing_experience(self) -> None:
        profile = _profile()
        result = apply_patch(
            profile,
            [_op(op="add", path="/experience/0/highlights/-", value="Led a migration")],
            source_kind="chat",
        )
        assert result.profile.experience[0].highlights == [
            "Shipped the v1 chat experience",
            "Led a migration",
        ]

    def test_remove_experience_by_index_via_chat(self) -> None:
        profile = _profile()
        result = apply_patch(profile, [_op(op="remove", path="/experience/0", value=None)], source_kind="chat")
        assert result.profile.experience == []
        assert len(result.applied) == 1

    def test_remove_via_manual_edit_allowed(self) -> None:
        profile = _profile()
        result = apply_patch(profile, [_op(op="remove", path="/skills/0", value=None)], source_kind="manual")
        assert result.profile.skills == ["TypeScript"]


class TestUploadNeverRemoves:
    def test_remove_via_upload_is_rejected_not_fatal(self) -> None:
        profile = _profile()
        ops = [
            _op(op="remove", path="/experience/0", value=None, reason="upload thinks stale"),
            _op(op="add", path="/skills/-", value="GraphQL", reason="upload found a new skill"),
        ]
        result = apply_patch(profile, ops, source_kind="upload")
        # the remove is skipped, but the unrelated add still goes through
        assert len(result.profile.experience) == 1
        assert "GraphQL" in result.profile.skills
        assert len(result.applied) == 1
        assert len(result.skipped) == 1
        assert "upload" in result.skipped[0].reason.lower()

    def test_remove_via_upload_rejected_even_for_scalar_paths(self) -> None:
        profile = _profile()
        result = apply_patch(
            profile, [_op(op="remove", path="/phone", value=None)], source_kind="upload"
        )
        assert result.profile.phone == profile.phone
        assert len(result.skipped) == 1


class TestOutOfBoundsTargets:
    def test_replace_out_of_bounds_index_is_skipped_not_fatal(self) -> None:
        profile = _profile()
        ops = [
            _op(path="/experience/5/title", value="Ghost Role"),
            _op(path="/headline", value="Still Works"),
        ]
        result = apply_patch(profile, ops, source_kind="chat")
        assert result.profile.headline == "Still Works"
        assert len(result.applied) == 1
        assert len(result.skipped) == 1

    def test_remove_out_of_bounds_index_is_skipped(self) -> None:
        profile = _profile()
        result = apply_patch(profile, [_op(op="remove", path="/education/9", value=None)], source_kind="chat")
        assert len(result.profile.education) == 1
        assert len(result.skipped) == 1

    def test_add_with_explicit_index_is_skipped_only_dash_append_supported(self) -> None:
        profile = _profile()
        result = apply_patch(
            profile,
            [_op(op="add", path="/experience/0", value={"company": "X", "title": "Y", "start": "2020"})],
            source_kind="chat",
        )
        assert len(result.skipped) == 1
        assert len(result.profile.experience) == 1


class TestSanitizationChokePoint:
    def test_added_summary_is_sanitized_like_parse_resume_json(self) -> None:
        profile = _profile()
        raw = "<script>alert(1)</script>Uses **Next.js** daily."
        result = apply_patch(profile, [_op(path="/summary", value=raw)], source_kind="chat")
        assert "<script>" not in result.profile.summary
        assert "<strong>Next.js</strong>" in result.profile.summary

    def test_added_highlight_is_sanitized(self) -> None:
        profile = _profile()
        raw = "<img src=x onerror=alert(1)>Shipped **auth**"
        result = apply_patch(
            profile,
            [_op(op="add", path="/experience/0/highlights/-", value=raw)],
            source_kind="chat",
        )
        added = result.profile.experience[0].highlights[-1]
        assert "onerror" not in added
        assert "<strong>auth</strong>" in added


class TestFinalSchemaValidationIsMandatory:
    def test_type_mismatched_value_fails_the_whole_patch(self) -> None:
        profile = _profile()
        ops = [_op(path="/summary", value={"not": "a string"})]
        with pytest.raises(PatchValidationFailed):
            apply_patch(profile, ops, source_kind="chat")
