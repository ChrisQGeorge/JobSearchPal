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

# Models we surface in the Settings dropdown.
#
# Why aliases, not pinned version IDs: the Claude Code CLI has no way to
# *enumerate* available models (no `claude models`, no JSON catalogue, no
# on-disk list — that only exists on the Anthropic API, which this app
# deliberately never calls). But the CLI's `--model` flag accepts tier
# aliases that auto-resolve to the newest release of each tier. So
# `--model opus` is Opus 4.8 today and whatever ships next with zero code
# changes — which is exactly the "new models show up automatically" goal,
# achieved purely through the CLI. Labels avoid version numbers for the
# same reason (they'd go stale). Power users can still pin an exact version
# ID via the API/settings file; see the relaxed validation below.
#
# Exception: Sonnet is deliberately PINNED to 4.6 (not the latest-tracking
# `sonnet` alias) — a product choice to hold the Sonnet tier at the 4.x
# generation rather than auto-upgrading to Sonnet 5.
#
# Order = most → least capable. "" means "use the global default".
MODEL_CHOICES: tuple[tuple[str, str], ...] = (
    ("", "Default (ANTHROPIC_DEFAULT_MODEL, else the CLI's own default)"),
    ("best", "Best available — most capable model (tracks the newest release)"),
    ("fable", "Fable — deepest reasoning (long-horizon work, priciest)"),
    ("opus", "Opus — latest (most capable, slower)"),
    ("claude-sonnet-4-6", "Sonnet 4.6 (balanced; pinned)"),
    ("haiku", "Haiku — latest (fastest, cheapest)"),
    ("fable[1m]", "Fable — 1M-token context"),
    ("opus[1m]", "Opus — latest, 1M-token context (long JDs / resumes)"),
    ("claude-sonnet-4-6[1m]", "Sonnet 4.6 — 1M-token context"),
)


def _load_raw() -> dict[str, str]:
    """Read the per-action map from disk. Returns {} on any error.

    Values are NOT checked against a fixed allow-list: the model space is
    open-ended (new aliases/versions appear over time) and the CLI is the
    real validator at run time. We only sanity-check the action key and
    that the value is a non-empty string, so a legacy pinned ID (e.g.
    "claude-opus-4-7") set before we moved to aliases is preserved rather
    than silently dropped.
    """
    try:
        data = json.loads(_PATH.read_text())
        models = data.get("models") or {}
        if isinstance(models, dict):
            return {
                k: v.strip()
                for k, v in models.items()
                if k in _VALID_KEYS and isinstance(v, str) and v.strip()
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
    """Replace the per-action map. Drops unknown action keys and empty
    values (empty = "fall back to the global default", so storing it would
    just waste space). Model values are accepted as-is (any non-empty
    string) — the CLI validates them at run time and the model space is
    open-ended. Returns the sanitized map that was actually persisted."""
    sanitized: dict[str, str] = {}
    for k, v in (mapping or {}).items():
        if k not in _VALID_KEYS:
            continue
        if isinstance(v, str) and v.strip():
            sanitized[k] = v.strip()
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps({"models": sanitized}, indent=2))
    except OSError as exc:
        log.warning("Failed to persist model settings: %s", exc)
    return sanitized
