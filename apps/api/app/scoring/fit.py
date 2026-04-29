"""Pure-Python fit-score computation.

A `TrackedJob` row is scored 0-100 against the user's `JobPreferences`
+ `JobCriterion` list. No Claude calls — deterministic so the score is
reproducible across calls, auditable in the UI, and cheap enough to
recompute on every preference / criterion edit.

Architecture:
- Each "component" of the score has a weight (0-100) and a verdict
  ("match" / "miss" / "veto" / "unknown"). Weight 0 means the user
  flagged the component as informational (does not affect score).
- "Veto" verdicts force `score = 0` and short-circuit. The user can
  declare a hard veto by setting an `unacceptable` criterion to
  `weight = 100` ("never work in defence industry"); same applies for
  built-in components when the JD's value lands in the user's
  `..._unacceptable` lists.
- All other components contribute weighted points to the average:
  `score = round(100 * Σ(weight × matched_pct) / Σ(weight))`
  where `matched_pct ∈ [0..1]` is how well the component matched.

Built-in components (defaults in `DEFAULT_BUILTIN_WEIGHTS`):
- salary, remote_policy, location, experience_level, employment_type,
  travel, hours.

User-defined criteria (`JobCriterion` rows) layer on top of those.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.jobs import Organization, TrackedJob
from app.models.preferences import JobCriterion, JobPreferences
from app.models.user import User


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

# Component keys that the user can override via JobPreferences.builtin_weights.
BUILTIN_KEYS: tuple[str, ...] = (
    "salary",
    "remote_policy",
    "location",
    "experience_level",
    "employment_type",
    "travel",
    "hours",
)

DEFAULT_BUILTIN_WEIGHTS: dict[str, int] = {
    "salary": 70,
    "remote_policy": 60,
    "location": 50,
    "experience_level": 60,
    "employment_type": 50,
    "travel": 30,
    "hours": 30,
}

# Weight at or above which a matching `unacceptable` criterion becomes a
# hard veto (forces score = 0). Below this, the criterion still
# subtracts because matched-unacceptable contributes 0 to numerator
# while still occupying weight in the denominator.
VETO_THRESHOLD = 100


# ---------------------------------------------------------------------------
# Component result type
# ---------------------------------------------------------------------------


@dataclass
class Component:
    key: str
    label: str
    weight: int
    verdict: str  # match | partial | miss | veto | unknown | informational
    matched_pct: float  # 0..1
    detail: str
    tier: Optional[str] = None  # for criterion components

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "weight": self.weight,
            "verdict": self.verdict,
            "matched_pct": round(self.matched_pct, 3),
            "detail": self.detail,
            "tier": self.tier,
        }


@dataclass
class FitResult:
    score: Optional[int]
    vetoed: bool
    veto_reason: Optional[str]
    components: list[Component] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "vetoed": self.vetoed,
            "veto_reason": self.veto_reason,
            "components": [c.to_dict() for c in self.components],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_weight(prefs: Optional[JobPreferences], key: str) -> int:
    """Pick the user's override for a built-in component or fall back
    to the shipped default. Clamped to [0, 100]."""
    base = DEFAULT_BUILTIN_WEIGHTS.get(key, 50)
    if prefs is None or not isinstance(prefs.builtin_weights, dict):
        return base
    raw = prefs.builtin_weights.get(key)
    if raw is None:
        return base
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return base
    return max(0, min(100, v))


def _str_in_list(value: Optional[str], candidates: Optional[Iterable]) -> bool:
    if not value or not candidates:
        return False
    norm_value = value.strip().lower()
    for c in candidates:
        if not isinstance(c, str):
            continue
        if c.strip().lower() == norm_value:
            return True
    return False


def _haystack(job: TrackedJob, org_name: Optional[str]) -> str:
    """Searchable lower-cased text across the fields a free-form
    criterion might match against."""
    pieces = [
        job.title,
        job.job_description,
        job.location,
        org_name,
        " ".join(job.required_skills or []) if isinstance(job.required_skills, list) else None,
        " ".join(job.nice_to_have_skills or []) if isinstance(job.nice_to_have_skills, list) else None,
    ]
    return " ".join((p or "").lower() for p in pieces if p)


def _word_match(term: str, hay: str) -> bool:
    """True if `term` appears in `hay` as a whole word (case-insensitive,
    punctuation-tolerant). Falls through to a plain substring check if
    the term contains characters that wouldn't tokenize cleanly."""
    if not term or not hay:
        return False
    t = term.strip().lower()
    if not t:
        return False
    # Try word-boundary regex first.
    try:
        pattern = r"\b" + re.escape(t) + r"\b"
        if re.search(pattern, hay):
            return True
    except re.error:
        pass
    return t in hay


