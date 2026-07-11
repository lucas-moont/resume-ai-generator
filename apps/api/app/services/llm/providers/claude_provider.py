from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import anyio.to_thread

from app.services.llm.providers.base import AuthMode, ProviderContext, ProviderName

# NOTE: temperature / top_p are intentionally NOT sent. Claude Sonnet 5, Opus 4.8 and 4.7 reject
# sampling parameters (HTTP 400), so the shared LLM_TEMPERATURE does not apply to this provider.
#
# NOTE: when no ANTHROPIC_API_KEY is configured, requests are routed through the local `claude`
# CLI (headless `-p` print mode) instead of the `anthropic` SDK, so a logged-in Claude Code
# session can be used with no API key stored anywhere in this project (the SDK itself only ever
# reads ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN -- it cannot discover a local Claude Code
# session). The CLI manages its own thinking/output-token budget end-to-end, so
# claude_thinking/claude_max_output_tokens below apply only to the SDK path (i.e. only when an
# API key is configured) and have no equivalent knob on the CLI path.


def _thinking_config(thinking: str) -> dict:
    # "adaptive" lets Claude reason before answering; "off" (disabled) gives the full max_tokens
    # budget to the JSON output, which is what a resume-generation task wants by default.
    if thinking == "adaptive":
        return {"type": "adaptive"}
    return {"type": "disabled"}


def _extract_text(message) -> str:
    parts: list[str] = []
    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", "") or ""
            if text:
                parts.append(text)
    return "".join(parts).strip()


def _error_message(exc: Exception, model: str) -> str:
    status = getattr(exc, "status_code", None)
    detail = str(getattr(exc, "message", "") or exc).strip()
    hint = (
        "Authenticate with `ant auth login` (local Claude session) or set ANTHROPIC_API_KEY in .env, "
        f"and confirm your account can access the model (CLAUDE_MODEL='{model}')."
    )
    if status:
        return f"Claude API HTTP {status}: {detail or '(no message)'} {hint}"
    return f"Claude request failed: {detail or exc.__class__.__name__}. {hint}"


def _cli_error_message(detail: str, model: str) -> str:
    """Same shape/intent as _error_message, adapted for the `claude` CLI subprocess path.

    (The SDK path's hint references `ant auth login` / ANTHROPIC_API_KEY, which is correct for
    the `anthropic` SDK's own credential resolution. The CLI path has a different login flow --
    `claude auth login` -- so the hint is adapted accordingly rather than reused verbatim.)
    """
    hint = (
        "Run `claude auth login` to sign in to Claude Code (or `claude auth status` to check), "
        f"or set ANTHROPIC_API_KEY in .env, and confirm your account can access the model "
        f"(CLAUDE_MODEL='{model}')."
    )
    return f"Claude CLI request failed: {detail or '(no message)'} {hint}"


