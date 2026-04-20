---
name: interview-retrospective
description: After an InterviewRound is marked complete, prompts the user for reflections, captures lessons learned, and stores them as InterviewArtifacts tagged feedback. Use right after an interview.
---

# Interview Retrospective

## Purpose
Capture immediate post-interview reflections before they fade.

## Inputs
- `interview_round_id`

## Outputs
- `InterviewArtifact` record (`kind="feedback"`) with structured reflections (what went well, what didn't, surprises, follow-ups, rating).
- Suggested updates to `prep_notes_md` on the round for next time.

## Guardrails
- Accept "I don't know" as a valid answer; do not pressure.
- Do not contact anyone or synthesize feedback from the interviewer — only record what the user provides.
