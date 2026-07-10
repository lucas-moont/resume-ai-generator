from pathlib import Path
import os

from dotenv import load_dotenv

from app.services.secret_store import resolve_secret

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
GITHUB_TOKEN = resolve_secret("GITHUB_TOKEN")

# SQLite persistence (B5). ``.as_posix()`` keeps the URL forward-slashed even on Windows,
# where DATA_DIR resolves to e.g. C:\Users\...\data -- SQLAlchemy's sqlite dialect wants
# "sqlite:///C:/Users/.../data/app.db", not backslashes.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip() or f"sqlite:///{DATA_DIR.as_posix()}/app.db"


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, min(maximum, int(raw)))
    except ValueError:
        return default


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, min(maximum, float(raw)))
    except ValueError:
        return default


# Generation tuning (shared intent across providers).
LLM_TEMPERATURE = _env_float("LLM_TEMPERATURE", 0.4, minimum=0.0, maximum=1.5)
# Ollama context window: default output/input models truncate long prompts (profile + PDF +
# projects) at 2k-4k tokens, silently lowering quality. Raise the window and output budget.
OLLAMA_NUM_CTX = _env_int("OLLAMA_NUM_CTX", 8192, minimum=2048, maximum=131072)
OLLAMA_NUM_PREDICT = _env_int("OLLAMA_NUM_PREDICT", 4096, minimum=512, maximum=32768)
# Gemini output budget (a full resume JSON can exceed the small implicit default).
GEMINI_MAX_OUTPUT_TOKENS = _env_int("GEMINI_MAX_OUTPUT_TOKENS", 8192, minimum=1024, maximum=65536)
# Per LLM call: stream heartbeat timeout and HTTP client timeout (local models can be slow).
LLM_TIMEOUT_SECONDS = _env_int("LLM_TIMEOUT_SECONDS", 900, minimum=60, maximum=3600)

AI_PROVIDER = os.getenv("AI_PROVIDER", "auto").strip().lower() or "auto"
AI_DEFAULT_MODEL = os.getenv("AI_DEFAULT_MODEL", "").strip() or None

GEMINI_API_KEY = resolve_secret("GEMINI_API_KEY")
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"

# Anthropic / Claude. Resolved from env var, then the OS keychain. When present it both lets
# AI_PROVIDER=auto pick Claude and is passed explicitly to the SDK. When absent, the client is
# built bare so the SDK uses a local `ant auth login` OAuth session — no variable needed here.
ANTHROPIC_API_KEY = resolve_secret("ANTHROPIC_API_KEY")
DEFAULT_CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5").strip() or "claude-sonnet-5"
# Claude output budget for the resume JSON (kept non-streaming; a full resume fits well under this).
CLAUDE_MAX_OUTPUT_TOKENS = _env_int("CLAUDE_MAX_OUTPUT_TOKENS", 8192, minimum=1024, maximum=32768)
# Extended thinking for Claude: "off" (default) keeps the whole token budget for the JSON and is
# fastest/cheapest; "adaptive" lets Claude reason first (raise CLAUDE_MAX_OUTPUT_TOKENS if you do).
CLAUDE_THINKING = os.getenv("CLAUDE_THINKING", "off").strip().lower() or "off"


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


def resolve_uploads_dir() -> Path:
    """Where uploaded Source Document bytes live (v2 ticket 03), read at CALL time (module-
    qualified) like ``resolve_profile_json_path`` above -- so tests can monkeypatch
    ``DATA_UPLOADS_DIR`` per-test (see tests/conftest.py's ``isolated_data_env``) without any
    module needing to re-import this file."""
    override = os.getenv("DATA_UPLOADS_DIR", "").strip()
    if override:
        p = Path(override).expanduser()
        return p if p.is_absolute() else (ROOT_DIR / p).resolve()
    return DATA_DIR / "uploads"


def max_upload_bytes() -> int:
    return _env_int("MAX_UPLOAD_BYTES", 10 * 1024 * 1024, minimum=1024, maximum=100 * 1024 * 1024)


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
