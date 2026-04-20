---
name: email-drafter
description: Drafts job-search emails — application follow-ups, thank-you notes, recruiter replies, networking outreach, and salary negotiation. Parameterized by recipient and tone.
---

# Email Drafter

## Purpose
Generate a job-search email appropriate to the user's intent.

## Inputs
- `intent`: one of `follow_up`, `thank_you`, `recruiter_reply`, `networking`, `negotiation`, `other`.
- `tracked_job_id` (optional).
- `recipient`: `{ name, role, email }` (optional).
- `tone_note`: free-text nudge for phrasing.
- `humanize`: default true.

## Outputs
- A `GeneratedDocument` with `doc_type="email"`, including subject, body, and a suggested send time.

## Guardrails
- Never auto-send. The UI requires an explicit user click to send anything outbound.
- Draw facts only from canonical history.
- Default to concise; expand only when `tone_note` requests it.
