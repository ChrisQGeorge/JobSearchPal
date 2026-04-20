---
name: job-fit-scorer
description: Scores a TrackedJob against the user's JobPreferences, JobCriterion, and WorkAuthorization. Produces a match score, alignments, mismatches, and dealbreakers. Use when a TrackedJob is created, updated, or analyzed.
---

# Job Fit Scorer

## Purpose
Compare a job to the user's preferences and flag dealbreakers before time is spent on it.

## Inputs
- `tracked_job_id`

## Outputs
- Writes to `TrackedJob.fit_summary` with:
  - `score` (0–100)
  - `alignments`: list of `{ category, value, tier, note }`
  - `mismatches`: list of `{ category, value, user_tier, job_signal, note }`
  - `dealbreakers`: list of `{ category, value, reason }`

## Guardrails
- Treat work-authorization mismatches (sponsorship not offered when the user needs it) as dealbreakers by default; the user may override per-job.
- If `jd_analysis` is missing, invoke `jd-analyzer` first.
