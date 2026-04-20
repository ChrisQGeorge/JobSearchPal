---
name: application-tracker
description: Creates and updates TrackedJob, ApplicationEvent, and InterviewRound records from conversational input. Use when the user mentions applying to something, hearing back, or scheduling interviews.
---

# Application Tracker

## Purpose
Let the user update their job-search status through natural conversation.

## Inputs
- Free-text user message ("I just applied to Acme for Senior Widget Engineer; recruiter is Jane").

## Outputs
- Proposed new `TrackedJob` / `ApplicationEvent` / `InterviewRound` records, presented for confirmation.
- On confirm, writes via API; may also create `Task` records for suggested follow-ups.

## Guardrails
- Always present changes as a diff before writing.
- Do not invent company data — if a new Company is implied, ask before creating.