def _run_claude_cli_sync(system: str, user: str, model_name: str, timeout_seconds: int) -> str:
    """Blocking implementation of the `claude` CLI call -- run via anyio.to_thread.run_sync.

    asyncio.create_subprocess_exec is unreliable on Windows (the default SelectorEventLoop
    policy does not support subprocesses at all), so this shells out with the blocking
    subprocess.run inside a worker thread instead, which works regardless of event loop policy.
    """
    claude_path = shutil.which("claude")
    if not claude_path:
        raise RuntimeError(
            "The `claude` CLI was not found on PATH. Install Claude Code and sign in "
            "(https://claude.com/claude-code, then `claude auth login`) so this app can use "
            "your local session, or set ANTHROPIC_API_KEY in .env to call the Anthropic API "
            "directly instead."
        )

    # The system prompt goes to a file (not an argv string) and REPLACES the default Claude Code
    # agent system prompt via --system-prompt-file, giving a clean JSON-only response instead of
    # the full coding-agent persona. --exclude-dynamic-system-prompt-sections is NOT used here:
    # per `claude --help`, it only applies with the *default* system prompt and is a no-op once
    # a custom one is supplied.
    #
    # The file lives directly in the OS temp directory (not a subdirectory we create and then
    # try to rmdir) and the subprocess runs with that same OS temp directory as cwd -- a stable,
    # pre-existing neutral location, not the project root. This sidesteps a Windows-specific
    # gotcha: deleting a *directory* immediately after a child process exits can transiently fail
    # with PermissionError/WinError 32 if the OS hasn't yet released the child's handle to that
    # directory as its cwd. Only the (much less lock-prone) file needs cleanup afterwards.
    neutral_dir = tempfile.gettempdir()
    fd, system_prompt_path_str = tempfile.mkstemp(
        prefix="claude_system_prompt_", suffix=".txt", dir=neutral_dir
    )
    system_prompt_path = Path(system_prompt_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(system)

        cmd = [
            claude_path,
            "-p",
            "--output-format", "json",
            "--model", model_name,
            "--max-turns", "1",
            "--system-prompt-file", str(system_prompt_path),
            # This is a single-turn JSON-generation task with no need for file/bash tools or any
            # globally-configured MCP servers -- disabling both cuts input tokens drastically
            # (confirmed empirically: ~28K cached + ~7K input tokens with defaults vs. ~1.4K
            # input tokens and no cache writes with these flags for the same prompt).
            "--tools", "",
            "--strict-mcp-config",
            "--no-session-persistence",
        ]
        try:
            proc = subprocess.run(
                cmd,
                input=user,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=float(timeout_seconds),
                cwd=neutral_dir,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"Claude CLI request timed out after {timeout_seconds}s. Raise "
                "LLM_TIMEOUT_SECONDS in .env if this task genuinely needs more time."
            ) from e
        except OSError as e:
            raise RuntimeError(f"Failed to launch the `claude` CLI: {e}") from e
    finally:
        try:
            system_prompt_path.unlink(missing_ok=True)
        except OSError:
            pass  # best-effort cleanup; a transiently-locked temp file is reaped by the OS later

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    envelope: dict | None = None
    if stdout:
        try:
            envelope = json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            envelope = None

    if envelope is None:
        detail = stderr or stdout or f"process exited with code {proc.returncode}"
        raise RuntimeError(_cli_error_message(detail, model_name))

    is_error = bool(envelope.get("is_error"))
    subtype = envelope.get("subtype")
    if proc.returncode != 0 or is_error or subtype != "success":
        detail = str(envelope.get("result") or stderr or f"exit code {proc.returncode}")
        raise RuntimeError(_cli_error_message(detail, model_name))

    if envelope.get("stop_reason") == "refusal":
        raise RuntimeError(
            "Claude declined to answer this request (stop_reason=refusal). "
            "Adjust the profile or job description text and try again."
        )

    result = str(envelope.get("result") or "").strip()
    if not result:
        raise RuntimeError(
            f"Claude ('{model_name}') returned an empty response via the local Claude CLI "
            "session. If the output was cut off, try again; otherwise verify `claude auth "
            "status` shows you as logged in and that your account can use this model."
        )
    return result


async def _chat_json_claude_cli(system: str, user: str, model_name: str, timeout_seconds: int) -> str:
    return await anyio.to_thread.run_sync(
        _run_claude_cli_sync, system, user, model_name, timeout_seconds
    )


class ClaudeProvider:
    name: ProviderName = "claude"

    def __init__(self, ctx: ProviderContext) -> None:
        self._ctx = ctx

    @property
    def auth_mode(self) -> AuthMode:
        # No API key: route through the local `claude` CLI (headless -p mode) so a logged-in
        # Claude Code session is used directly, with no key stored anywhere in this project. See
        # the module docstring/comment at the top of this file for why the SDK itself can't do
        # this. Claude always has this fallback, so it never reports "none".
        return "api_key" if (self._ctx.anthropic_api_key or "").strip() else "cli"

    @property
    def is_available(self) -> bool:
        if self.auth_mode == "api_key":
            return True
        return shutil.which("claude") is not None

    async def chat_json(
        self,
        system: str,
        user: str,
        model_override: str | None = None,
    ) -> str:
        model_name = (model_override or self._ctx.default_claude_model or "claude-sonnet-5").strip()

        if self.auth_mode == "cli":
            return await _chat_json_claude_cli(
                system, user, model_name, self._ctx.llm_timeout_seconds
            )

        try:
            from anthropic import AsyncAnthropic
        except ModuleNotFoundError as e:
            raise RuntimeError(
                "The 'anthropic' package is not installed. Run "
                "`pip install -r apps/api/requirements.txt` inside your virtualenv."
            ) from e

        # ANTHROPIC_API_KEY is set (from env or the OS keychain, via config) -- pass it
        # explicitly so a keychain-stored key works.
        client = AsyncAnthropic(
            api_key=self._ctx.anthropic_api_key, timeout=float(self._ctx.llm_timeout_seconds)
        )
        try:
            message = await client.messages.create(
                model=model_name,
                max_tokens=self._ctx.claude_max_output_tokens,
                system=system,
                thinking=_thinking_config(self._ctx.claude_thinking),
                messages=[{"role": "user", "content": user}],
            )
        except Exception as e:  # anthropic.APIError subclasses + connection/auth errors
            raise RuntimeError(_error_message(e, model_name)) from e
        finally:
            await client.close()

        if getattr(message, "stop_reason", None) == "refusal":
            raise RuntimeError(
                "Claude declined to answer this request (stop_reason=refusal). "
                "Adjust the profile or job description text and try again."
            )

        text = _extract_text(message)
        if not text:
            raise RuntimeError(
                f"Claude ('{model_name}') returned an empty response. If the output was cut "
                "off, raise CLAUDE_MAX_OUTPUT_TOKENS in .env; otherwise verify authentication "
                "(ANTHROPIC_API_KEY) and that your account can use this model."
            )
        return text
