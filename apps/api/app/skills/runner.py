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
) -> ClaudeResult:
    """Run the Claude Code CLI non-interactively and return parsed output.

    If `session_id` is provided, passes `--resume <id>` so the CLI continues an
    existing multi-turn conversation instead of starting a fresh one.

    Raises ClaudeCodeError on non-zero exit, timeout, or JSON parse failure.
    """

    cmd: list[str] = [settings.CLAUDE_CODE_BIN, "-p", prompt, "--output-format", output_format]

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
