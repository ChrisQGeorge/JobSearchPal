---
name: interview-prep
description: Generates role-specific practice questions from a TrackedJob, runs mock interview drills, and stores prep docs as InterviewArtifacts. Use when the user has an upcoming round or is preparing in general.
---

# Interview Prep

## Purpose
Help the user prepare for an interview round.

## Inputs
- `tracked_job_id`
- Optional: `round_type` (behavioral / technical / system_design / etc.), `difficulty` (easy/med/hard), `duration_minutes`.

## Outputs
- A set of questions, model answers keyed to the user's history, and drill prompts.
- Artifacts persisted as `InterviewArtifact` rows (`kind="prep_doc"`).

## Guardrails
- Ground model answers in canonical history. Flag any question the user's history cannot credibly answer.
