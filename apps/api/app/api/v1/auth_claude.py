"""In-browser Claude Code OAuth login flow.

`claude setup-token` uses Ink (React-in-terminal) and requires a raw-mode TTY,
so we wrap it with util-linux `script` which allocates a PTY. We then:

  1. Strip ANSI escape sequences from output.
  2. Extract the OAuth URL the CLI prints and surface it to the browser.
  3. Forward the browser-supplied code back to the subprocess stdin.
  4. Report exit status so the UI can refresh /health/claude.

The subprocess's config lands in /root/.claude inside the container (isolated
named volume). Nothing touches the host.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import time
from pathlib import Path
from typing import Optional

_DEBUG_DIR = Path("/root/.claude/.jsp-login-debug")

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import settings
from app.core.deps import get_current_user
from app.models.user import User
from app.skills.token_store import clear_token, save_token

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/claude-login", tags=["auth-claude"])

# Battle-tested ECMA-48 escape stripper: covers CSI (ESC [ ... final), OSC
# (ESC ] ... BEL|ST), and the common two-byte escapes (ESC 7, ESC 8, ESC D,
# etc.) that Ink uses for cursor positioning and color. Previously we had a
# narrower regex and any unmatched sequences ended up embedded between token
# characters, so auto-extracted tokens authenticated as 401.
_ANSI_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"       # CSI — any params, intermediates, final
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC terminated by BEL or ST
    r"|\x1b[@-Z\\-_]"                # single-byte ESC-X sequences (ESC 7, ESC D, etc.)
)

_OAUTH_URL_START_RE = re.compile(r"https://[^\s]*?/oauth/authorize\?")
_PROMPT_RE = re.compile(r"paste\s*code\s*here", re.IGNORECASE)
_TOKEN_START_RE = re.compile(r"sk-ant-oat01-[A-Za-z0-9_=-]+")


def _extract_token(buf: str) -> Optional[str]:
    """Pull the long-lived OAuth token out of a successful setup-token run.

    The CLI prints `sk-ant-oat01-<chars>` and then immediately runs into
    "Storethistokensecurely" text (no whitespace — Ink renders with cursor
    positioning). Grab the greedy match, then truncate at the sentinel.
    """
    m = _TOKEN_START_RE.search(buf)
    if not m:
        return None
    token = m.group(0)
    for sentinel in ("Store", "Use", "Copy", " "):
        i = token.find(sentinel)
        if i > len("sk-ant-oat01-"):
            token = token[:i]
            break
    return token


def _extract_oauth_url(buf: str) -> Optional[str]:
    """Pull the full OAuth authorize URL out of the CLI buffer.

    The CLI wraps the URL across 80-column lines, and after stripping ANSI
    cursor-move sequences the "Paste code here if prompted" text collapses
    directly onto the URL's tail (no whitespace separator). We find the URL
    start, then walk forward: collapsing newlines (terminal wraps), stopping
    at whitespace / escape / the "paste" sentinel that always follows the URL.
    """
    m = _OAUTH_URL_START_RE.search(buf)
    if not m:
        return None
    chars: list[str] = []
    i = m.start()
    while i < len(buf):
        c = buf[i]
        if c in " \t\x1b\x00":
            break
        if c in "\n\r":
            i += 1
            continue
        if buf[i : i + 5].lower() == "paste":
            break
        chars.append(c)
        i += 1
    if len(chars) < m.end() - m.start():
        return None
    return "".join(chars)


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s).replace("\r", "")


class LoginSession:
    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self.proc = proc
        self.queue: asyncio.Queue[dict] = asyncio.Queue()
        self.finished = False
        self.exit_code: Optional[int] = None
        self.url: Optional[str] = None
        self.prompt_seen = False
        # Raw accumulated bytes (with ANSI still in them). We never strip per
        # chunk — a split ANSI sequence across chunk boundaries would otherwise
        # drop real content on the floor. Strip at scan time from the whole.
        self._raw = ""
        # Append-only binary log of the PTY stdout bytes, used to diagnose
        # token-extraction bugs. Rotated per-session.
        try:
            _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            self._debug_path: Optional[Path] = _DEBUG_DIR / f"{int(time.time())}.bin"
            self._debug_fh = self._debug_path.open("wb")
        except OSError as exc:
            log.warning("auth-claude debug log disabled: %s", exc)
            self._debug_path = None
            self._debug_fh = None

    @property
    def _buf(self) -> str:
        return _strip_ansi(self._raw).replace("\r", "")

    async def pump(self) -> None:
        """Read subprocess output in chunks, strip ANSI lazily, and emit events."""
        try:
            assert self.proc.stdout is not None
            while True:
                chunk = await self.proc.stdout.read(4096)
                if not chunk:
                    break
                if self._debug_fh is not None:
                    try:
                        self._debug_fh.write(chunk)
                        self._debug_fh.flush()
                    except OSError:
                        pass
                text = chunk.decode("utf-8", errors="replace")
                self._raw += text
                # For the UI, emit a stripped-view of just this chunk. OK that
                # some escapes slip through here — it's only for display.
                stripped = _strip_ansi(text)
                if stripped.strip():
                    await self.queue.put({"event": "chunk", "text": stripped})
                await self._scan_buffer()
        except Exception as exc:  # pragma: no cover  (best-effort streaming)
            log.exception("auth-claude pump error: %s", exc)
            await self.queue.put({"event": "error", "message": str(exc)})
        finally:
            self.exit_code = await self.proc.wait()
            # On a clean exit, extract and persist the token the CLI printed.
            # Everything downstream (/health/claude, runner.py) reads from the
            # token store, so this is what actually marks the container as
            # authenticated.
            if self.exit_code == 0:
                token = _extract_token(self._buf)
                if token:
                    try:
                        save_token(token)
                        await self.queue.put({"event": "token_saved"})
                    except Exception as exc:
                        log.exception("failed to save token: %s", exc)
                        await self.queue.put(
                            {"event": "error", "message": f"token save failed: {exc}"}
                        )
                else:
                    await self.queue.put(
                        {"event": "error", "message": "CLI exited 0 but no token found in output"}
                    )
            await self.queue.put({"event": "exit", "code": self.exit_code})
            self.finished = True
            if self._debug_fh is not None:
                try:
                    self._debug_fh.close()
                except OSError:
                    pass

    async def _scan_buffer(self) -> None:
        # Only emit the URL once we've seen the "Paste code" prompt — by then
        # the whole URL has been printed and we can reliably un-wrap it.
        if not self.prompt_seen and _PROMPT_RE.search(self._buf):
            self.prompt_seen = True
            if self.url is None:
                self.url = _extract_oauth_url(self._buf)
                if self.url:
                    await self.queue.put({"event": "url", "url": self.url})
            await self.queue.put({"event": "prompt"})


# In-memory session registry. Single-user app; one login at a time is plenty.
_SESSIONS: dict[str, LoginSession] = {}


@router.post("/start")
async def start_login(_: User = Depends(get_current_user)) -> dict[str, str]:
    """Spawn `claude setup-token` under a PTY and return a session id."""
    # Kill any prior unfinished session so we don't leak processes.
    for sid, s in list(_SESSIONS.items()):
        if not s.finished:
            try:
                s.proc.kill()
                await s.proc.wait()
            except Exception:
                pass
            _SESSIONS.pop(sid, None)

    env = os.environ.copy()
    env.setdefault("CLAUDE_CONFIG_DIR", "/root/.claude")
    # Ink (the CLI's terminal UI) needs a reasonable terminal size and TERM,
    # otherwise it degrades rendering and corrupts the token display — e.g.
    # with TERM=dumb and 0x0 size, the token gets broken into visual chunks
    # and two characters are replaced by cursor-right moves, making
    # auto-extraction impossible.
    env["TERM"] = "xterm-256color"
    env["COLUMNS"] = "200"
    env["LINES"] = "50"
    # `script` wraps the command in a PTY. We also set stty inside so the
    # kernel knows the PTY's window size (TIOCSWINSZ), not just env vars.
    inner_cmd = (
        "stty rows 50 cols 200 2>/dev/null; "
        f"{settings.CLAUDE_CODE_BIN} setup-token"
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            "script",
            "-q",
            "-c",
            inner_cmd,
            "/dev/null",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to start login: `script` or the Claude Code CLI is missing "
                "inside the container. Try rebuilding the api image."
            ),
        ) from exc

    session_id = secrets.token_urlsafe(16)
    sess = LoginSession(proc)
    _SESSIONS[session_id] = sess
    asyncio.create_task(sess.pump())
    return {"session_id": session_id}


@router.get("/{session_id}/stream")
async def stream_login(
    session_id: str,
    request: Request,
    _: User = Depends(get_current_user),
) -> StreamingResponse:
    sess = _SESSIONS.get(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="Unknown login session")

    async def generator():
        # Re-emit already-known state so a reconnecting client doesn't miss it.
        yield f'data: {json.dumps({"event": "opened"})}\n\n'
        if sess.url:
            yield f'data: {json.dumps({"event": "url", "url": sess.url})}\n\n'
        if sess.prompt_seen:
            yield f'data: {json.dumps({"event": "prompt"})}\n\n'

        while not sess.finished or not sess.queue.empty():
            if await request.is_disconnected():
                break
            try:
                item = await asyncio.wait_for(sess.queue.get(), timeout=15.0)
                yield f"data: {json.dumps(item)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


class InputLine(BaseModel):
    line: str


class TokenPayload(BaseModel):
    token: str


@router.post("/token")
async def save_token_manually(
    body: TokenPayload, _: User = Depends(get_current_user)
) -> dict[str, bool]:
    """Direct token save — bypasses the subprocess flow.

    Useful when the interactive flow misbehaves: run
    `docker compose exec -it api claude setup-token` on your own, copy the
    token, and paste it into the UI.
    """
    token = body.token.strip()
    if not token.startswith("sk-ant-oat01-") or len(token) < 40:
        raise HTTPException(
            status_code=422, detail="Token must start with sk-ant-oat01- and look like an OAuth token."
        )
    save_token(token)
    return {"ok": True}


@router.delete("/token", status_code=status.HTTP_204_NO_CONTENT)
async def reset_token(_: User = Depends(get_current_user)) -> None:
    """Forget the stored OAuth token. Companion will show the login flow again."""
    clear_token()


@router.post("/{session_id}/input")
async def send_input(
    session_id: str,
    body: InputLine,
    _: User = Depends(get_current_user),
) -> dict[str, bool]:
    sess = _SESSIONS.get(session_id)
    if sess is None or sess.proc.stdin is None:
        raise HTTPException(status_code=404, detail="Unknown login session")
    if sess.finished:
        raise HTTPException(status_code=409, detail="Login session already finished")
    try:
        # Ink (the React-for-terminal library that `claude setup-token` uses)
        # puts the PTY in raw mode. A bulk paste of "code\r" seems to get the
        # text typed but the Enter is sometimes swallowed. Writing the body
        # first, draining, then a separate CR write after a tiny delay so
        # Ink's input widget sees them as distinct events reliably.
        sess.proc.stdin.write(body.line.encode("utf-8"))
        await sess.proc.stdin.drain()
        await asyncio.sleep(0.15)
        sess.proc.stdin.write(b"\r")
        await sess.proc.stdin.drain()
    except (BrokenPipeError, ConnectionResetError) as exc:
        raise HTTPException(status_code=502, detail=f"stdin closed: {exc}") from exc
    return {"ok": True}


@router.post("/{session_id}/cancel")
async def cancel_login(
    session_id: str, _: User = Depends(get_current_user)
) -> dict[str, bool]:
    sess = _SESSIONS.pop(session_id, None)
    if sess and not sess.finished:
        try:
            sess.proc.kill()
            await sess.proc.wait()
        except Exception:
            pass
    return {"ok": True}
