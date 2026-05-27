"""Per-action Claude model overrides.

Lets the user route different kinds of work to different models — e.g.
haiku-4.5 for cheap URL fetches, opus-4.7 for resume writing,
sonnet-4.6 for JD analysis. All requests still go through the Claude
Code CLI (`claude -p --model <id>`); we don't talk to the Anthropic
API SDK from this app.

Persistence: a JSON file in /root/.claude (same volume as the OAuth
token + worker settings) so the choices survive container restarts.

Resolution order for a given action:
  1. The per-action mapping in the file (if set + non-empty)
  2. The global ANTHROPIC_DEFAULT_MODEL env var
  3. None — the CLI uses its own default
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.core.config import settings

log = logging.getLogger(__name__)

_PATH = Path("/root/.claude/jsp-model-settings.json")

# Action keys for every LLM-using context in the app. Order matters — the
# Settings UI renders dropdowns in this order.
ACTIONS: tuple[tuple[str, str], ...] = (
    ("fetch", "URL fetch (parse a job posting page)"),
    ("jd_analyze", "JD analysis (fit score, red flags)"),
    ("tailor_resume", "Tailor resume"),
    ("tailor_cover_letter", "Tailor cover letter"),
    ("tailor_other", "Tailor other documents (outreach, follow-up, etc.)"),
    ("humanize", "Humanize a draft"),
    ("selection_edit", "Selection edit in the doc editor"),
    ("org_research", "Company research"),
    ("companion_chat", "Companion chat"),
    ("analyze_entity", "Analyze a history entry"),
    ("resume_ingest", "Resume ingest"),
    ("email_ingest", "Email ingest"),
    ("interview_prep", "Interview prep doc"),
    ("interview_retro", "Interview retro"),
    ("autofill", "Application autofill"),
    ("strategy", "Strategy briefing"),
)
_VALID_KEYS = frozenset(k for k, _ in ACTIONS)

# Models we surface in the Settings dropdown. Order = most → least capable.
# An empty string means "use the global default" (env or CLI default).
SUPPORTED_MODELS: tuple[tuple[str, str], ...] = (
    ("", "Default (ANTHROPIC_DEFAULT_MODEL env var)"),
    ("claude-opus-4-7", "Claude Opus 4.7 (most capable, slowest, priciest)"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6 (balanced)"),
    ("claude-haiku-4-5-20251001", "Claude Haiku 4.5 (fastest, cheapest)"),
)
_VALID_MODELS = frozenset(m for m, _ in SUPPORTED_MODELS)


def _load_raw() -> dict[str, str]:
    """Read the per-action map from disk. Returns {} on any error."""
    try:
        data = json.loads(_PATH.read_text())
        models = data.get("models") or {}
        if isinstance(models, dict):
            # Drop unknown keys / unknown values defensively so a stale
            # settings file from a previous schema can't poison resolution.
            return {
                k: v
                for k, v in models.items()
                if k in _VALID_KEYS and isinstance(v, str) and v in _VALID_MODELS
            }
        return {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def get_model_for(action: str) -> str | None:
    """Resolve which model to use for `action`. Returns:
      - the user's per-action choice (string) if set and non-empty;
      - the global default (settings.ANTHROPIC_DEFAULT_MODEL) otherwise;
      - None if neither is set — caller passes nothing and the CLI picks.
    """
    chosen = _load_raw().get(action, "")
    if chosen:
        return chosen
    return settings.ANTHROPIC_DEFAULT_MODEL or None


def get_all() -> dict[str, str]:
    """Snapshot of the user-saved choices. Keys are action ids; values are
    model ids or empty string (= use default). Unset actions are omitted —
    the Settings UI fills them in client-side as empty strings."""
    return _load_raw()


def set_all(mapping: dict[str, str]) -> dict[str, str]:
    """Replace the per-action map. Silently drops unknown keys / unknown
    model ids so a malformed PUT can't break resolution. Returns the
    sanitized map that was actually persisted."""
    sanitized: dict[str, str] = {}
    for k, v in (mapping or {}).items():
        if k not in _VALID_KEYS:
            continue
        if not isinstance(v, str):
            continue
        if v == "" or v in _VALID_MODELS:
            # Only keep non-empty overrides — empty means "fall back to
            # global default" so writing it would just waste space.
            if v:
                sanitized[k] = v
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps({"models": sanitized}, indent=2))
    except OSError as exc:
        log.warning("Failed to persist model settings: %s", exc)
    return sanitized