# ---------------------------------------------------------------------------
# Built-in scorers
# ---------------------------------------------------------------------------


def _score_salary(
    job: TrackedJob, prefs: Optional[JobPreferences], weight: int
) -> Component:
    """Job's salary range vs. the user's preferred / acceptable / veto
    thresholds. Uses salary_min as the "what they're advertising" anchor."""
    job_min = float(job.salary_min) if job.salary_min is not None else None
    job_max = float(job.salary_max) if job.salary_max is not None else None
    if job_min is None and job_max is None:
        return Component(
            key="salary",
            label="Salary",
            weight=weight,
            verdict="unknown",
            matched_pct=0.0,
            detail="No salary on the job posting.",
        )
    if prefs is None:
        return Component(
            key="salary",
            label="Salary",
            weight=weight,
            verdict="unknown",
            matched_pct=0.0,
            detail="No salary preferences set.",
        )
    target = (
        float(prefs.salary_preferred_target)
        if prefs.salary_preferred_target is not None
        else None
    )
    accept = (
        float(prefs.salary_acceptable_min)
        if prefs.salary_acceptable_min is not None
        else None
    )
    veto = (
        float(prefs.salary_unacceptable_below)
        if prefs.salary_unacceptable_below is not None
        else None
    )
    # Use the high end of the posted range to evaluate "could meet
    # target", and the low end to evaluate "definitely below floor".
    high = job_max if job_max is not None else job_min
    low = job_min if job_min is not None else job_max
    if veto is not None and high is not None and high < veto:
        return Component(
            key="salary",
            label="Salary",
            weight=weight,
            verdict="veto",
            matched_pct=0.0,
            detail=f"Posted ≤{int(high):,} is below your hard floor ({int(veto):,}).",
        )
    if target is not None and high is not None and high >= target:
        return Component(
            key="salary",
            label="Salary",
            weight=weight,
            verdict="match",
            matched_pct=1.0,
            detail=f"Posted up to {int(high):,} meets your preferred target ({int(target):,}).",
        )
    if accept is not None and high is not None and high >= accept:
        # Partial credit scaled into the [0.5, 0.95] band based on how
        # close the posted upper end is to the target (if a target is
        # set) or just 0.7 baseline.
        pct = 0.7
        if target is not None and target > accept:
            pct = max(0.5, min(0.95, 0.5 + 0.45 * ((high - accept) / (target - accept))))
        return Component(
            key="salary",
            label="Salary",
            weight=weight,
            verdict="partial",
            matched_pct=pct,
            detail=(
                f"Posted up to {int(high):,} clears acceptable ({int(accept):,}) "
                f"but is below your target ({int(target):,})."
                if target is not None
                else f"Posted up to {int(high):,} clears acceptable ({int(accept):,})."
            ),
        )
    return Component(
        key="salary",
        label="Salary",
        weight=weight,
        verdict="miss",
        matched_pct=0.0,
        detail=f"Posted up to {int(high):,} is below acceptable ({int(accept):,})."
        if accept is not None and high is not None
        else "Salary doesn't meet preferences.",
    )


