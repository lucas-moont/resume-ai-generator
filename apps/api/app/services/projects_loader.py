import json
from pathlib import Path

import frontmatter
import yaml

from app.models import ProfileMaster


def load_profile(path: Path) -> ProfileMaster:
    if not path.is_file():
        from app.config import profile_json_candidates_message

        raise FileNotFoundError(
            f"Missing profile JSON at {path}.\n"
            f"Create one of:\n  {profile_json_candidates_message()}\n"
            f"Copy from data/examples/profile/resume.example.json (see README)."
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    return ProfileMaster.model_validate(raw)


def looks_like_placeholder_profile(profile: ProfileMaster) -> bool:
    full_name = (profile.fullName or "").strip().lower()
    summary = (profile.summary or "").strip().lower()
    sample_markers = (
        "alex sample",
        "replace this text with your real summary",
        "example corp",
        "sample university",
    )
    if full_name in {"alex sample", "sample"}:
        return True
    return any(marker in summary for marker in sample_markers)


def load_project_markdown_files(projects_dir: Path) -> list[dict]:
    if not projects_dir.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(projects_dir.glob("*.md")):
        if p.name.startswith("."):
            continue
        post = frontmatter.load(p)
        meta = post.metadata or {}
        if not meta.get("name"):
            meta["name"] = p.stem.replace("-", " ").title()
        out.append(
            {
                "slug": p.stem,
                "path": str(p),
                "frontmatter": meta,
                "body": post.content.strip(),
            }
        )
    return out


def projects_to_context_string(entries: list[dict]) -> str:
    parts: list[str] = []
    for e in entries:
        fm = e["frontmatter"]
        header = yaml.safe_dump(fm, allow_unicode=True, default_flow_style=False).strip()
        parts.append(f"### Project file: {e['slug']}\n---\n{header}\n---\n{e['body']}\n")
    return "\n".join(parts) if parts else "(no local project markdown files)"
