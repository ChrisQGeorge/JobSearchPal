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

import logging
from typing import Any

log = logging.getLogger(__name__)

# ApiCredential provider key — keep in sync with KNOWN_PROVIDERS in
# web/src/app/(app)/settings/_panels/SettingsPanels.tsx.
JEV_PROVIDER = "typesafe_jev"

_API_URL = "https://api.typesafe.ai/v1/systemone"
_MODEL = "jev-latest"

# Ordered worst → best. Jev's score answer is the probability-weighted
# position across these levels; we rescale to the app's 0-100 fit_score.
_FIT_LEVELS = [
    "No real fit: the candidate lacks most core requirements, or a hard "
    "blocker applies (location/onsite conflict, missing mandatory "
    "credential, seniority far off).",
    "Weak fit: a few transferable skills but major gaps in the required "
    "skills, domain, or experience level.",
    "Partial fit: meets roughly half the requirements; would need real "
    "ramp-up or a sympathetic hiring manager.",
    "Strong fit: meets most required skills and the experience band; gaps "
    "are minor or clearly learnable.",
    "Excellent fit: meets or exceeds the required skills, experience "
    "level, and logistics; reads like the target candidate for this "
    "posting.",
]

_QUESTIONS: dict[str, Any] = {
    "fit": {
        "type": "score",
        "instructions": (
            "Rate how strong a fit this candidate is for this specific job "
            "posting. Weigh required-skills overlap most heavily, then "
            "experience level and years, then domain relevance, then "
            "logistics (location / remote policy / work authorization) and "
            "the candidate's stated preferences where present."
        ),
        "criteria": _FIT_LEVELS,
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


class JevError(RuntimeError):
    """HTTP / protocol failure from the Jev API. The message embeds the
    status code + body snippet, so the queue worker's rate-limit
    detector (which matches ' 429', 'rate limit', …) parks the task on
    quota errors instead of burning retries."""


async def score_job_fit(
    api_key: str,
    *,
    job_state: dict[str, Any],
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """One evaluation round-trip. Returns a jd_analysis-shaped dict:
    {fit_score (0-100 int), recommendation ("go"/"maybe"/"no-go"),
    confidence (0-1), apply_probability (0-1), engine ("jev")}."""
    import httpx

    payload = {"state": job_state, "model": _MODEL, "questions": _QUESTIONS}
    timeout = httpx.Timeout(connect=15.0, read=float(timeout_seconds), write=30.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(
                _API_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            raise JevError(f"Jev API transport error: {exc}") from exc
    if resp.status_code >= 400:
        raise JevError(
            f"Jev API HTTP {resp.status_code}: {resp.text[:500]}"
        )
    try:
        answers = resp.json()["answers"]
        fit = answers["fit"]
        apply_ans = answers["apply"]
        raw_score = float(fit["score"])
        confidence = float(fit.get("confidence") or 0.0)
        apply_p = float(apply_ans["noul"])
    except (KeyError, TypeError, ValueError) as exc:
        raise JevError(
            f"Jev API returned an unexpected shape: {resp.text[:500]}"
        ) from exc

    # The score answer is probability-weighted across the ordered levels
    # (1..N). Rescale to 0-100. Clamp defensively — a value outside the
    # level range would otherwise produce a nonsense percentage.
    n = len(_FIT_LEVELS)
    pct = (min(max(raw_score, 1.0), float(n)) - 1.0) / (n - 1) * 100.0
    recommendation = (
        "go" if apply_p >= 0.65 else "no-go" if apply_p <= 0.35 else "maybe"
    )
    return {
        "engine": "jev",
        "fit_score": int(round(pct)),
        "recommendation": recommendation,
        "confidence": round(confidence, 3),
        "apply_probability": round(apply_p, 3),
    }
