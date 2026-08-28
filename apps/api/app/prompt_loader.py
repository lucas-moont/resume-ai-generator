from pathlib import Path


def load_prompt(rel_path: str, prompts_dir: Path) -> str:
    p = prompts_dir / rel_path
    if not p.is_file():
        raise FileNotFoundError(f"Prompt file missing: {p}")
    return p.read_text(encoding="utf-8")


def load_generate_system_prompt(prompts_dir: Path) -> str:
    return "\n\n---\n\n".join(
        [
            load_prompt("system/generate.md", prompts_dir),
            load_prompt("skills/resume-craft.md", prompts_dir),
            load_prompt("skills/tailored-resume-generator.md", prompts_dir),
            load_prompt("skills/humanizer.md", prompts_dir),
        ]
    )


def load_refine_system_prompt(prompts_dir: Path) -> str:
    """Refine system prompt composed with the shared resume-craft skill block, so a
    chat refine (and the post-generation auto-improve pass) applies the same bullet /
    quantification / ATS craft as generation. ``system/refine.md`` still owns the
    refine-specific rules (apply the user's request precisely, the ask-instead-of-guessing
    valve, project-source honesty). The humanizer block keeps revised prose from drifting
    into AI-slop wording."""
    return "\n\n---\n\n".join(
        [
            load_prompt("system/refine.md", prompts_dir),
            load_prompt("skills/resume-craft.md", prompts_dir),
            load_prompt("skills/humanizer.md", prompts_dir),
        ]
    )


def load_linkedin_analysis_system_prompt(prompts_dir: Path) -> str:
    """v5 (Profile Analysis): the standalone system prompt for an Analysis Turn. Not composed
    with generate/refine -- the analysis motor is its own read-only advisor (returns either an
    Analysis or a Clarifying Question), never emitting the resume JSON. Composed with the
    humanizer block so the LinkedIn copy it suggests reads human, not chatbot."""
    return "\n\n---\n\n".join(
        [
            load_prompt("skills/linkedin-analysis.md", prompts_dir),
            load_prompt("skills/humanizer.md", prompts_dir),
        ]
    )


def load_extract_profile_system_prompt(prompts_dir: Path) -> str:
    return load_prompt("system/extract_profile.md", prompts_dir)


def load_merge_profile_system_prompt(prompts_dir: Path) -> str:
    return load_prompt("system/merge_profile.md", prompts_dir)


def load_profile_update_system_prompt(prompts_dir: Path) -> str:
    return load_prompt("system/profile_update.md", prompts_dir)


def load_propose_improvements_system_prompt(prompts_dir: Path) -> str:
    return load_prompt("system/propose_improvements.md", prompts_dir)


def load_proposal_turn_system_prompt(prompts_dir: Path) -> str:
    return load_prompt("system/proposal_turn.md", prompts_dir)


def load_converse_system_prompt(prompts_dir: Path) -> str:
    """The read-only conversation turn's system prompt. Composed with the humanizer block like
    generate/refine, because this lane authors prose the user reads (an answer, a qualification
    summary, a cover letter) and it must not drift into chatbot wording. Not composed with
    resume-craft: it never emits the resume JSON that block exists to shape."""
    return "\n\n---\n\n".join(
        [
            load_prompt("system/converse.md", prompts_dir),
            load_prompt("skills/humanizer.md", prompts_dir),
        ]
    )


def load_job_fit_system_prompt(prompts_dir: Path) -> str:
    """v7 (Job Monitor): stage 2 of the Fit Score -- Profile x Job Listing, one number out.

    Deliberately NOT composed with ``resume-craft``/``humanizer`` like the prompts above. Those
    blocks exist to make PROSE good, and this call produces no prose at all: the contract is
    ``{"fit": 0-100}`` with the justification explicitly discarded (CONTEXT.md: Fit Score, "a
    percentage only -- no written justification"). Composing them in would be craft guidance
    the model cannot use, paid for on up to ``FIT_LLM_TOP_N`` calls per Scan.
    """
    return load_prompt("skills/job-fit.md", prompts_dir)