def _score_remote_policy(
    job: TrackedJob, prefs: Optional[JobPreferences], weight: int
) -> Component:
    if not job.remote_policy:
        return Component(
            key="remote_policy",
            label="Remote policy",
            weight=weight,
            verdict="unknown",
            matched_pct=0.0,
            detail="JD didn't specify remote policy.",
        )
    if prefs is None:
        return Component(
            key="remote_policy",
            label="Remote policy",
            weight=weight,
            verdict="unknown",
            matched_pct=0.0,
            detail="No remote-policy preference set.",
        )
    if _str_in_list(job.remote_policy, prefs.remote_policies_unacceptable):
        return Component(
            key="remote_policy",
            label="Remote policy",
            weight=weight,
            verdict="veto",
            matched_pct=0.0,
            detail=f"Job is {job.remote_policy} — flagged unacceptable in your prefs.",
        )
    if prefs.remote_policy_preferred and prefs.remote_policy_preferred == job.remote_policy:
        return Component(
            key="remote_policy",
            label="Remote policy",
            weight=weight,
            verdict="match",
            matched_pct=1.0,
            detail=f"Job is {job.remote_policy}, your preferred policy.",
        )
    if _str_in_list(job.remote_policy, prefs.remote_policies_acceptable):
        return Component(
            key="remote_policy",
            label="Remote policy",
            weight=weight,
            verdict="partial",
            matched_pct=0.7,
            detail=f"Job is {job.remote_policy} — acceptable but not your preferred.",
        )
    return Component(
        key="remote_policy",
        label="Remote policy",
        weight=weight,
        verdict="miss",
        matched_pct=0.0,
        detail=f"Job is {job.remote_policy} — outside your stated preferences.",
    )


def _score_location(
    job: TrackedJob, prefs: Optional[JobPreferences], weight: int
) -> Component:
    loc = (job.location or "").strip()
    if not loc:
        return Component(
            key="location",
            label="Location",
            weight=weight,
            verdict="unknown",
            matched_pct=0.0,
            detail="JD didn't specify a location.",
        )
    if prefs is None:
        return Component(
            key="location",
            label="Location",
            weight=weight,
            verdict="unknown",
            matched_pct=0.0,
            detail="No location preferences set.",
        )
    pref_locs = prefs.preferred_locations or []
    loc_lower = loc.lower()
    for entry in pref_locs:
        if not isinstance(entry, dict):
            continue
        name = (entry.get("name") or "").lower().strip()
        if not name:
            continue
        if name in loc_lower or loc_lower in name:
            return Component(
                key="location",
                label="Location",
                weight=weight,
                verdict="match",
                matched_pct=1.0,
                detail=f'Job at "{loc}" matches preferred location "{name}".',
            )
    if prefs.willing_to_relocate:
        return Component(
            key="location",
            label="Location",
            weight=weight,
            verdict="partial",
            matched_pct=0.5,
            detail=f'Job at "{loc}" — outside preferred but you\'re open to relocating.',
        )
    return Component(
        key="location",
        label="Location",
        weight=weight,
        verdict="miss",
        matched_pct=0.0,
        detail=f'Job at "{loc}" matches none of your preferred locations.',
    )


def _score_experience_level(
    job: TrackedJob, prefs: Optional[JobPreferences], weight: int
) -> Component:
    level = (job.experience_level or "").strip()
    if not level:
        return Component(
            key="experience_level",
            label="Experience level",
            weight=weight,
            verdict="unknown",
            matched_pct=0.0,
            detail="JD didn't specify an experience level.",
        )
    if prefs is None:
        return Component(
            key="experience_level",
            label="Experience level",
            weight=weight,
            verdict="unknown",
            matched_pct=0.0,
            detail="No experience-level preference set.",
        )
    if _str_in_list(level, prefs.experience_levels_unacceptable):
        return Component(
            key="experience_level",
            label="Experience level",
            weight=weight,
            verdict="veto",
            matched_pct=0.0,
            detail=f"Level '{level}' flagged unacceptable in your prefs.",
        )
    if prefs.experience_level_preferred and prefs.experience_level_preferred == level:
        return Component(
            key="experience_level",
            label="Experience level",
            weight=weight,
            verdict="match",
            matched_pct=1.0,
            detail=f"Level '{level}' is your preferred level.",
        )
    if _str_in_list(level, prefs.experience_levels_acceptable):
        return Component(
            key="experience_level",
            label="Experience level",
            weight=weight,
            verdict="partial",
            matched_pct=0.7,
            detail=f"Level '{level}' is acceptable but not your preferred.",
        )
    return Component(
        key="experience_level",
        label="Experience level",
        weight=weight,
        verdict="miss",
        matched_pct=0.0,
        detail=f"Level '{level}' isn't in your stated preferences.",
    )


