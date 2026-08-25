from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any
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

# Claude output budget for the resume JSON (kept non-streaming; a full resume fits well under this).
CLAUDE_MAX_OUTPUT_TOKENS = _env_int("CLAUDE_MAX_OUTPUT_TOKENS", 8192, minimum=1024, maximum=32768)
# Extended thinking for Claude: "off" (default) keeps the whole token budget for the JSON and is
# fastest/cheapest; "adaptive" lets Claude reason first (raise CLAUDE_MAX_OUTPUT_TOKENS if you do).
CLAUDE_THINKING = os.getenv("CLAUDE_THINKING", "off").strip().lower() or "off"


# --- Runtime AI settings (v3 ticket 01) ------------------------------------------------------
#
# AI_PROVIDER, AI_DEFAULT_MODEL, the provider API keys, and DEFAULT_{CLAUDE,GEMINI,OLLAMA}_MODEL
# used to be frozen at import time above -- a settings write at runtime (future
# PUT /api/settings/providers|keys, v3 ticket 03) would silently have no effect without a
# process restart. Below, each is a call-time accessor instead, and get_runtime_config()
# bundles them for the LLM modules (resolver, clients, model catalog) to read module-qualified
# (``config_module.get_runtime_config()``), matching the pattern resolve_uploads_dir already
# uses for DATA_UPLOADS_DIR.
#
# Precedence, matching docs/v3-agnostic-settings.md Backend-1/2:
#   - provider/model preferences: env var -> app_settings row -> hardcoded default.
#   - API keys: env var -> OS keychain (resolve_secret) -- NEVER app_settings/SQLite.
#
# app_settings reads/writes go through main.py's lifespan-owned engine (app.state.db_engine),
# wired in via set_settings_engine -- a second Engine object on the same on-disk SQLite file
# would otherwise get built the first time a setting is resolved. The lazy path in
# _get_settings_engine below is only a fallback for callers outside the FastAPI app (a
# standalone script, or a test that doesn't go through tests/conftest.py's
# isolated_runtime_settings_engine fixture); tests inject an isolated in-memory engine via
# set_settings_engine so no test ever touches the real data/app.db.

_settings_engine: Any = None
_settings_engine_lock = Lock()
_app_settings_cache: dict[str, Any] | None = None
_app_settings_cache_lock = Lock()


def set_settings_engine(engine: Any) -> None:
    """Test seam (module-qualified, like resolve_uploads_dir) -- also called by main.py's
    lifespan with its own app.state.db_engine, so production never falls through to the lazy
    fallback below. Pass ``None`` to reset to that lazy on-demand default."""
    global _settings_engine
    with _settings_engine_lock:
        _settings_engine = engine
    invalidate_runtime_config_cache()


def _get_settings_engine() -> Any:
    global _settings_engine
    if _settings_engine is None:
        # Double-checked locking: two concurrent first callers (fallback path only -- see the
        # comment above) must not each build their own Engine+pool on the same file.
        with _settings_engine_lock:
            if _settings_engine is None:
                # Local import: app.db.engine imports this module at top level, so importing
                # it back here at module scope would be a circular import. Deferred to call
                # time, it resolves fine because both modules are already fully loaded by then.
                from app.db.engine import create_db_engine, init_db

                engine = create_db_engine()
                init_db(engine)
                _settings_engine = engine
    return _settings_engine


def invalidate_runtime_config_cache() -> None:
    """Called after every app_settings write (set_app_setting/delete_app_setting) so the very
    next get_runtime_config() call re-reads the table instead of serving a stale value."""
    global _app_settings_cache
    with _app_settings_cache_lock:
        _app_settings_cache = None


def _app_settings() -> dict[str, Any]:
    global _app_settings_cache
    with _app_settings_cache_lock:
        if _app_settings_cache is None:
            from sqlmodel import Session

            from app.repositories import app_settings_repo

            with Session(_get_settings_engine()) as session:
                _app_settings_cache = app_settings_repo.get_all(session)
        return _app_settings_cache


def _app_setting_str(key: str) -> str | None:
    value = _app_settings().get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def set_app_setting(key: str, value: Any) -> None:
    """Write a non-sensitive runtime preference (e.g. ``ai_provider``) and invalidate the
    cache so it takes effect on the very next get_runtime_config() call -- no restart, no
    module reload. API keys never go through this path; see secret_store.store_secret."""
    from sqlmodel import Session

    from app.repositories import app_settings_repo

    with Session(_get_settings_engine()) as session:
        app_settings_repo.set(session, key, value)
        session.commit()
    invalidate_runtime_config_cache()


def delete_app_setting(key: str) -> None:
    from sqlmodel import Session

    from app.repositories import app_settings_repo

    with Session(_get_settings_engine()) as session:
        app_settings_repo.delete(session, key)
        session.commit()
    invalidate_runtime_config_cache()


# v3 ticket 11 fix round: hoisted above the resolvers (previously declared below them with the
# names re-typed inline in each resolver) so "which env var backs which preference" has exactly
# one source of truth -- the resolvers below and settings_service's lock indicator both read
# through these instead of a resolver's own literal drifting from is_env_locked's.
AI_PROVIDER_ENV_VAR = "AI_PROVIDER"
_DEFAULT_MODEL_ENV_VARS: dict[str, str] = {
    "claude": "CLAUDE_MODEL",
    "gemini": "GEMINI_MODEL",
    "ollama": "OLLAMA_MODEL",
}


def default_model_env_var(provider: str) -> str:
    """The env var that pins `default_{provider}_model` (see resolve_default_*_model below)."""
    try:
        return _DEFAULT_MODEL_ENV_VARS[provider]
    except KeyError:
        valid = ", ".join(sorted(_DEFAULT_MODEL_ENV_VARS))
        raise ValueError(f"Unknown provider {provider!r} -- expected one of: {valid}") from None


