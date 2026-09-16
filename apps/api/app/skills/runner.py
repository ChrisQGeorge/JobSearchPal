"""Thin wrapper around the Claude Code CLI, invoked as a subprocess.

The backend does not talk to the Anthropic HTTP API directly. Instead it shells
out to `claude -p` (non-interactive mode) so that the user's existing Claude
Code login — including Pro/Max subscription OAuth — is reused. See the project
README for the auth setup.

Typical flow:

    result = await run_claude_prompt(
        prompt="Summarize this job description: ...",
        output_format="json",
        timeout_seconds=60,
    )
    text = result["result"]   # the final assistant text
    meta = result             # session_id, cost_usd, duration_ms, num_turns, ...
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.skills.token_store import load_token

log = logging.getLogger(__name__)


class ClaudeCodeError(RuntimeError):
    """Raised when the Claude Code CLI fails or its output cannot be parsed."""


def _resolve_external(
    chosen_model: str | None, action: str | None
) -> tuple[dict | None, str | None, str | None]:
    """Decide whether this run goes to an external OpenAI-compatible
    provider instead of the Claude CLI.

    Returns (provider, ext_model, effective_claude_model):
      * provider set → run externally with ext_model.
      * provider None → run the CLI with effective_claude_model (which is
        the incoming model, or the env default when an ext model was
        configured for an action that needs Claude's tools).
    """
    from app.skills.llm_providers import resolve_ext_model
    from app.skills.model_settings import EXT_COMPATIBLE_ACTIONS

    ext = resolve_ext_model(chosen_model)
    if ext is None:
        return None, None, chosen_model
    if action is not None and action not in EXT_COMPATIBLE_ACTIONS:
        log.warning(
            "Action %r requires Claude Code tools; configured external model %r "
            "ignored — using ANTHROPIC_DEFAULT_MODEL.",
            action, chosen_model,
        )
        return None, None, settings.ANTHROPIC_DEFAULT_MODEL or None
    provider, ext_model = ext
    return provider, ext_model, None


@dataclass(frozen=True)
class ClaudeResult:
    """Parsed result of a `claude -p --output-format json` invocation."""

    result: str
    session_id: str | None
    cost_usd: float | None
    duration_ms: int | None
    num_turns: int | None
    raw: dict[str, Any]


async def run_claude_prompt(
    prompt: str,
    *,
    output_format: str = "json",
    skills_dir: str | None = None,
    system_prompt_append: str | None = None,
    allowed_tools: list[str] | None = None,
    timeout_seconds: int = 120,
    cwd: str | None = None,
    session_id: str | None = None,
    extra_env: dict[str, str] | None = None,
    action: str | None = None,
) -> ClaudeResult:
    """Run the Claude Code CLI non-interactively and return parsed output.

    If `session_id` is provided, passes `--resume <id>` so the CLI continues an
    existing multi-turn conversation instead of starting a fresh one.

    `action` is an optional key from `model_settings.ACTIONS` that lets the
    user route different kinds of work (fetch, jd_analyze, tailor_resume,
    …) to different Claude models from the Settings page. Falls back to
    ANTHROPIC_DEFAULT_MODEL when the user hasn't picked an override.

    Raises ClaudeCodeError on non-zero exit, timeout, or JSON parse failure.
    """

    # Pin the model. The runner consults the user's per-action override
    # (from /api/v1/jobs/model-settings, persisted in /root/.claude) and
    # falls back to ANTHROPIC_DEFAULT_MODEL. Claude models go through the
    # CLI `--model` flag — never the Anthropic API SDK. `ext:` models
    # (user-configured OpenAI-compatible providers — DeepSeek, OpenAI,
    # local Ollama, …) skip the CLI entirely and hit the provider's HTTP
    # API. External models are text-only: allowed_tools / session_id are
    # ignored (tool-dependent actions are gated in _resolve_external).
    from app.skills.model_settings import get_model_for as _get_model

    chosen_model = _get_model(action) if action else settings.ANTHROPIC_DEFAULT_MODEL
    provider, ext_model, chosen_model = _resolve_external(chosen_model, action)
    if provider is not None:
        from app.skills.llm_providers import ExternalProviderError, chat_text

        log.info(
            "Invoking external provider %s model %s (action=%s)",
            provider["id"], ext_model, action,
        )
        try:
            text = await chat_text(
                provider, ext_model, prompt, timeout_seconds=timeout_seconds
            )
        except ExternalProviderError as exc:
            raise ClaudeCodeError(str(exc)) from exc
        except Exception as exc:
            raise ClaudeCodeError(
                f"External provider {provider['label']} failed: {exc}"
            ) from exc
        return ClaudeResult(
            result=text,
            session_id=None,
            cost_usd=None,
            duration_ms=None,
            num_turns=None,
            raw={"result": text, "provider": provider["id"], "model": ext_model},
        )

    cmd: list[str] = [settings.CLAUDE_CODE_BIN, "-p", prompt, "--output-format", output_format]
    if chosen_model:
        cmd += ["--model", chosen_model]

    if session_id:
        cmd += ["--resume", session_id]

    # When running inside the container, skills are bind-mounted to SKILLS_DIR.
    # Set the CWD to that dir (or a caller override) so auto-discovery finds them.
    effective_cwd = cwd or skills_dir or settings.SKILLS_DIR
    if not Path(effective_cwd).is_dir():
        log.warning("Skills/work dir %s does not exist; falling back to /tmp", effective_cwd)
        effective_cwd = "/tmp"

    if system_prompt_append:
        cmd += ["--append-system-prompt", system_prompt_append]

    if allowed_tools:
        cmd += ["--allowedTools", ",".join(allowed_tools)]

    env = os.environ.copy()
    # Force a UTF-8 locale in the subprocess. Without this the Node.js CLI
    # (and any curl calls it makes inside Bash) default to whatever the
    # inherited POSIX locale is, which on the slim Python base image is
    # "C" — producing mojibake on non-ASCII characters ("résumé" → "rÃ©sumÃ©")
    # by the time it round-trips through subprocess.PIPE as bytes.
    env["LANG"] = "C.UTF-8"
    env["LC_ALL"] = "C.UTF-8"
    env["PYTHONIOENCODING"] = "utf-8"
    # Auth precedence: a stored long-lived OAuth token (from the in-UI login
    # flow) wins, otherwise fall back to an ANTHROPIC_API_KEY if configured.
    oauth_token = load_token()
    if oauth_token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
    elif settings.ANTHROPIC_API_KEY:
        env["ANTHROPIC_API_KEY"] = settings.ANTHROPIC_API_KEY
    env.setdefault("CLAUDE_CONFIG_DIR", "/root/.claude")
    if extra_env:
        env.update(extra_env)

    log.info("Invoking Claude Code: %s (cwd=%s)", " ".join(cmd[:3] + ["…"]), effective_cwd)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=effective_cwd,
            env=env,
        )
    except FileNotFoundError as exc:
        raise ClaudeCodeError(
            f"Claude Code CLI not found at '{settings.CLAUDE_CODE_BIN}'. "
            "Is the CLI installed in this container?"
        ) from exc

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_seconds
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        raise ClaudeCodeError(f"Claude Code timed out after {timeout_seconds}s") from exc

    if proc.returncode != 0:
        stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
        raise ClaudeCodeError(
            f"Claude Code exited {proc.returncode}: {stderr_text or '(no stderr)'}"
        )

    stdout_text = stdout_bytes.decode("utf-8", errors="replace")

    if output_format == "text":
        return ClaudeResult(
            result=stdout_text,
            session_id=None,
            cost_usd=None,
            duration_ms=None,
            num_turns=None,
            raw={"result": stdout_text},
        )

    try:
        data = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        raise ClaudeCodeError(
            f"Could not parse Claude Code JSON output: {exc}. Raw: {stdout_text[:500]!r}"
        ) from exc

    return ClaudeResult(
        result=str(data.get("result", "")),
        session_id=data.get("session_id"),
        cost_usd=data.get("cost_usd"),
        duration_ms=data.get("duration_ms"),
        num_turns=data.get("num_turns"),
        raw=data,
    )


async def stream_claude_prompt(
    prompt: str,
    *,
    system_prompt_append: str | None = None,
    allowed_tools: list[str] | None = None,
    session_id: str | None = None,
    extra_env: dict[str, str] | None = None,
    skills_dir: str | None = None,
    cwd: str | None = None,
    timeout_seconds: int = 300,
    action: str | None = None,
):
    """Run Claude Code with `--output-format stream-json` and yield each
    event (parsed dict) as it arrives.

    The CLI emits newline-delimited JSON on stdout; we yield one dict per
    line. The caller is responsible for mapping those events onto whatever
    transport it needs (SSE, WebSocket, whatever).

    Raises ClaudeCodeError on startup errors. Stream errors (malformed
    lines, timeouts, non-zero exit) are surfaced as a final yielded dict
    with type="error" so the caller can pass them through to the user.
    """
    import asyncio as _a

    from app.skills.model_settings import get_model_for as _get_model

    chosen_model = _get_model(action) if action else settings.ANTHROPIC_DEFAULT_MODEL
    provider, ext_model, chosen_model = _resolve_external(chosen_model, action)
    if provider is not None:
        # External OpenAI-compatible provider — no CLI subprocess. Emit
        # events in the same stream-json shape the consumers expect:
        # assistant text blocks (flushed in chunks for liveness on the
        # activity feed) followed by a terminal `result`. Tools and
        # `--resume` sessions don't exist here; `_resolve_external`
        # already gated tool-dependent actions back to Claude.
        from app.skills.llm_providers import stream_chat

        log.info(
            "Streaming external provider %s model %s (action=%s)",
            provider["id"], ext_model, action,
        )
        yield {"type": "system", "subtype": "init", "provider": provider["id"]}
        collected: list[str] = []
        buf: list[str] = []
        buf_len = 0
        try:
            async for delta in stream_chat(
                provider, ext_model, prompt, timeout_seconds=timeout_seconds
            ):
                collected.append(delta)
                buf.append(delta)
                buf_len += len(delta)
                if buf_len >= 600:
                    yield {
                        "type": "assistant",
                        "message": {"content": [{"type": "text", "text": "".join(buf)}]},
                    }
                    buf, buf_len = [], 0
        except Exception as exc:
            yield {"type": "error", "message": f"{provider['label']}: {exc}"[:2000]}
            return
        if buf:
            yield {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "".join(buf)}]},
            }
        yield {
            "type": "result",
            "result": "".join(collected),
            "provider": provider["id"],
            "model": ext_model,
        }
        return

    cmd: list[str] = [
        settings.CLAUDE_CODE_BIN,
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",  # stream-json requires --verbose
        "--include-partial-messages",
    ]
    if chosen_model:
        cmd += ["--model", chosen_model]
    if session_id:
        cmd += ["--resume", session_id]

    effective_cwd = cwd or skills_dir or settings.SKILLS_DIR
    if not Path(effective_cwd).is_dir():
        log.warning("Skills/work dir %s does not exist; falling back to /tmp", effective_cwd)
        effective_cwd = "/tmp"

    if system_prompt_append:
        cmd += ["--append-system-prompt", system_prompt_append]
    if allowed_tools:
        cmd += ["--allowedTools", ",".join(allowed_tools)]

    env = os.environ.copy()
    env["LANG"] = "C.UTF-8"
    env["LC_ALL"] = "C.UTF-8"
    env["PYTHONIOENCODING"] = "utf-8"
    oauth_token = load_token()
    if oauth_token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
    elif settings.ANTHROPIC_API_KEY:
        env["ANTHROPIC_API_KEY"] = settings.ANTHROPIC_API_KEY
    env.setdefault("CLAUDE_CONFIG_DIR", "/root/.claude")
    if extra_env:
        env.update(extra_env)

    log.info(
        "Streaming Claude Code: %s (cwd=%s)", " ".join(cmd[:3] + ["…"]), effective_cwd
    )

    try:
        # asyncio.StreamReader's default per-line buffer is 64 KB. Claude's
        # stream-json emits whole assistant blocks (or large tool_result
        # payloads from a long curl response) on a single line, and those
        # routinely blow past 64 KB — raising ValueError "Separator is
        # found, but chunk is longer than limit" and killing the stream.
        # 16 MB gives plenty of headroom; worst case it's a few MB of
        # serialized history JSON from a /history/work curl.
        proc = await _a.create_subprocess_exec(
            *cmd,
            stdout=_a.subprocess.PIPE,
            stderr=_a.subprocess.PIPE,
            cwd=effective_cwd,
            env=env,
            limit=16 * 1024 * 1024,
        )
    except FileNotFoundError as exc:
        raise ClaudeCodeError(
            f"Claude Code CLI not found at '{settings.CLAUDE_CODE_BIN}'."
        ) from exc

    assert proc.stdout is not None

    async def _drain_stderr() -> bytes:
        assert proc.stderr is not None
        return await proc.stderr.read()

    stderr_task = _a.create_task(_drain_stderr())

    try:
        async with _a.timeout(timeout_seconds):
            while True:
                try:
                    line = await proc.stdout.readline()
                except ValueError as exc:
                    # Shouldn't happen with the 16 MB `limit=` above, but
                    # fail soft instead of tearing down the whole tailor:
                    # log, skip to the next newline, and keep going.
                    log.warning(
                        "stream-json line exceeded readline buffer: %s. "
                        "Skipping to next newline.", exc,
                    )
                    try:
                        await proc.stdout.readuntil(b"\n")
                    except Exception:
                        break
                    continue
                if not line:
                    break
                try:
                    event = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    # Skip malformed lines rather than killing the stream.
                    continue
                yield event
    except TimeoutError:
        proc.kill()
        yield {"type": "error", "message": f"Timed out after {timeout_seconds}s"}
        return
    finally:
        # Let the process wind down; ignore exit code since we might have
        # killed it on timeout.
        try:
            await _a.wait_for(proc.wait(), timeout=5)
        except _a.TimeoutError:
            proc.kill()
        stderr_bytes = await stderr_task
        if proc.returncode not in (0, None) and stderr_bytes:
            err = stderr_bytes.decode("utf-8", errors="replace").strip()
            if err:
                yield {"type": "error", "message": err[:2000]}


async def claude_is_available() -> bool:
    """Lightweight health check — does the CLI exist and respond to --version?"""
    try:
        proc = await asyncio.create_subprocess_exec(
            settings.CLAUDE_CODE_BIN,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=5)
        return proc.returncode == 0
    except (FileNotFoundError, asyncio.TimeoutError):
        return False