def _score_employment_type(
    job: TrackedJob, prefs: Optional[JobPreferences], weight: int
) -> Component:
    et = (job.employment_type or "").strip()
    if not et:
        return Component(
            key="employment_type",
            label="Employment type",
            weight=weight,
            verdict="unknown",
            matched_pct=0.0,
            detail="JD didn't specify employment type.",
        )
    if prefs is None:
        return Component(
            key="employment_type",
            label="Employment type",
            weight=weight,
            verdict="unknown",
            matched_pct=0.0,
            detail="No employment-type preference set.",
        )
    if _str_in_list(et, prefs.employment_types_unacceptable):
        return Component(
            key="employment_type",
            label="Employment type",
            weight=weight,
            verdict="veto",
            matched_pct=0.0,
            detail=f"Type '{et}' flagged unacceptable in your prefs.",
        )
    if _str_in_list(et, prefs.employment_types_preferred):
        return Component(
            key="employment_type",
            label="Employment type",
            weight=weight,
            verdict="match",
            matched_pct=1.0,
            detail=f"Type '{et}' is on your preferred list.",
        )
    if _str_in_list(et, prefs.employment_types_acceptable):
        return Component(
            key="employment_type",
            label="Employment type",
            weight=weight,
            verdict="partial",
            matched_pct=0.7,
            detail=f"Type '{et}' is acceptable but not your preferred.",
        )
    return Component(
        key="employment_type",
        label="Employment type",
        weight=weight,
        verdict="miss",
        matched_pct=0.0,
        detail=f"Type '{et}' isn't in your stated preferences.",
    )


def _score_travel(
    job: TrackedJob, prefs: Optional[JobPreferences], weight: int
) -> Component:
    """Travel preference is in prefs but the JD doesn't usually expose
    a percentage; scored "unknown" unless the user has hard limits AND
    the JD specified one. Currently always unknown — left in for shape
    so the breakdown panel can show "no data" honestly."""
    return Component(
        key="travel",
        label="Travel",
        weight=weight,
        verdict="unknown",
        matched_pct=0.0,
        detail="No travel data on JD; component skipped.",
    )


def _score_hours(
    job: TrackedJob, prefs: Optional[JobPreferences], weight: int
) -> Component:
    """Same as travel — JDs rarely state weekly hours explicitly."""
    return Component(
        key="hours",
        label="Hours",
        weight=weight,
        verdict="unknown",
        matched_pct=0.0,
        detail="No hours data on JD; component skipped.",
    )


# ---------------------------------------------------------------------------
# Criterion scorer
# ---------------------------------------------------------------------------


def _score_criterion(
    criterion: JobCriterion,
    job: TrackedJob,
    org_name: Optional[str],
) -> Component:
    """Score a single user-defined criterion against the job. The match
    rule is: substring (whole word where possible) of criterion.value
    in a haystack composed of title, JD body, location, organization
    name, and required/nice-to-have skills.

    Tier semantics:
    - preferred / acceptable: matching the value is positive — full
      contribution to the numerator. Not matching adds nothing.
    - unacceptable: matching the value is *negative*. Weight ≥
      VETO_THRESHOLD → hard veto. Otherwise: still adds weight to the
      denominator but contributes 0 to numerator (penalizes the score).
      Not-matched unacceptable criteria add positively (job avoids the
      thing).
    """
    weight = int(criterion.weight or 0)
    weight = max(0, min(100, weight))
    label = f"{criterion.category.replace('_', ' ').title()}: {criterion.value}"

    if weight == 0:
        return Component(
            key=f"criterion:{criterion.id}",
            label=label,
            weight=0,
            verdict="informational",
            matched_pct=0.0,
            detail=f"{criterion.tier} — informational only (weight 0).",
            tier=criterion.tier,
        )

    hay = _haystack(job, org_name)
    matched = _word_match(criterion.value, hay)

    if criterion.tier == "unacceptable":
        if matched and weight >= VETO_THRESHOLD:
            return Component(
                key=f"criterion:{criterion.id}",
                label=label,
                weight=weight,
                verdict="veto",
                matched_pct=0.0,
                detail=f"Job matches an unacceptable criterion ({criterion.category} = {criterion.value}).",
                tier=criterion.tier,
            )
        if matched:
            return Component(
                key=f"criterion:{criterion.id}",
                label=label,
                weight=weight,
                verdict="miss",
                matched_pct=0.0,
                detail=f"Job matches an unacceptable criterion ({criterion.category} = {criterion.value}).",
                tier=criterion.tier,
            )
        return Component(
            key=f"criterion:{criterion.id}",
            label=label,
            weight=weight,
            verdict="match",
            matched_pct=1.0,
            detail=f"Job avoids the unacceptable criterion ({criterion.category} = {criterion.value}).",
            tier=criterion.tier,
        )

    # preferred / acceptable: match is positive.
    if matched:
        pct = 1.0 if criterion.tier == "preferred" else 0.85
        return Component(
            key=f"criterion:{criterion.id}",
            label=label,
            weight=weight,
            verdict="match",
            matched_pct=pct,
            detail=f"JD references '{criterion.value}'.",
            tier=criterion.tier,
        )
    return Component(
        key=f"criterion:{criterion.id}",
        label=label,
        weight=weight,
        verdict="miss",
        matched_pct=0.0,
        detail=f"JD doesn't reference '{criterion.value}'.",
        tier=criterion.tier,
    )


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