def is_env_locked(var_name: str) -> bool:
    """Cheap call-time check (module-qualified, same idiom as the resolve_* accessors below):
    true when `var_name` is set (non-empty) in the environment, meaning the runtime-config
    field it backs is pinned there -- a settings write to it has no visible effect until the
    var is unset (the P2 QA gate bug ticket 11 surfaces in the UI instead of hiding)."""
    return bool(os.getenv(var_name, "").strip())


def resolve_ai_provider() -> str:
    env_value = os.getenv(AI_PROVIDER_ENV_VAR, "").strip().lower()
    if env_value:
        return env_value
    stored = _app_setting_str("ai_provider")
    return stored.lower() if stored else "auto"


def resolve_ai_default_model() -> str | None:
    env_value = os.getenv("AI_DEFAULT_MODEL", "").strip()
    if env_value:
        return env_value
    return _app_setting_str("ai_default_model")


def resolve_anthropic_api_key() -> str | None:
    return resolve_secret("ANTHROPIC_API_KEY")


def resolve_gemini_api_key() -> str | None:
    return resolve_secret("GEMINI_API_KEY")


def resolve_github_token() -> str | None:
    return resolve_secret("GITHUB_TOKEN")


def resolve_default_claude_model() -> str:
    env_value = os.getenv(_DEFAULT_MODEL_ENV_VARS["claude"], "").strip()
    if env_value:
        return env_value
    return _app_setting_str("default_claude_model") or "claude-sonnet-5"


def resolve_default_gemini_model() -> str:
    env_value = os.getenv(_DEFAULT_MODEL_ENV_VARS["gemini"], "").strip()
    if env_value:
        return env_value
    return _app_setting_str("default_gemini_model") or "gemini-2.5-flash"


def resolve_default_ollama_model() -> str:
    env_value = os.getenv(_DEFAULT_MODEL_ENV_VARS["ollama"], "").strip()
    if env_value:
        return env_value
    return _app_setting_str("default_ollama_model") or "llama3.2"


@dataclass(frozen=True)
class RuntimeConfig:
    ai_provider: str
    ai_default_model: str | None
    # repr=False: a stray `logger.info(f"{runtime}")`/log line must not leak either key.
    anthropic_api_key: str | None = field(repr=False)
    default_claude_model: str
    gemini_api_key: str | None = field(repr=False)
    default_gemini_model: str
    default_ollama_model: str


def get_runtime_config() -> RuntimeConfig:
    """The call-time replacement for the AI constants that used to be frozen at import time.
    Cheap to call repeatedly: the app_settings-backed fields come from the cache above (one DB
    read until the next write); API keys are resolved fresh every call (resolve_secret is just
    an env/keyring lookup, no DB) so a key added via the keychain mid-process is picked up
    immediately without needing its own cache-invalidation wiring.
    """
    return RuntimeConfig(
        ai_provider=resolve_ai_provider(),
        ai_default_model=resolve_ai_default_model(),
        anthropic_api_key=resolve_anthropic_api_key(),
        default_claude_model=resolve_default_claude_model(),
        gemini_api_key=resolve_gemini_api_key(),
        default_gemini_model=resolve_default_gemini_model(),
        default_ollama_model=resolve_default_ollama_model(),
    )


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


# --- Job Monitor / Scan engine (v7 ticket 07) -------------------------------------------------
#
# Call-time accessors, not import-time constants -- the same discipline as ``max_upload_bytes``
# and ``resolve_uploads_dir`` above, so a test can set the env var with ``monkeypatch.setenv``
# and have it take effect without reloading this module. Everything the USER chooses (interval,
# boards, applicant cap) lives in the Search Profile instead; only knobs nobody should have to
# think about are here.


def scan_check_interval_seconds() -> int:
    """How long the scheduler sleeps between two reads of the Search Profile's interval.

    It is NOT the scan interval: it is the granularity at which a change to that interval (or
    switching it off) takes effect, and the poll that decides whether the next scheduled Scan
    is due. Same philosophy as the Runtime Config -- a setting written in the UI applies on the
    next loop, with no restart.
    """
    return _env_int("SCAN_CHECK_INTERVAL_SECONDS", 60, minimum=1, maximum=3600)


def scan_results_wanted() -> int:
    """``BoardQuery.results_wanted``: the cap on postings ONE board should return for one Scan.

    Per board, not per Scan (the frozen contract says so), and the JobSpy adapter divides it
    further across the role x location grid it fans out into -- it is that board's whole budget
    for the query, which is what keeps a five-role Search Profile from turning into a burst.
    """
    return _env_int("SCAN_RESULTS_WANTED", 50, minimum=1, maximum=200)


def scan_scheduler_enabled() -> bool:
    """Whether ``main.py``'s lifespan starts the background Scan scheduler.

    On by default -- an interval of ``None`` ("off") in the Search Profile is how a USER stops
    scheduled Scans, and it is the state a fresh install is in, so the switch here is not the
    product's off button. It exists for the test suite: two integration tests drive
    ``app.main.lifespan`` directly (``test_db_lifespan``, ``test_reaper_startup``), and a real
    scheduler task reaching real Job Boards from those is exactly what CLAUDE.md forbids.
    ``tests/conftest.py`` sets it to ``0`` for every test; the scheduler's own tests build a
    ``ScanScheduler`` directly instead of going through the lifespan.
    """
    raw = os.getenv("SCAN_SCHEDULER_ENABLED", "").strip().lower()
    if not raw:
        return True
    return raw not in {"0", "false", "no", "off"}


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
