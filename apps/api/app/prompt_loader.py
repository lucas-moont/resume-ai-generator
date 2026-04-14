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
