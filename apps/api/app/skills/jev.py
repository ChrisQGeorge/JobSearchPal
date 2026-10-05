"""TypeSafe Jev (System One) client for job-fit scoring.

Jev is an evaluation model: instead of generating text, it answers typed
questions about an input "state" with calibrated probabilities. That
maps cleanly onto initial job scoring — we hand it the posting plus the
candidate profile and ask for (a) a 5-level fit score and (b) a yes/no
"worth applying" judgment, and get back numbers with confidence instead
of prose. No reasons text is produced by design.

API (docs.typesafe.ai/api):
  POST https://api.typesafe.ai/v1/systemone
  Authorization: Bearer <key>
  body: {"state": ..., "model": "jev-latest", "questions": {...}}
  response: {"answers": {key: {type, score|noul, probabilities,
             confidence, legend}}, "usage": {...}}

The API key is a per-user ApiCredential row (provider "typesafe_jev"),
managed on Settings → API Keys — never hardcoded, never in env.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# ApiCredential provider key — keep in sync with KNOWN_PROVIDERS in
# web/src/app/(app)/settings/_panels/SettingsPanels.tsx.
JEV_PROVIDER = "typesafe_jev"

_API_URL = "https://api.typesafe.ai/v1/systemone"
_MODEL = "jev-latest"

# Five scored dimensions, asked in ONE call (Jev takes a map of typed
# questions). Each has 5 ordered levels, worst → best; the answer's
# probability-weighted position rescales to 0-100 and the overall
# fit_score is the plain average of the five. Keys land in
# jd_analysis["scores"] — keep in sync with the labels in
# web/src/app/(app)/jobs/[id]/page.tsx (JdAnalysisBody).
SCORE_DIMENSIONS: list[tuple[str, str]] = [
    ("skills_fit", "Skills & requirements"),
    ("job_quality", "Job quality"),
    ("location_fit", "Location"),
    ("career_fit", "Career trajectory"),
    ("posting_quality", "Posting credibility"),
]

_QUESTIONS: dict[str, Any] = {
    "skills_fit": {
        "type": "score",
        "instructions": (
            "Rate how well the candidate meets this posting's stated "
            "requirements: required and nice-to-have skills, education, "
            "certifications, domain experience, and years/level of "
            "experience."
        ),
        "criteria": [
            "Lacks most required skills and the education/experience bar; "
            "would be screened out immediately.",
            "A few transferable skills but major gaps in the required "
            "skills, education, or experience level.",
            "Meets roughly half the requirements; real ramp-up needed on "
            "the rest.",
            "Meets most required skills and the experience band; remaining "
            "gaps are minor or clearly learnable.",
            "Meets or exceeds essentially every stated requirement; reads "
            "like the target candidate.",
        ],
    },
    "job_quality": {
        "type": "score",
        "instructions": (
            "Rate the quality of the job itself for this candidate: posted "
            "compensation vs. their salary preferences, benefits vs. their "
            "required/preferred benefits, travel burden, employment type, "
            "and overall working conditions implied by the posting. Judge "
            "only what the posting states or clearly implies."
        ),
        "criteria": [
            "Clearly poor: pay below the candidate's unacceptable floor, "
            "heavy travel, or exploitative terms.",
            "Below the candidate's stated needs on pay, benefits, or "
            "conditions in a significant way.",
            "Adequate: roughly meets the acceptable minimums with nothing "
            "compelling beyond them.",
            "Good: meets the acceptable bar and several preferences "
            "(target pay range, benefits, low travel).",
            "Excellent: meets or beats the preferred targets across pay, "
            "benefits, and conditions.",
        ],
    },
    "location_fit": {
        "type": "score",
        "instructions": (
            "Rate the location/logistics fit. IMPORTANT: if the job is "
            "remote (see job_posting.remote_policy) and the candidate "
            "accepts remote work, location fit is PERFECT regardless of "
            "the city listed on the posting — for remote roles the posted "
            "location is just the employer's office, not where the "
            "candidate must live. Judge geography only for onsite or "
            "hybrid roles: are they in or near one of the candidate's "
            "preferred locations, or is the candidate willing to "
            "relocate?"
        ),
        "criteria": [
            "Hard conflict: an ONSITE or HYBRID role far outside every "
            "preferred location with no relocation willingness, or a "
            "workplace policy the candidate lists as unacceptable. Never "
            "this level for a remote role the candidate accepts.",
            "Poor: onsite/hybrid with a commuting or relocation burden "
            "the candidate has not signaled willingness to accept.",
            "Workable: onsite/hybrid within reach of a preferred "
            "location, with some friction.",
            "Good: onsite/hybrid comfortably in a preferred location, or "
            "an accepted remote policy with minor caveats (e.g. "
            "occasional office days).",
            "Ideal: a REMOTE role and the candidate accepts remote (the "
            "posted office city is irrelevant), or onsite/hybrid exactly "
            "in a preferred location.",
        ],
    },
    "career_fit": {
        "type": "score",
        "instructions": (
            "Rate how well this role advances the candidate's career "
            "trajectory: seniority alignment with their history (neither a "
            "big step down nor an unrealistic jump), growth potential, and "
            "consistency with the direction their recent roles and stated "
            "preferences point."
        ),
        "criteria": [
            "A clear step backward or sideways into a dead end for this "
            "candidate's trajectory.",
            "Mild regression or stagnation; little growth on offer.",
            "Lateral move: sustains the trajectory without advancing it.",
            "Solid step: appropriate seniority with room to grow in the "
            "candidate's direction.",
            "Strong career move: right seniority and clear advancement "
            "along the candidate's trajectory.",
        ],
    },
    "posting_quality": {
        "type": "score",
        "instructions": (
            "Rate the credibility and quality of the posting itself, "
            "independent of the candidate: specificity of scope and "
            "responsibilities, disclosed compensation, realistic "
            "requirements, and absence of ghost-job or spam signals "
            "(vague everything, buzzword soup, always-hiring evergreen "
            "reqs, MLM/commission-only patterns)."
        ),
        "criteria": [
            "Reads like spam or a ghost job: vague, contradictory, or "
            "bait-style posting.",
            "Multiple red flags: undisclosed comp plus vague scope or "
            "inflated requirement lists.",
            "Ordinary posting: some vagueness, nothing alarming.",
            "Solid posting: concrete responsibilities and requirements, "
            "mostly transparent.",
            "Excellent posting: specific scope, disclosed comp, coherent "
            "requirements from a clearly real team.",
        ],
    },
    "apply": {
        "type": "noul",
        "instructions": (
            "Should this candidate spend their limited time applying to "
            "this job?"
        ),
        "criteria": {
            "true": (
                "A tailored application has a realistic chance of an "
                "interview; the fit justifies the effort."
            ),
            "false": (
                "The application would very likely be screened out, or a "
                "hard blocker makes the role a poor use of time."
            ),
        },
    },
}

# ---- User-tunable scoring prompts -----------------------------------------
#
# The five dimension prompts (instructions + ordered criteria) and their
# weights in the overall average are editable from Settings → Jev
# scoring. Overrides persist on the claude_config volume (same git-proof
# home as the worker settings), so "tell Jev what to prioritize" is a
# settings edit, not a code change. The candidate profile/state and the
# apply yes/no judgment are NOT exposed. A dimension's criteria list may
# be 2-10 levels (worst → best); scores rescale to 0-100 by its own
# length.

_SETTINGS_PATH = Path("/root/.claude/jsp-jev-settings.json")
MIN_CRITERIA = 2
MAX_CRITERIA = 10
MAX_WEIGHT = 5.0


def _load_settings() -> dict:
    try:
        data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {}


def _valid_override(o: Any) -> Optional[dict]:
    """Return a cleaned {instructions, criteria} override, or None if
    unusable (falls back to the default prompt)."""
    if not isinstance(o, dict):
        return None
    instructions = str(o.get("instructions") or "").strip()[:2000]
    criteria = [
        str(c).strip()[:600]
        for c in (o.get("criteria") or [])
        if str(c).strip()
    ]
    if not instructions or not (MIN_CRITERIA <= len(criteria) <= MAX_CRITERIA):
        return None
    return {"instructions": instructions, "criteria": criteria}


def get_scoring_config() -> dict:
    """Effective per-dimension config for the API/UI: prompt text,
    criteria, weight, and whether it's overridden — plus the defaults so
    the UI can offer reset."""
    data = _load_settings()
    overrides = data.get("overrides") if isinstance(data.get("overrides"), dict) else {}
    weights = data.get("weights") if isinstance(data.get("weights"), dict) else {}
    dims = []
    for key, label in SCORE_DIMENSIONS:
        default = _QUESTIONS[key]
        ov = _valid_override(overrides.get(key))
        try:
            w = float(weights.get(key, 1.0))
        except (TypeError, ValueError):
            w = 1.0
        dims.append({
            "key": key,
            "label": label,
            "instructions": (ov or default)["instructions"],
            "criteria": list((ov or default)["criteria"]),
            "weight": max(0.0, min(MAX_WEIGHT, w)),
            "overridden": ov is not None,
            "default_instructions": default["instructions"],
            "default_criteria": list(default["criteria"]),
        })
    return {"dimensions": dims}


def save_scoring_config(
    overrides: dict[str, Any], weights: dict[str, Any]
) -> dict:
    """Persist prompt overrides + weights. An override missing/invalid
    for a key resets that dimension to the default. Returns the new
    effective config."""
    keys = {k for k, _ in SCORE_DIMENSIONS}
    clean_ov: dict[str, dict] = {}
    for key, o in (overrides or {}).items():
        if key not in keys:
            continue
        v = _valid_override(o)
        if v is not None:
            default = _QUESTIONS[key]
            # Storing a byte-identical copy of the default is noise, not
            # an override.
            if (
                v["instructions"] != default["instructions"]
                or v["criteria"] != list(default["criteria"])
            ):
                clean_ov[key] = v
    clean_w: dict[str, float] = {}
    for key, w in (weights or {}).items():
        if key not in keys:
            continue
        try:
            wf = float(w)
        except (TypeError, ValueError):
            continue
        wf = max(0.0, min(MAX_WEIGHT, wf))
        if wf != 1.0:
            clean_w[key] = wf
    try:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_PATH.write_text(
            json.dumps({"overrides": clean_ov, "weights": clean_w}, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        log.warning("Failed to persist Jev scoring settings: %s", exc)
    return get_scoring_config()


def _build_questions() -> tuple[dict[str, Any], dict[str, int], dict[str, float]]:
    """Merged question map for the API call, plus per-dimension level
    counts and weights."""
    cfg = get_scoring_config()
    questions: dict[str, Any] = {}
    levels: dict[str, int] = {}
    weights: dict[str, float] = {}
    for d in cfg["dimensions"]:
        questions[d["key"]] = {
            "type": "score",
            "instructions": d["instructions"],
            "criteria": d["criteria"],
        }
        levels[d["key"]] = len(d["criteria"])
        weights[d["key"]] = d["weight"]
    questions["apply"] = _QUESTIONS["apply"]
    return questions, levels, weights


class JevError(RuntimeError):
    """HTTP / protocol failure from the Jev API. The message embeds the
    status code + body snippet, so the queue worker's rate-limit
    detector (which matches ' 429', 'rate limit', …) parks the task on
    quota errors instead of burning retries."""


async def _post(api_key: str, state: dict, questions: dict, timeout_seconds: int) -> dict:
    """One System One round-trip; returns the `answers` map."""
    import httpx

    timeout = httpx.Timeout(connect=15.0, read=float(timeout_seconds), write=30.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(
                _API_URL,
                json={"state": state, "model": _MODEL, "questions": questions},
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            raise JevError(f"Jev API transport error: {exc}") from exc
    if resp.status_code >= 400:
        raise JevError(f"Jev API HTTP {resp.status_code}: {resp.text[:500]}")
    try:
        return resp.json()["answers"]
    except (KeyError, ValueError) as exc:
        raise JevError(f"Jev API returned an unexpected shape: {resp.text[:500]}") from exc


# ---- Email triage ----------------------------------------------------------
#
# First rung of the email-classification ladder (Jev → LLM → human). Each
# email type is one yes/no question, so Jev returns an independent,
# calibrated probability per type; the caller accepts Jev's answer only
# when one type clearly wins, and escalates to the LLM classifier
# otherwise.

EMAIL_INTENT_QUESTIONS: dict[str, str] = {
    "rejection": "The employer is declining the candidate / not moving forward with their application.",
    "interview_invite": "The employer wants to schedule a conversation with the candidate: a recruiter call, phone screen, or interview.",
    "take_home_assigned": "The candidate is asked to complete something before talking to a person: an online assessment, coding test, take-home exercise, screening questionnaire, or one-way video interview.",
    "offer": "The employer is extending a job offer to the candidate.",
    "withdrew": "This confirms that the candidate withdrew their own application.",
    "ghosted": "The employer closed the role or the candidate's application without any interview and without a direct rejection.",
    "status_update": "A job-application status update that requires no decision: an application-received confirmation, 'still reviewing', or 'position on hold'.",
    "unrelated": "This email is not about one of the candidate's job applications at all (marketing, job alerts, newsletters, personal mail).",
}


async def classify_email(
    api_key: str, *, email_state: dict[str, Any], timeout_seconds: int = 45
) -> dict[str, float]:
    """Return {intent: probability} for every email type, plus
    "_phone_screen": probability that an interview invite is only a
    first recruiter / phone screen."""
    questions: dict[str, Any] = {
        key: {
            "type": "noul",
            "instructions": "Does this email belong in this category? " + text,
            "criteria": {
                "true": "Yes — this is the email's main purpose.",
                "false": "No — the email is about something else.",
            },
        }
        for key, text in EMAIL_INTENT_QUESTIONS.items()
    }
    questions["_phone_screen"] = {
        "type": "noul",
        "instructions": (
            "If this email invites the candidate to talk, is it only a first "
            "call with a recruiter / phone screen (rather than an interview "
            "with the hiring team)?"
        ),
        "criteria": {"true": "First recruiter call or phone screen.",
                     "false": "Team interview, or not an invitation at all."},
    }
    answers = await _post(api_key, email_state, questions, timeout_seconds)
    try:
        return {k: float(answers[k]["noul"]) for k in questions}
    except (KeyError, TypeError, ValueError) as exc:
        raise JevError(f"Jev email triage: unexpected answer shape: {answers!r}"[:500]) from exc


async def score_job_fit(
    api_key: str,
    *,
    job_state: dict[str, Any],
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """One evaluation round-trip covering all five dimensions plus the
    worth-applying judgment. Returns a jd_analysis-shaped dict:
    {fit_score (0-100 int — average of the dimensions),
     scores ({dimension: {score: 0-100 int, confidence: 0-1}}),
     recommendation ("go"/"maybe"/"no-go"), confidence (0-1, mean),
     apply_probability (0-1), engine ("jev")}."""
    questions, levels, weights = _build_questions()
    answers = await _post(api_key, job_state, questions, timeout_seconds)

    def _to_pct(raw_score: float, n: int) -> int:
        # Jev's score is the probability-weighted level INDEX, 0..N-1 —
        # legend and probabilities are keyed "0".."N-1" (docs example: 95%
        # on level 1 + 5% on level 2 → score 1.05). Rescale to 0-100,
        # clamped defensively.
        top = float(max(n, 2) - 1)
        clamped = min(max(raw_score, 0.0), top)
        return int(round(clamped / top * 100.0))

    try:
        scores: dict[str, dict[str, float | int]] = {}
        confidences: list[float] = []
        for key, _label in SCORE_DIMENSIONS:
            ans = answers[key]
            conf = float(ans.get("confidence") or 0.0)
            scores[key] = {
                "score": _to_pct(float(ans["score"]), levels.get(key, 5)),
                "confidence": round(conf, 3),
            }
            confidences.append(conf)
        apply_p = float(answers["apply"]["noul"])
    except (KeyError, TypeError, ValueError) as exc:
        raise JevError(
            f"Jev API returned an unexpected shape: {answers!r}"[:500]
        ) from exc

    # Weighted average — Settings → Jev scoring controls the weights
    # (0 drops a dimension from the headline while still reporting its
    # subscore). All-zero weights degrade to a plain average.
    total_w = sum(weights.get(k, 1.0) for k, _ in SCORE_DIMENSIONS)
    if total_w <= 0:
        fit_score = int(
            round(sum(s["score"] for s in scores.values()) / len(scores))
        )
    else:
        fit_score = int(
            round(
                sum(
                    scores[k]["score"] * weights.get(k, 1.0)
                    for k, _ in SCORE_DIMENSIONS
                )
                / total_w
            )
        )
    recommendation = (
        "go" if apply_p >= 0.65 else "no-go" if apply_p <= 0.35 else "maybe"
    )
    return {
        "engine": "jev",
        "fit_score": fit_score,
        "scores": scores,
        "weights": {k: weights.get(k, 1.0) for k, _ in SCORE_DIMENSIONS},
        "recommendation": recommendation,
        "confidence": round(sum(confidences) / len(confidences), 3),
        "apply_probability": round(apply_p, 3),
    }
