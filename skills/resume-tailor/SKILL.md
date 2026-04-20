---
name: resume-tailor
description: Generates a resume tailored to a specific TrackedJob using only the user's canonical history. Use when the user has selected a job and wants a targeted resume draft.
---

# Resume Tailor

## Purpose
Produce a resume tailored to a `TrackedJob`. The skill must only draw from the user's recorded history (`WorkExperience`, `Education`, `Course`, `Skill`, `Certification`, `Project`, `Publication`, `Presentation`, `Achievement`). It must never invent employers, dates, degrees, or credentials.

## Inputs
- `tracked_job_id`: the target job.
- Optional: `persona_id`, `model_override`, `format_preset` (e.g., one-page, two-page, technical).

## Outputs
- A `GeneratedDocument` with `doc_type="resume"`, containing:
  - `content_md`: the tailored resume.
  - `prompt_snapshot`: the assembled prompt for reproducibility.
  - Coverage report: which JD requirements were addressed, which were flagged as gaps.

## Process
1. Load user history via the API.
2. Load target `TrackedJob` and its `jd_analysis` (invoke `jd-analyzer` first if missing).
3. Construct a prompt that presents the history as structured ground truth and the JD as the target.
4. Generate draft; self-check against history for any unattributed claim.
5. Persist as `GeneratedDocument`.

## Guardrails
- **No fabrication.** If a JD requirement is not truthfully covered, flag it in the coverage report rather than inventing coverage.
- Tone is set by the active `Persona` via `companion-persona`.
- Any write to history is out of scope for this skill; it is read-only against canonical data.
