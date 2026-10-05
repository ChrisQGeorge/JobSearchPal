"""Editable, A/B-testable prompts for every agent action.

Each registered prompt keeps its built-in template in code (the
"default" variant). Users can add custom variants on Settings → Prompts,
enable/disable them, and give each a weight. At run time
`render_prompt` picks one enabled variant at random, weighted — so:

  * tweak a prompt: add a variant, disable "default"
  * A/B test: leave two or more variants enabled (e.g. 50/50)
  * roll back: re-enable "default", disable the rest

Generated documents record which variant wrote them
(GeneratedDocument.prompt_variant = "<key>:<variant_id>"), and
/api/v1/prompts/{key}/stats joins that to job outcomes so experiments
on resume / cover-letter prompts have a scoreboard.

Variants persist in /root/.claude/jsp-prompts.json on the claude_config
volume (git-proof, survives rebuilds; same home as the other runtime
settings). Templates use `{placeholder}` names (listed per prompt);
`{{` / `}}` are literal braces, so the built-in text can be copied into
a variant verbatim. Unknown `{names}` are left in the text untouched
rather than raising, so a typo in a variant can't crash a run.
"""
from __future__ import annotations

import importlib
import json
import logging
import random
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

log = logging.getLogger(__name__)

_PATH = Path("/root/.claude/jsp-prompts.json")
_LOCK = threading.Lock()
MAX_VARIANTS = 12
MAX_TEMPLATE_CHARS = 60_000
DEFAULT_ID = "default"


@dataclass(frozen=True)
class PromptDef:
    key: str
    label: str
    group: str
    module: str
    attr: str
    description: str = ""
    tracks_documents: bool = False  # outcome stats available


PROMPTS: list[PromptDef] = [
    PromptDef("tailor_resume", "Tailored resume", "Documents",
              "app.api.v1.documents", "_TAILOR_RESUME_PROMPT",
              "Writes a resume tailored to one job posting.", True),
    PromptDef("tailor_cover_letter", "Tailored cover letter", "Documents",
              "app.api.v1.documents", "_TAILOR_COVER_LETTER_PROMPT",
              "Writes a cover letter tailored to one job posting.", True),
    PromptDef("tailor_email", "Outreach / thank-you / follow-up email", "Documents",
              "app.api.v1.documents", "_TAILOR_EMAIL_PROMPT",
              "Short job-related emails; {purpose_label} says which kind.", True),
    PromptDef("tailor_generic", "Other tailored documents", "Documents",
              "app.api.v1.documents", "_TAILOR_GENERIC_PROMPT",
              "Any other document type, driven by the extra notes.", True),
    PromptDef("humanize", "Humanize (rewrite in your voice)", "Documents",
              "app.api.v1.documents", "_HUMANIZE_PROMPT",
              "Rewrites a generated document in your own voice.", True),
    PromptDef("humanize_fix", "Humanize — banned-phrase fix pass", "Documents",
              "app.api.v1.documents", "_HUMANIZE_FIX_PROMPT",
              "Retry prompt when a humanized draft still contains banned phrases."),
    PromptDef("selection_rewrite", "Studio: rewrite selection", "Studio",
              "app.api.v1.documents", "_SELECTION_REWRITE_PROMPT"),
    PromptDef("selection_answer", "Studio: answer about selection", "Studio",
              "app.api.v1.documents", "_SELECTION_ANSWER_PROMPT"),
    PromptDef("selection_new_doc", "Studio: new document from selection", "Studio",
              "app.api.v1.documents", "_SELECTION_NEW_DOC_PROMPT", "", True),
    PromptDef("jd_analyze", "Job analysis (LLM scoring fallback)", "Jobs",
              "app.api.v1.jobs", "_JD_ANALYZE_PROMPT",
              "Used when Jev isn't configured."),
    PromptDef("jd_prep", "Application prep (resume emphasis, hooks)", "Jobs",
              "app.api.v1.jobs", "_JD_PREP_PROMPT"),
    PromptDef("fetch_parse", "URL fetch: parse page", "Jobs",
              "app.api.v1.jobs", "_FETCH_PARSE_PROMPT",
              "LLM fallback parse when no deterministic extractor matches."),
    PromptDef("fetch_fallback", "URL fetch: WebFetch fallback", "Jobs",
              "app.api.v1.jobs", "_FETCH_FALLBACK_PROMPT"),
    PromptDef("interview_prep", "Interview round prep", "Interviews",
              "app.api.v1.jobs", "_INTERVIEW_PREP_PROMPT"),
    PromptDef("interview_retro", "Interview retrospective", "Interviews",
              "app.api.v1.jobs", "_INTERVIEW_RETRO_PROMPT"),
    PromptDef("org_research", "Company research", "Research",
              "app.api.v1.organizations", "_RESEARCH_PROMPT"),
    PromptDef("org_research_fallback", "Company research (fallback)", "Research",
              "app.api.v1.organizations", "_RESEARCH_FALLBACK_PROMPT"),
    PromptDef("strategy", "Strategy advisor", "Dashboard",
              "app.api.v1.metrics", "_STRATEGY_PROMPT"),
    PromptDef("email_classify", "Email classifier", "Inbox",
              "app.api.v1.email_ingest", "_CLASSIFY_PROMPT"),
    PromptDef("autofill", "Application form autofill", "Applying",
              "app.api.v1.autofill", "_AUTOFILL_PROMPT"),
    PromptDef("resume_ingest", "Resume import (history extraction)", "Profile",
              "app.api.v1.resume_ingest", "_INGEST_PROMPT"),
]
BY_KEY = {p.key: p for p in PROMPTS}

