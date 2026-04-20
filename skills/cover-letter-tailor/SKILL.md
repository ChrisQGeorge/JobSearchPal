---
name: cover-letter-tailor
description: Generates a cover letter tailored to a TrackedJob. Always passes output through writing-humanizer before returning. Use when the user wants a cover letter for a specific job.
---

# Cover Letter Tailor

## Purpose
Produce a cover letter targeted at a `TrackedJob`, grounded in the user's canonical history and their `WritingSample` corpus (for voice).

## Inputs
- `tracked_job_id`
- Optional: `persona_id`, `humanize=true|false` (default true), `length_preference` (short/standard/long), `tone_note` (free text).

## Outputs
- A `GeneratedDocument` with `doc_type="cover_letter"`, `humanized=true` (unless explicitly disabled), and `humanized_from_samples` populated with the `WritingSample` IDs used.

## Process
1. Pull history, JD (and `jd_analysis`), and Writing Samples.
2. Draft the cover letter using history to support concrete claims.
3. Invoke `writing-humanizer` on the draft.
4. Persist as `GeneratedDocument`.

## Guardrails
- Do not invent facts. Draw all evidence from canonical history.
- Do not include demographic or self-identification content — that is the exclusive domain of `application-autofiller`.
