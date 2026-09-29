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
            "Rate the location/logistics fit: is the job remote and the "
            "candidate accepts remote? If onsite or hybrid, is it in or "
            "near one of the candidate's preferred locations, or are they "
            "willing to relocate? Treat an onsite role far from every "
            "preferred location with no relocation willingness as the "
            "worst level."
        ),
        "criteria": [
            "Hard conflict: onsite far outside every preferred location "
            "and the candidate won't relocate, or a remote policy the "
            "candidate finds unacceptable.",
            "Poor: likely commuting/relocation burden the candidate has "
            "not signaled willingness to accept.",
            "Workable: hybrid or onsite within reach of a preferred "
            "location, with some friction.",
            "Good: matches an accepted remote policy or sits comfortably "
            "in a preferred location.",
            "Ideal: fully matches the candidate's stated location and "
            "remote-policy preferences.",
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

_LEVELS_PER_DIMENSION = 5


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
    """One evaluation round-trip covering all five dimensions plus the
    worth-applying judgment. Returns a jd_analysis-shaped dict:
    {fit_score (0-100 int — average of the dimensions),
     scores ({dimension: {score: 0-100 int, confidence: 0-1}}),
     recommendation ("go"/"maybe"/"no-go"), confidence (0-1, mean),
     apply_probability (0-1), engine ("jev")}."""
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
    def _to_pct(raw_score: float) -> int:
        # Score answers are probability-weighted across the ordered levels
        # (1..N). Rescale to 0-100, clamped defensively — a value outside
        # the level range would otherwise produce a nonsense percentage.
        n = _LEVELS_PER_DIMENSION
        clamped = min(max(raw_score, 1.0), float(n))
        return int(round((clamped - 1.0) / (n - 1) * 100.0))

    try:
        answers = resp.json()["answers"]
        scores: dict[str, dict[str, float | int]] = {}
        confidences: list[float] = []
        for key, _label in SCORE_DIMENSIONS:
            ans = answers[key]
            conf = float(ans.get("confidence") or 0.0)
            scores[key] = {
                "score": _to_pct(float(ans["score"])),
                "confidence": round(conf, 3),
            }
            confidences.append(conf)
        apply_p = float(answers["apply"]["noul"])
    except (KeyError, TypeError, ValueError) as exc:
        raise JevError(
            f"Jev API returned an unexpected shape: {resp.text[:500]}"
        ) from exc

    fit_score = int(round(sum(s["score"] for s in scores.values()) / len(scores)))
    recommendation = (
        "go" if apply_p >= 0.65 else "no-go" if apply_p <= 0.35 else "maybe"
    )
    return {
        "engine": "jev",
        "fit_score": fit_score,
        "scores": scores,
        "recommendation": recommendation,
        "confidence": round(sum(confidences) / len(confidences), 3),
        "apply_probability": round(apply_p, 3),
    }
