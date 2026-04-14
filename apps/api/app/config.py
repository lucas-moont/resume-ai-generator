from pathlib import Path
import os

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / ".env")
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT_DIR / "data"))).resolve()
PROFILE_DIR = DATA_DIR / "profile"
PROJECTS_DIR = DATA_DIR / "projects"
EXAMPLES_DIR = DATA_DIR / "examples"
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip() or None

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip() or None
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"


def resolve_profile_json_path() -> Path:
    override = os.getenv("PROFILE_JSON_PATH", "").strip()
    if override:
        p = Path(override).expanduser()
        if not p.is_absolute():
            p = (ROOT_DIR / p).resolve()
        else:
            p = p.resolve()
        return p
    candidates = [
        PROFILE_DIR / "resume.json",
        PROFILE_DIR / "Profile.json",
        DATA_DIR / "profile_master.json",
    ]
    for c in candidates:
        if c.is_file():
            return c.resolve()
    return (PROFILE_DIR / "resume.json").resolve()


def resolve_profile_pdf_path() -> Path | None:
    override = os.getenv("PROFILE_PDF_PATH", "").strip()
    if override:
        p = Path(override).expanduser()
        if not p.is_absolute():
            p = (ROOT_DIR / p).resolve()
        else:
            p = p.resolve()
        return p if p.is_file() else None
    for name in ("Profile.pdf", "profile.pdf", "resume.pdf"):
        candidate = (PROFILE_DIR / name).resolve()
        if candidate.is_file():
            return candidate
    return None


def profile_pdf_max_chars() -> int:
    raw = os.getenv("PROFILE_PDF_MAX_CHARS", "32000").strip()
    try:
        return max(1000, min(200_000, int(raw)))
    except ValueError:
        return 32000


def profile_json_candidates_message() -> str:
    lines: list[str] = []
    o = os.getenv("PROFILE_JSON_PATH", "").strip()
    if o:
        lines.append(f"{o} (PROFILE_JSON_PATH)")
    lines.extend(
        [
            str(PROFILE_DIR / "resume.json"),
            str(PROFILE_DIR / "Profile.json"),
            str(DATA_DIR / "profile_master.json"),
        ]
    )
    return "\n  ".join(lines)
