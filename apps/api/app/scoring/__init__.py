"""Deterministic fit-scoring against the user's preferences + criteria.

Replaces the prior Claude-driven score so the number is reproducible,
auditable, and free. The Companion still produces qualitative analysis
(strengths / gaps / red flags); only the numeric `fit_score` lives
here."""
from app.scoring.fit import (
    DEFAULT_BUILTIN_WEIGHTS,
    BUILTIN_KEYS,
    compute_fit_score,
    apply_fit_score_to_job,
)

__all__ = [
    "DEFAULT_BUILTIN_WEIGHTS",
    "BUILTIN_KEYS",
    "compute_fit_score",
    "apply_fit_score_to_job",
]