_PLACEHOLDER_RE = re.compile(r"\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}")


def default_template(key: str) -> str:
    p = BY_KEY[key]
    return getattr(importlib.import_module(p.module), p.attr)


def placeholders(template: str) -> list[str]:
    seen: list[str] = []
    for m in _PLACEHOLDER_RE.finditer(template):
        name = m.group(1)
        if name and name not in seen:
            seen.append(name)
    return seen


def render_template(
    template: str, values: Mapping[str, Any], missing: Optional[str] = None
) -> str:
    """Substitute `{name}` from `values` (raw, unescaped — values are
    inserted literally and never re-parsed), `{{`/`}}` → literal braces.
    Unknown names stay as written, or become `missing` when given.
    Equivalent to str.format for the built-in templates."""
    def sub(m: re.Match) -> str:
        tok = m.group(0)
        if tok == "{{":
            return "{"
        if tok == "}}":
            return "}"
        name = m.group(1)
        if name in values:
            return str(values[name])
        return missing if missing is not None else tok

    return _PLACEHOLDER_RE.sub(sub, template)


# ---- Store -----------------------------------------------------------------


def _load() -> dict:
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(_PATH)


def _entry(data: dict, key: str) -> dict:
    e = data.get(key) if isinstance(data.get(key), dict) else {}
    return {
        "default_enabled": bool(e.get("default_enabled", True)),
        "default_weight": float(e.get("default_weight", 1.0)),
        "variants": [v for v in (e.get("variants") or []) if isinstance(v, dict)],
    }


def get_prompt(key: str) -> dict:
    """Full editable view of one prompt: the built-in default plus custom
    variants, each with enabled/weight and its effective traffic share."""
    p = BY_KEY[key]
    e = _entry(_load(), key)
    default_text = default_template(key)
    variants = [{
        "id": DEFAULT_ID,
        "name": "Built-in default",
        "template": default_text,
        "enabled": e["default_enabled"],
        "weight": e["default_weight"],
        "builtin": True,
    }] + [{
        "id": v.get("id"),
        "name": v.get("name") or "variant",
        "template": v.get("template") or "",
        "enabled": bool(v.get("enabled", True)),
        "weight": float(v.get("weight", 1.0)),
        "builtin": False,
        "created_at": v.get("created_at"),
        "updated_at": v.get("updated_at"),
    } for v in e["variants"]]
    active = [v for v in variants if v["enabled"] and v["weight"] > 0]
    total = sum(v["weight"] for v in active)
    for v in variants:
        if not active:
            v["share"] = 1.0 if v["id"] == DEFAULT_ID else 0.0
        else:
            v["share"] = round(v["weight"] / total, 4) if v in active else 0.0
    return {
        "key": p.key,
        "label": p.label,
        "group": p.group,
        "description": p.description,
        "tracks_documents": p.tracks_documents,
        "placeholders": placeholders(default_text),
        "variants": variants,
    }


def list_prompts() -> list[dict]:
    data = _load()
    out = []
    for p in PROMPTS:
        e = _entry(data, p.key)
        customized = (
            not e["default_enabled"]
            or any(v.get("enabled", True) for v in e["variants"])
        )
        out.append({
            "key": p.key,
            "label": p.label,
            "group": p.group,
            "description": p.description,
            "tracks_documents": p.tracks_documents,
            "variant_count": 1 + len(e["variants"]),
            "customized": customized,
            "ab_testing": sum(
                1 for v in ([{"enabled": e["default_enabled"], "weight": e["default_weight"]}]
                            + e["variants"])
                if v.get("enabled", True) and float(v.get("weight", 1.0)) > 0
            ) > 1,
        })
    return out


