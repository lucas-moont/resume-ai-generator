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
            load_prompt("skills/tailored-resume-generator.md", prompts_dir),
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