async def _load_prefs(db: AsyncSession, user_id: int) -> Optional[JobPreferences]:
    return (
        await db.execute(
            select(JobPreferences).where(
                JobPreferences.user_id == user_id,
                JobPreferences.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def _load_criteria(db: AsyncSession, user_id: int) -> list[JobCriterion]:
    return list(
        (
            await db.execute(
                select(JobCriterion).where(
                    JobCriterion.user_id == user_id,
                    JobCriterion.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    )


async def _resolve_org_name(db: AsyncSession, org_id: Optional[int]) -> Optional[str]:
    if not org_id:
        return None
    row = (
        await db.execute(select(Organization.name).where(Organization.id == org_id))
    ).first()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def compute_fit_score(
    db: AsyncSession,
    user: User,
    job: TrackedJob,
) -> FitResult:
    """Compute the deterministic fit score for `job` against `user`'s
    preferences and criteria. Pure read-only — caller decides whether
    to persist the result."""
    prefs = await _load_prefs(db, user.id)
    criteria = await _load_criteria(db, user.id)
    org_name = await _resolve_org_name(db, job.organization_id)

    components: list[Component] = []
    components.append(_score_salary(job, prefs, _resolve_weight(prefs, "salary")))
    components.append(
        _score_remote_policy(job, prefs, _resolve_weight(prefs, "remote_policy"))
    )
    components.append(
        _score_location(job, prefs, _resolve_weight(prefs, "location"))
    )
    components.append(
        _score_experience_level(
            job, prefs, _resolve_weight(prefs, "experience_level")
        )
    )
    components.append(
        _score_employment_type(
            job, prefs, _resolve_weight(prefs, "employment_type")
        )
    )
    components.append(_score_travel(job, prefs, _resolve_weight(prefs, "travel")))
    components.append(_score_hours(job, prefs, _resolve_weight(prefs, "hours")))

    for c in criteria:
        components.append(_score_criterion(c, job, org_name))

    veto_reason: Optional[str] = None
    numerator = 0.0
    denominator = 0.0
    for comp in components:
        if comp.verdict == "veto":
            veto_reason = comp.detail
            break
        # Skip components we couldn't evaluate or that the user
        # explicitly muted via weight=0.
        if comp.verdict in ("unknown", "informational"):
            continue
        if comp.weight == 0:
            continue
        denominator += comp.weight
        numerator += comp.weight * comp.matched_pct

    if veto_reason is not None:
        return FitResult(
            score=0,
            vetoed=True,
            veto_reason=veto_reason,
            components=components,
        )
    if denominator <= 0:
        return FitResult(
            score=None,
            vetoed=False,
            veto_reason=None,
            components=components,
        )
    score = int(round(100 * numerator / denominator))
    return FitResult(
        score=max(0, min(100, score)),
        vetoed=False,
        veto_reason=None,
        components=components,
    )


def apply_fit_score_to_job(job: TrackedJob, result: FitResult) -> None:
    """Persist `result` onto `job.fit_summary`. Preserves any existing
    qualitative summary the JD-analyzer wrote so re-scoring doesn't
    erase analyst output."""
    prior = job.fit_summary if isinstance(job.fit_summary, dict) else {}
    out = dict(prior)
    out["score"] = result.score
    out["vetoed"] = result.vetoed
    out["veto_reason"] = result.veto_reason
    out["breakdown"] = [c.to_dict() for c in result.components]
    out["scored_by"] = "deterministic"
    job.fit_summary = out