def _clean_variant(v: Mapping[str, Any]) -> dict:
    name = str(v.get("name") or "").strip()[:80] or "variant"
    template = str(v.get("template") or "")
    if not template.strip():
        raise ValueError(f"Variant '{name}' has an empty template.")
    if len(template) > MAX_TEMPLATE_CHARS:
        raise ValueError(f"Variant '{name}' exceeds {MAX_TEMPLATE_CHARS} chars.")
    return {
        "name": name,
        "template": template,
        "enabled": bool(v.get("enabled", True)),
        "weight": max(0.0, min(100.0, float(v.get("weight", 1.0)))),
    }


def save_prompt(key: str, variants: list[Mapping[str, Any]]) -> dict:
    """Full replacement of a prompt's variant list. The built-in entry
    (id "default") only carries enabled/weight; its text is never
    stored. Custom variants without an id are created; ids not present
    are deleted (their documents keep the attribution string)."""
    if key not in BY_KEY:
        raise KeyError(key)
    now = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    with _LOCK:
        data = _load()
        old = {v.get("id"): v for v in _entry(data, key)["variants"]}
        default_enabled, default_weight = True, 1.0
        custom: list[dict] = []
        for v in variants:
            if v.get("id") == DEFAULT_ID:
                default_enabled = bool(v.get("enabled", True))
                default_weight = max(0.0, min(100.0, float(v.get("weight", 1.0))))
                continue
            clean = _clean_variant(v)
            vid = v.get("id") if v.get("id") in old else None
            if vid:
                prev = old[vid]
                clean["id"] = vid
                clean["created_at"] = prev.get("created_at") or now
                clean["updated_at"] = (
                    now if prev.get("template") != clean["template"] else prev.get("updated_at")
                )
            else:
                clean["id"] = secrets.token_hex(4)
                clean["created_at"] = now
                clean["updated_at"] = now
            custom.append(clean)
        if len(custom) + 1 > MAX_VARIANTS:
            raise ValueError(f"At most {MAX_VARIANTS} variants per prompt.")
        data[key] = {
            "default_enabled": default_enabled,
            "default_weight": default_weight,
            "variants": custom,
        }
        _save(data)
    return get_prompt(key)


# ---- Rendering -------------------------------------------------------------


@dataclass
class RenderedPrompt:
    text: str
    key: str
    variant_id: str
    variant_name: str

    @property
    def attribution(self) -> str:
        return f"{self.key}:{self.variant_id}"


def render_prompt(
    key: str,
    values: Mapping[str, Any],
    *,
    variant_id: Optional[str] = None,
    missing: Optional[str] = None,
) -> RenderedPrompt:
    """Pick a variant (weighted random among enabled ones, or the
    requested `variant_id`) and render it. Never raises on store
    problems — any failure falls back to the built-in default."""
    default_text = default_template(key)
    chosen_id, chosen_name, template = DEFAULT_ID, "Built-in default", default_text
    try:
        e = _entry(_load(), key)
        pool: list[tuple[str, str, str, float]] = []
        if e["default_enabled"] and e["default_weight"] > 0:
            pool.append((DEFAULT_ID, "Built-in default", default_text, e["default_weight"]))
        by_id = {}
        for v in e["variants"]:
            entry = (v.get("id"), v.get("name") or "variant",
                     v.get("template") or "", float(v.get("weight", 1.0)))
            by_id[entry[0]] = entry
            if v.get("enabled", True) and entry[3] > 0 and entry[2].strip():
                pool.append(entry)
        if variant_id and variant_id != DEFAULT_ID and variant_id in by_id:
            chosen_id, chosen_name, template, _ = by_id[variant_id]
        elif variant_id == DEFAULT_ID:
            pass
        elif pool:
            chosen_id, chosen_name, template, _ = random.choices(
                pool, weights=[w for *_, w in pool], k=1
            )[0]
    except Exception as exc:  # pragma: no cover — never block an agent run
        log.warning("Prompt variant selection failed for %s: %s", key, exc)
    return RenderedPrompt(
        text=render_template(template, values, missing=missing),
        key=key,
        variant_id=chosen_id,
        variant_name=chosen_name,
    )
